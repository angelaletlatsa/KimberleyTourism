from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Avg, Count
from django.core.paginator import Paginator
from django.utils import timezone
from django.http import JsonResponse
from django.contrib import messages
from .models import Category, Experience, Availability
from bookings.models import Booking
from notifications.models import Notification
from django.contrib.auth.models import User


def experience_list(request):
    """Public page to browse all published experiences with user-friendly filters"""
    experiences = Experience.objects.filter(
        status='published',
        is_available=True
    ).select_related('category', 'provider')

    # ===== SEARCH (name + description + location) =====
    q = request.GET.get('q', '').strip()
    if q:
        experiences = experiences.filter(
            Q(name__icontains=q) |
            Q(description__icontains=q) |
            Q(location__icontains=q)
        )

    # ===== CATEGORY FILTER =====
    category_id = request.GET.get('category', '')
    if category_id:
        experiences = experiences.filter(category_id=category_id)

    # ===== LOCATION FILTER =====
    location = request.GET.get('location', '')
    if location:
        experiences = experiences.filter(location__icontains=location)

    # ===== DISTANCE FILTER =====
    distance = request.GET.get('distance', '')
    if distance:
        experiences = experiences.filter(location__icontains='Kimberley')

    # ===== RATING FILTER =====
    rating = request.GET.get('rating', '')
    if rating:
        experiences = experiences.filter(average_rating__gte=rating)

    # ===== OPENING HOURS FILTER =====
    opening_hours = request.GET.get('opening_hours', '')
    if opening_hours:
        pass

    # ===== SORTING =====
    sort = request.GET.get('sort', '-created_at')
    sort_options = {
        'name': 'name',
        '-name': '-name',
        'rating': '-average_rating',
        '-created_at': '-created_at',
        'created_at': 'created_at',
    }
    sort_value = sort_options.get(sort, '-created_at')
    experiences = experiences.order_by(sort_value)

    # ===== PAGINATION =====
    paginator = Paginator(experiences, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # ===== CATEGORIES FOR FILTER DROPDOWN =====
    categories = Category.objects.filter(is_active=True)

    # ===== AVAILABLE LOCATIONS =====
    locations = Experience.objects.filter(
        status='published'
    ).values_list('location', flat=True).distinct()

    # ===== POPULAR EXPERIENCES =====
    popular_experiences = Experience.objects.filter(
        status='published',
        is_available=True
    ).order_by('-average_rating', '-total_reviews')[:6]

    # ===== CHECK IF FILTERS ARE APPLIED =====
    has_filters = any([q, category_id, location, distance, rating, opening_hours])

    # ===== CHECK IF COMING FROM PLAN MY TRIP =====
    is_planning = request.GET.get('planning', '0') == '1'

    # ===== GET SAVED EXPERIENCE IDS =====
    saved_ids = []
    if request.user.is_authenticated and hasattr(request.user, 'profile'):
        try:
            from tourist.models import SavedExperience
            tourist_profile = request.user.profile.tourist_profile
            saved_ids = SavedExperience.objects.filter(
                visitor=tourist_profile
            ).values_list('experience_id', flat=True)
        except Exception:
            pass

    for exp in page_obj:
        exp.is_saved = exp.id in saved_ids

    context = {
        'experiences': page_obj,
        'categories': categories,
        'locations': locations,
        'selected_category': category_id,
        'q': q,
        'location': location,
        'distance': distance,
        'rating': rating,
        'opening_hours': opening_hours,
        'sort': sort,
        'popular_experiences': popular_experiences,
        'has_filters': has_filters,
        'total_count': paginator.count,
        'now': timezone.now(),
        'is_planning': is_planning,
        'saved_count': len(saved_ids),
        'unread_count': Notification.objects.filter(
            recipient=request.user,
            is_read=False
        ).count() if request.user.is_authenticated else 0,
    }

    return render(request, 'experiences/list.html', context)


def experience_detail(request, experience_id):
    """
    View detailed information about a specific experience — category-aware.

    Reviews shown here are ONLY 'experience' reviews (not guide reviews).
    """
    experience = get_object_or_404(
        Experience.objects.select_related('category', 'provider', 'guide'),
        id=experience_id,
        status='published'
    )

    # ===== REVIEWS — experience reviews only =====
    from reviews.models import Review

    base_reviews = Review.objects.filter(
        experience=experience,
        review_type='experience',
        moderation_status='approved'
    ).select_related(
        'visitor', 'visitor__profile', 'visitor__profile__user'
    ).order_by('-created_at')

    reviews = base_reviews[:5]
    review_count = base_reviews.count()

    avg_rating = base_reviews.aggregate(avg=Avg('rating'))['avg'] or 0

    # Rating breakdown for the sidebar
    rating_breakdown = []
    for star in range(5, 0, -1):
        count = base_reviews.filter(rating=star).count()
        percentage = (count / review_count * 100) if review_count > 0 else 0
        rating_breakdown.append({
            'star': star,
            'count': count,
            'percentage': percentage,
        })

    # ===== DETERMINE CTA (Call To Action) =====
    listing_type = experience.listing_type
    cta_label = ''
    cta_url = ''
    cta_icon = ''

    if listing_type == 'activities':
        cta_label = 'Find a Tour Guide'
        cta_url = f'/tourist/guides/?activity={experience.id}'
        cta_icon = 'fa-user-tie'
    elif listing_type == 'food_dining':
        cta_label = 'Contact Restaurant'
        cta_url = ''
        cta_icon = 'fa-phone'
    elif listing_type == 'places_to_stay':
        cta_label = 'Contact Accommodation'
        cta_url = ''
        cta_icon = 'fa-phone'
    elif listing_type == 'attractions':
        cta_label = 'Get Directions'
        cta_url = f'https://maps.google.com/?q={experience.location}'
        cta_icon = 'fa-map-marker-alt'

    context = {
        'experience': experience,
        'reviews': reviews,
        'review_count': review_count,
        'avg_rating': avg_rating,
        'rating_breakdown': rating_breakdown,
        'listing_type': listing_type,
        'cta_label': cta_label,
        'cta_url': cta_url,
        'cta_icon': cta_icon,
        'now': timezone.now(),
        'unread_count': Notification.objects.filter(
            recipient=request.user,
            is_read=False
        ).count() if request.user.is_authenticated else 0,
    }

    return render(request, 'experiences/detail.html', context)


@login_required
def experience_create(request):
    """Provider creates a new experience"""
    if request.user.profile.role != 'provider':
        return redirect('tourist:dashboard')
    return redirect('provider:create_experience')


@login_required
def my_experiences(request):
    """Provider views their own experiences"""
    if request.user.profile.role != 'provider':
        return redirect('tourist:dashboard')
    return redirect('provider:my_experiences')


@login_required
def approve_experience(request, experience_id):
    """Admin approves or rejects an experience"""
    if request.user.profile.role != 'admin':
        return redirect('tourist:dashboard')
    return redirect('admin_dashboard:experiences')


@login_required
def experience_edit(request, pk):
    """Edit an experience — delegates to provider"""
    if request.user.profile.role != 'provider':
        return redirect('tourist:dashboard')
    return redirect('provider:edit_experience', experience_id=pk)


@login_required
def experience_delete(request, pk):
    """Delete an experience — delegates to provider"""
    if request.user.profile.role != 'provider':
        return redirect('tourist:dashboard')
    return redirect('provider:my_experiences')