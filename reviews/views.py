from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Avg, Count

from bookings.models import Booking
from experiences.models import Experience
from tourist.utils import get_tourist_page_context
from .models import Review


def _get_tourist(user):
    """Return the TouristProfile for this user, or None."""
    profile = getattr(user, 'profile', None)
    if not profile or profile.role != 'tourist':
        return None
    return getattr(profile, 'tourist_profile', None)


def _read_review_section(request, prefix):
    """
    Read one review section from POST.

    Field names use a prefix:
        guide_rating, guide_title, guide_comment, guide_pros, guide_cons
        experience_rating, experience_title, experience_comment, ...

    Returns a dict with parsed values, plus 'attempted' = True if any
    field was non-empty (indicating the tourist tried to write this section).
    """
    rating_raw = request.POST.get(f'{prefix}_rating', '').strip()
    title = request.POST.get(f'{prefix}_title', '').strip()
    comment = request.POST.get(f'{prefix}_comment', '').strip()
    pros = request.POST.get(f'{prefix}_pros', '').strip()
    cons = request.POST.get(f'{prefix}_cons', '').strip()

    attempted = any([rating_raw, title, comment, pros, cons])

    rating_int = None
    if rating_raw:
        try:
            rating_int = int(rating_raw)
            if rating_int < 1 or rating_int > 5:
                rating_int = None
        except (TypeError, ValueError):
            rating_int = None

    return {
        'attempted': attempted,
        'rating': rating_int,
        'title': title,
        'comment': comment,
        'pros': pros,
        'cons': cons,
    }


# ============================================================
# CREATE REVIEW — Guide + Experience (Model B)
# ============================================================
@login_required
def create_review(request, booking_id):
    """
    FR-13: Tourist Reviews Guide and Experience
    Traceability: UC-13 Tourist Leaves Review

    A single page lets the tourist write up to TWO reviews for a
    completed booking:
        - A guide review (only if the booking has a guide)
        - An experience review (only if the booking has an experience)

    Both are optional. At least one must be filled. Each is created
    as its own Review row with review_type = 'guide' or 'experience'.

    Reviews are auto-approved on submit so ratings show immediately
    on Discover / Experience pages. Admin can still reject or remove
    later via the moderation tools.
    """
    tourist = _get_tourist(request.user)
    if tourist is None:
        return redirect('/providers/dashboard/')

    booking = get_object_or_404(
        Booking.objects.select_related(
            'guide', 'guide__profile__user',
            'experience',
        ),
        id=booking_id,
        visitor=tourist,
        status='completed',
    )

    has_guide = booking.guide is not None
    has_experience = booking.experience is not None

    # A booking must have at least one reviewable subject
    if not has_guide and not has_experience:
        messages.error(
            request,
            'This booking has nothing to review.'
        )
        return redirect('bookings:my_bookings')

    # Which review types already exist for this booking?
    existing_types = set(
        Review.objects.filter(booking=booking).values_list('review_type', flat=True)
    )
    guide_already_reviewed = 'guide' in existing_types
    experience_already_reviewed = 'experience' in existing_types

    # If everything reviewable is already done → kick back
    guide_done = guide_already_reviewed or not has_guide
    experience_done = experience_already_reviewed or not has_experience
    if guide_done and experience_done:
        messages.info(request, 'You have already reviewed this booking.')
        return redirect('reviews:my_reviews')

    if request.method == 'POST':
        guide_data = _read_review_section(request, 'guide') if has_guide else None
        experience_data = _read_review_section(request, 'experience') if has_experience else None

        # Skip sections that shouldn't be submitted
        if not has_guide or guide_already_reviewed:
            if guide_data:
                guide_data['attempted'] = False
        if not has_experience or experience_already_reviewed:
            if experience_data:
                experience_data['attempted'] = False

        # ---- Validate ----
        errors = []

        # At least one section must be attempted
        any_attempted = (
            (guide_data and guide_data['attempted']) or
            (experience_data and experience_data['attempted'])
        )
        if not any_attempted:
            errors.append('Please write at least one review — for your guide, the experience, or both.')

        # Each attempted section must be valid
        if guide_data and guide_data['attempted']:
            if not guide_data['rating']:
                errors.append('Guide review: please select a rating from 1 to 5.')
            if not guide_data['comment']:
                errors.append('Guide review: please write a comment.')

        if experience_data and experience_data['attempted']:
            if not experience_data['rating']:
                errors.append('Experience review: please select a rating from 1 to 5.')
            if not experience_data['comment']:
                errors.append('Experience review: please write a comment.')

        if errors:
            extra = {
                'booking': booking,
                'errors': errors,
                'has_guide': has_guide,
                'has_experience': has_experience,
                'guide_already_reviewed': guide_already_reviewed,
                'experience_already_reviewed': experience_already_reviewed,
                'guide_data': guide_data or {},
                'experience_data': experience_data or {},
            }
            context = get_tourist_page_context(
                tourist, request.user, active_page='bookings', extra=extra
            )
            return render(request, 'reviews/create.html', context)

        # ---- Create reviews ----
        created_any = False

        if has_guide and guide_data and guide_data['attempted']:
            try:
                Review.objects.create(
                    visitor=tourist,
                    review_type='guide',
                    guide=booking.guide,
                    experience=None,
                    booking=booking,
                    rating=guide_data['rating'],
                    title=guide_data['title'],
                    comment=guide_data['comment'],
                    pros=guide_data['pros'],
                    cons=guide_data['cons'],
                    moderation_status='approved',   # auto-approve on submit
                )
                # Model's save() override recalculated the guide's stats.
                created_any = True
            except Exception as e:
                messages.error(request, f'Could not save your guide review: {e}')
                return redirect('reviews:create', booking_id=booking.id)

        if has_experience and experience_data and experience_data['attempted']:
            try:
                Review.objects.create(
                    visitor=tourist,
                    review_type='experience',
                    guide=None,
                    experience=booking.experience,
                    booking=booking,
                    rating=experience_data['rating'],
                    title=experience_data['title'],
                    comment=experience_data['comment'],
                    pros=experience_data['pros'],
                    cons=experience_data['cons'],
                    moderation_status='approved',   # auto-approve on submit
                )
                # Model's save() override recalculated the experience's stats.
                created_any = True
            except Exception as e:
                messages.error(request, f'Could not save your experience review: {e}')
                return redirect('reviews:create', booking_id=booking.id)

        if created_any:
            messages.success(
                request,
                'Thank you — your review has been submitted.'
            )
        return redirect('reviews:my_reviews')

    # ---- GET: show form ----
    extra = {
        'booking': booking,
        'has_guide': has_guide,
        'has_experience': has_experience,
        'guide_already_reviewed': guide_already_reviewed,
        'experience_already_reviewed': experience_already_reviewed,
        'guide_data': {},
        'experience_data': {},
    }
    context = get_tourist_page_context(
        tourist, request.user, active_page='bookings', extra=extra
    )
    return render(request, 'reviews/create.html', context)


# ============================================================
# MY REVIEWS
# ============================================================

@login_required
def my_reviews(request):
    """
    All reviews written by the tourist.

    No status labels — the tourist just sees their own reviews.
    Both guide and experience reviews are returned together.
    """
    tourist = _get_tourist(request.user)
    if tourist is None:
        return redirect('/providers/dashboard/')

    reviews_qs = Review.objects.filter(
        visitor=tourist
    ).select_related(
        'guide', 'guide__profile__user',
        'experience', 'booking'
    ).order_by('-created_at')

    avg_rating = reviews_qs.aggregate(avg=Avg('rating'))['avg'] or 0

    extra = {
        'reviews': reviews_qs,
        'avg_rating': avg_rating,
    }
    context = get_tourist_page_context(
        tourist, request.user, active_page='reviews', extra=extra
    )
    return render(request, 'reviews/my_reviews.html', context)


# ============================================================
# EXPERIENCE REVIEWS (public)
# ============================================================

@login_required
def experience_reviews(request, experience_id):
    """
    Public list of approved EXPERIENCE reviews for an experience.
    Only reviews with review_type='experience' and
    moderation_status='approved' are shown.
    """
    tourist = _get_tourist(request.user)
    if tourist is None:
        return redirect('/providers/dashboard/')

    experience = get_object_or_404(Experience, id=experience_id)

    reviews = Review.objects.filter(
        experience=experience,
        review_type='experience',
        moderation_status='approved'
    ).select_related(
        'visitor', 'visitor__profile'
    ).order_by('-created_at')

    avg_rating = reviews.aggregate(Avg('rating'))['rating__avg'] or 0

    extra = {
        'experience': experience,
        'reviews': reviews,
        'avg_rating': avg_rating,
        'total_reviews': reviews.count(),
        'rating_counts': {
            5: reviews.filter(rating=5).count(),
            4: reviews.filter(rating=4).count(),
            3: reviews.filter(rating=3).count(),
            2: reviews.filter(rating=2).count(),
            1: reviews.filter(rating=1).count(),
        },
    }
    context = get_tourist_page_context(
        tourist, request.user, active_page='experiences', extra=extra
    )
    return render(request, 'reviews/experience_reviews.html', context)