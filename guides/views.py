from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.core.exceptions import ValidationError
from django.db.models import Avg, Count, Q
from datetime import timedelta

from .models import GuideProfile, get_or_create_guide_profile
from .utils import get_guide_page_context, get_guide_nav_context
from bookings.models import Booking
from reviews.models import Review
from notifications.models import Notification
from notifications.utils import create_notification, get_unread_count_for_user


# ============================================================
# DASHBOARD
# ============================================================

@login_required
def dashboard(request):
    """Guide Dashboard - Operational Control Centre"""

    if request.user.profile.role != 'guide':
        return redirect('tourist:dashboard')

    guide = get_or_create_guide_profile(request.user.profile)

    bookings = Booking.objects.filter(guide=guide)
    today = timezone.now().date()

    # ===== STATS =====
    total_tours = bookings.count()
    pending_assignments = bookings.filter(
        status='pending', admin_approved=True
    ).count()
    upcoming_tours_count = bookings.filter(
        status='confirmed', booking_date__gte=today
    ).count()
    completed_tours = bookings.filter(status='completed').count()
    cancelled_tours = bookings.filter(status='cancelled').count()
    rejected_tours = bookings.filter(status='rejected').count()
    today_tours = bookings.filter(status='confirmed', booking_date=today).count()

    # ===== LISTS =====
    pending_list = bookings.filter(
        status='pending', admin_approved=True
    ).select_related('visitor', 'visitor__profile__user', 'experience').order_by('booking_date')[:5]

    today_list = bookings.filter(
        status='confirmed', booking_date=today
    ).select_related('visitor', 'visitor__profile__user', 'experience').order_by('booking_time')

    upcoming_list = bookings.filter(
        status='confirmed', booking_date__gt=today
    ).select_related('visitor', 'visitor__profile__user', 'experience').order_by('booking_date', 'booking_time')[:5]

    # ===== REVIEWS =====
    reviews = Review.objects.filter(
        review_type='guide',
        guide=guide,
    ).select_related('visitor', 'visitor__profile__user', 'experience').order_by('-created_at')

    avg_rating = reviews.aggregate(Avg('rating'))['rating__avg'] or 0
    total_reviews = reviews.count()

    # ===== NOTIFICATIONS =====
    recent_activity = Notification.objects.filter(
        recipient=request.user
    ).order_by('-created_at')[:5]

    # ===== WEEK CHART — next 7 days =====
    week_chart = []
    max_week_count = 1
    for i in range(7):
        d = today + timedelta(days=i)
        count = bookings.filter(
            status='confirmed',
            booking_date=d
        ).count()
        if count > max_week_count:
            max_week_count = count
        week_chart.append({
            'label': d.strftime('%a'),
            'count': count,
            'is_today': (i == 0),
        })

    # ===== THIS WEEK AT A GLANCE =====
    week_end = today + timedelta(days=6)
    this_week_tours = bookings.filter(
        status='confirmed',
        booking_date__gte=today,
        booking_date__lte=week_end,
    ).count()

    # ===== COMPLETION RATE (nice visual number) =====
    decided_tours = completed_tours + cancelled_tours + rejected_tours
    completion_rate = int((completed_tours / decided_tours) * 100) if decided_tours > 0 else 0

    # ===== UNREAD NOTIFICATIONS =====
    unread_count = get_unread_count_for_user(request.user)

    extra = {
        # stats
        'total_tours': total_tours,
        'pending_assignments': pending_assignments,
        'upcoming_tours': upcoming_tours_count,
        'completed_tours': completed_tours,
        'cancelled_tours': cancelled_tours,
        'rejected_tours': rejected_tours,
        'today_tours': today_tours,
        'this_week_tours': this_week_tours,
        'completion_rate': completion_rate,
        'avg_rating': avg_rating,
        'total_reviews': total_reviews,

        # lists
        'pending_list': pending_list,
        'today_list': today_list,
        'upcoming_list': upcoming_list,
        'recent_activity': recent_activity,
        'recent_reviews': reviews[:4],

        # chart
        'week_chart': week_chart,
        'max_week_count': max_week_count,

        # flags
        'is_suspended': guide.is_suspended,
        'has_schedule': guide.has_schedule,
        'verification_status_display': guide.verification_status_display,
    }

    context = get_guide_page_context(
        guide, request.user, active_page='dashboard', extra=extra
    )
    return render(request, 'guides/dashboard.html', context)


# ============================================================
# PROFILE (READ-ONLY)
# ============================================================

@login_required
def profile(request):
    if request.user.profile.role != 'guide':
        return redirect('tourist:dashboard')

    guide = get_or_create_guide_profile(request.user.profile)

    extra = {
        'verification_status_display': guide.verification_status_display,
    }
    context = get_guide_page_context(
        guide, request.user, active_page='profile', extra=extra
    )
    return render(request, 'guides/profile.html', context)


# ============================================================
# PROFILE (EDIT FORM)
# ============================================================

@login_required
def profile_edit(request):
    if request.user.profile.role != 'guide':
        return redirect('tourist:dashboard')

    guide = get_or_create_guide_profile(request.user.profile)

    if request.method == 'POST':
        guide.biography = request.POST.get('biography', '').strip()

        years_raw = request.POST.get('years_experience', '').strip()
        try:
            guide.years_experience = int(years_raw) if years_raw != '' else 0
        except (ValueError, TypeError):
            guide.years_experience = 0
        guide.years_experience_set = True

        guide.languages = _split_csv(request.POST.get('languages', ''))
        guide.specializations = _split_csv(request.POST.get('specializations', ''))
        guide.qualifications = _split_csv(request.POST.get('qualifications', ''))
        guide.areas_of_expertise = _split_csv(request.POST.get('areas_of_expertise', ''))

        uploaded = request.FILES.get('profile_picture')
        if uploaded:
            request.user.profile.profile_picture = uploaded
            request.user.profile.save()

        guide.save()

        messages.success(request, 'Profile updated successfully.')
        return redirect('guides:profile')

    extra = {
        'verification_status_display': guide.verification_status_display,
    }
    context = get_guide_page_context(
        guide, request.user, active_page='profile', extra=extra
    )
    return render(request, 'guides/profile_edit.html', context)


# ============================================================
# PROFILE (SUBMIT FOR VERIFICATION)
# ============================================================

@login_required
@require_POST
def profile_submit(request):
    if request.user.profile.role != 'guide':
        return redirect('tourist:dashboard')

    guide = get_or_create_guide_profile(request.user.profile)

    if guide.verification_status not in ('pending', 'rejected'):
        messages.warning(
            request,
            f'Your profile cannot be submitted right now. '
            f'Current status: {guide.verification_status_display}.'
        )
        return redirect('guides:profile')

    if guide.verification_status == 'rejected':
        guide.verification_status = 'pending'
        guide.verification_notes = ''
        guide.save()

    from django.contrib.auth.models import User
    admins = User.objects.filter(profile__role='admin')
    for admin in admins:
        Notification.objects.create(
            recipient=admin,
            notification_type='guide_verification',
            title='Guide Verification Request',
            message=f'Guide {guide.full_name} has submitted their profile for verification.',
            entity_type='GuideProfile',
            entity_id=guide.id,
        )

    messages.success(
        request,
        'Your profile has been submitted for verification. '
        'You will be notified once a decision is made.'
    )
    return redirect('guides:profile')


# ============================================================
# AVAILABILITY
# ============================================================

@login_required
def availability(request):
    if request.user.profile.role != 'guide':
        return redirect('tourist:dashboard')

    guide = get_or_create_guide_profile(request.user.profile)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_schedule':
            schedule = guide.availability_schedule or {}
            days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
            for day in days:
                schedule[day] = {
                    'available': request.POST.get(f'{day}_available') == 'on',
                    'start': request.POST.get(f'{day}_start', ''),
                    'end': request.POST.get(f'{day}_end', ''),
                }
            guide.availability_schedule = schedule
            guide.save()
            messages.success(request, 'Weekly schedule updated successfully.')

        elif action == 'block_date':
            date = request.POST.get('date')
            reason = request.POST.get('reason', '')
            if date:
                schedule = guide.availability_schedule or {}
                blocked_dates = schedule.get('blocked_dates', [])
                if not any(b.get('date') == date for b in blocked_dates):
                    blocked_dates.append({'date': date, 'reason': reason})
                    schedule['blocked_dates'] = blocked_dates
                    guide.availability_schedule = schedule
                    guide.save()
                    messages.success(request, f'Date {date} blocked successfully.')
                else:
                    messages.warning(request, f'Date {date} is already blocked.')

        elif action == 'unblock_date':
            date = request.POST.get('date')
            if date:
                schedule = guide.availability_schedule or {}
                blocked_dates = schedule.get('blocked_dates', [])
                schedule['blocked_dates'] = [
                    b for b in blocked_dates if b.get('date') != date
                ]
                guide.availability_schedule = schedule
                guide.save()
                messages.success(request, f'Date {date} unblocked successfully.')

        elif action == 'toggle_availability':
            guide.is_available = not guide.is_available
            guide.save()
            messages.success(
                request,
                f'Availability set to '
                f'{"Available" if guide.is_available else "Unavailable"}.'
            )

        return redirect('guides:availability')

    schedule = guide.availability_schedule or {}

    if not schedule or not any(
        isinstance(v, dict) and v.get('available')
        for k, v in schedule.items() if k != 'blocked_dates'
    ):
        schedule = {
            'monday':    {'available': True,  'start': '09:00', 'end': '17:00'},
            'tuesday':   {'available': True,  'start': '09:00', 'end': '17:00'},
            'wednesday': {'available': True,  'start': '09:00', 'end': '17:00'},
            'thursday':  {'available': True,  'start': '09:00', 'end': '17:00'},
            'friday':    {'available': True,  'start': '09:00', 'end': '17:00'},
            'saturday':  {'available': False, 'start': '',      'end': ''},
            'sunday':    {'available': False, 'start': '',      'end': ''},
        }
        if 'blocked_dates' in (guide.availability_schedule or {}):
            schedule['blocked_dates'] = guide.availability_schedule['blocked_dates']

    blocked_dates = schedule.get('blocked_dates', [])

    extra = {
        'schedule': schedule,
        'blocked_dates': blocked_dates,
        'has_schedule': guide.has_schedule,
    }
    context = get_guide_page_context(
        guide, request.user, active_page='availability', extra=extra
    )
    return render(request, 'guides/availability.html', context)


# ============================================================
# ASSIGNMENTS (PENDING BOOKINGS)
# ============================================================

@login_required
def assignments(request):
    if request.user.profile.role != 'guide':
        return redirect('tourist:dashboard')

    guide = get_or_create_guide_profile(request.user.profile)

    pending = Booking.objects.filter(
        guide=guide,
        status='pending',
        admin_approved=True,
    ).select_related(
        'visitor', 'visitor__profile', 'visitor__profile__user', 'experience'
    ).order_by('-created_at')

    extra = {
        'pending_bookings': pending,
        'has_schedule': guide.has_schedule,
    }
    context = get_guide_page_context(
        guide, request.user, active_page='assignments', extra=extra
    )
    return render(request, 'guides/assignments.html', context)


# ============================================================
# BOOKING ACTIONS (AJAX)
# ============================================================

@login_required
@require_POST
def accept_booking(request):
    if request.user.profile.role != 'guide':
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)

    guide = get_or_create_guide_profile(request.user.profile)
    booking_id = request.POST.get('booking_id')
    if not booking_id:
        return JsonResponse({'success': False, 'error': 'Booking ID required'}, status=400)

    booking = get_object_or_404(Booking, id=booking_id)

    if booking.guide != guide:
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)

    if not guide.is_verified:
        return JsonResponse({'success': False, 'error': 'Your profile is not verified.'}, status=403)

    if not guide.is_bookable:
        return JsonResponse({'success': False, 'error': 'You are not currently available for bookings.'}, status=403)

    try:
        booking.accept(guide=guide, confirmed_by=request.user)
        return JsonResponse({
            'success': True,
            'message': 'Booking confirmed',
            'booking_id': booking.id,
            'new_status': booking.status,
        })
    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
@require_POST
def decline_booking(request):
    if request.user.profile.role != 'guide':
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)

    guide = get_or_create_guide_profile(request.user.profile)
    booking_id = request.POST.get('booking_id')
    reason = request.POST.get('reason', '')

    if not booking_id:
        return JsonResponse({'success': False, 'error': 'Booking ID required'}, status=400)

    booking = get_object_or_404(Booking, id=booking_id)

    if booking.guide != guide:
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)

    try:
        booking.decline(reason=reason)
        return JsonResponse({
            'success': True,
            'message': 'Booking declined',
            'booking_id': booking.id,
            'new_status': booking.status,
        })
    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
@require_POST
def complete_tour(request):
    if request.user.profile.role != 'guide':
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)

    guide = get_or_create_guide_profile(request.user.profile)
    booking_id = request.POST.get('booking_id')
    if not booking_id:
        return JsonResponse({'success': False, 'error': 'Booking ID required'}, status=400)

    booking = get_object_or_404(Booking, id=booking_id)

    if booking.guide != guide:
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)

    try:
        booking.complete()
        return JsonResponse({
            'success': True,
            'message': 'Tour completed',
            'booking_id': booking.id,
            'new_status': booking.status,
        })
    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


# ============================================================
# MY TOURS
# ============================================================

@login_required
def my_tours(request):
    if request.user.profile.role != 'guide':
        return redirect('tourist:dashboard')

    guide = get_or_create_guide_profile(request.user.profile)

    status_filter = request.GET.get('status', 'all')
    bookings = Booking.objects.filter(guide=guide)

    if status_filter != 'all':
        bookings = bookings.filter(status=status_filter)

    bookings = bookings.select_related(
        'visitor', 'visitor__profile', 'visitor__profile__user', 'experience'
    ).order_by('-booking_date', '-booking_time')

    counts = {
        'all':       Booking.objects.filter(guide=guide).count(),
        'pending':   Booking.objects.filter(guide=guide, status='pending').count(),
        'confirmed': Booking.objects.filter(guide=guide, status='confirmed').count(),
        'completed': Booking.objects.filter(guide=guide, status='completed').count(),
        'cancelled': Booking.objects.filter(guide=guide, status='cancelled').count(),
        'rejected':  Booking.objects.filter(guide=guide, status='rejected').count(),
    }

    extra = {
        'bookings': bookings,
        'counts': counts,
        'current_status': status_filter,
    }
    context = get_guide_page_context(
        guide, request.user, active_page='my_tours', extra=extra
    )
    return render(request, 'guides/my_tours.html', context)


# ============================================================
# TOUR DETAIL
# ============================================================

@login_required
def tour_detail(request, booking_id):
    if request.user.profile.role != 'guide':
        return redirect('tourist:dashboard')

    guide = get_or_create_guide_profile(request.user.profile)
    booking = get_object_or_404(Booking, id=booking_id, guide=guide)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'mark_completed' and booking.status == 'confirmed':
            try:
                booking.complete()
                messages.success(request, 'Tour marked as completed.')
            except ValidationError as e:
                messages.error(request, str(e))
            return redirect('guides:tour_detail', booking_id=booking.id)

        elif action == 'accept' and booking.status == 'pending':
            try:
                booking.accept(guide=guide, confirmed_by=request.user)
                messages.success(request, 'Booking confirmed.')
            except ValidationError as e:
                messages.error(request, str(e))
            return redirect('guides:tour_detail', booking_id=booking.id)

        elif action == 'decline' and booking.status == 'pending':
            reason = request.POST.get('reason', '')
            try:
                booking.decline(reason=reason)
                messages.info(request, 'Booking declined.')
            except ValidationError as e:
                messages.error(request, str(e))
            return redirect('guides:tour_detail', booking_id=booking.id)

    can_complete = (
        booking.status == 'confirmed'
        and booking.booking_date
        and booking.booking_date <= timezone.now().date()
    )

    extra = {
        'booking': booking,
        'can_complete': can_complete,
    }
    context = get_guide_page_context(
        guide, request.user, active_page='my_tours', extra=extra
    )
    return render(request, 'guides/tour_detail.html', context)


# ============================================================
# SCHEDULE
# ============================================================

@login_required
def schedule(request):
    if request.user.profile.role != 'guide':
        return redirect('tourist:dashboard')

    guide = get_or_create_guide_profile(request.user.profile)

    date_str = request.GET.get('date')
    if date_str:
        from datetime import datetime
        try:
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            date = timezone.now().date()
    else:
        date = timezone.now().date()

    day_bookings = Booking.objects.filter(
        guide=guide,
        booking_date=date,
        status='confirmed'
    ).select_related(
        'visitor', 'visitor__profile__user', 'experience'
    ).order_by('booking_time')

    extra = {
        'date': date,
        'day_bookings': day_bookings,
    }
    context = get_guide_page_context(
        guide, request.user, active_page='schedule', extra=extra
    )
    return render(request, 'guides/schedule.html', context)


# ============================================================
# REVIEWS
# ============================================================

@login_required
def reviews(request):
    if request.user.profile.role != 'guide':
        return redirect('tourist:dashboard')

    guide = get_or_create_guide_profile(request.user.profile)

    reviews_qs = Review.objects.filter(
        review_type='guide',
        guide=guide,
        moderation_status__in=['approved', 'pending'],
    ).select_related(
        'visitor', 'visitor__profile__user',
        'booking'
    ).order_by('-created_at')

    total = reviews_qs.count()
    avg_rating = reviews_qs.aggregate(avg=Avg('rating'))['avg'] or 0

    rating_breakdown = []
    for star in range(5, 0, -1):
        count = reviews_qs.filter(rating=star).count()
        percentage = (count / total * 100) if total > 0 else 0
        rating_breakdown.append({
            'star': star,
            'count': count,
            'percentage': percentage,
        })

    extra = {
        'reviews': reviews_qs,
        'total': total,
        'avg_rating': avg_rating,
        'rating_breakdown': rating_breakdown,
    }
    context = get_guide_page_context(
        guide, request.user, active_page='reviews', extra=extra
    )
    return render(request, 'guides/reviews.html', context)


# ============================================================
# AJAX HELPERS
# ============================================================

@login_required
@require_POST
def toggle_availability(request):
    if request.user.profile.role != 'guide':
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    guide = get_or_create_guide_profile(request.user.profile)
    guide.is_available = not guide.is_available
    guide.save()

    return JsonResponse({
        'is_available': guide.is_available,
        'is_bookable': guide.is_bookable,
        'availability_status': guide.availability_status,
        'message': 'Available' if guide.is_available else 'Unavailable',
    })


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _split_csv(raw):
    if not raw:
        return []
    return [item.strip() for item in raw.split(',') if item.strip()]