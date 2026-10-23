from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Avg, Q
from django.urls import reverse
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from experiences.models import Experience, Category
from bookings.models import Booking, MAX_BOOKING_PARTICIPANTS
from itineraries.models import Itinerary, ItineraryItem, Budget
from reviews.models import Review
from notifications.models import Notification
from tourist.models import TouristProfile, SavedExperience
from guides.models import GuideProfile

from django.db import transaction
from notifications.utils import create_notification, get_unread_count_for_user

from .utils import get_tourist_page_context


# ============================================================
# HELPERS
# ============================================================

def _get_or_create_tourist(user):
    """Return the TouristProfile for this user, creating if missing."""
    profile = getattr(user, 'profile', None)
    if not profile or profile.role != 'tourist':
        return None
    tourist = getattr(profile, 'tourist_profile', None)
    if tourist is None:
        tourist = TouristProfile.objects.create(profile=profile)
    return tourist


def _availability_badge(guide, today):
    """
    Compute the availability badge for a guide card.
    Returns dict: {'code': str, 'label': str, 'next_date': date|None}
    """
    from datetime import timedelta

    if not guide.is_verified:
        return {'code': 'pending', 'label': 'Pending verification', 'next_date': None}

    if guide.is_suspended or not guide.is_active:
        return {'code': 'suspended', 'label': 'Not available', 'next_date': None}

    if not guide.has_schedule:
        return {'code': 'no_schedule', 'label': 'No schedule set', 'next_date': None}

    # Walk the next 14 days to find the first free working day
    day_names = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    schedule = guide.availability_schedule or {}
    confirmed_dates = set(
        guide.bookings.filter(
            status='confirmed',
            booking_date__gte=today,
            booking_date__lte=today + timedelta(days=14)
        ).values_list('booking_date', flat=True)
    )

    next_available = None
    for offset in range(0, 14):
        check_date = today + timedelta(days=offset)
        day_key = day_names[check_date.weekday()]
        day_config = schedule.get(day_key, {})
        if not day_config.get('available'):
            continue
        if check_date in confirmed_dates:
            continue
        next_available = check_date
        break

    if next_available is None:
        return {'code': 'booked', 'label': 'Fully booked', 'next_date': None}

    if next_available == today:
        return {'code': 'available_now', 'label': 'Available today', 'next_date': today}

    return {
        'code': 'available_this_week',
        'label': f"Next: {next_available.strftime('%a %d %b')}",
        'next_date': next_available,
    }


def _build_day_options(itinerary):
    """
    Return a list of {value, label} for the day-picker dropdown.

    Example:
        [
            {'value': '2026-12-15', 'label': 'Day 1 · Mon 15 Dec'},
            {'value': '2026-12-16', 'label': 'Day 2 · Tue 16 Dec'},
            ...
        ]

    Empty list if itinerary has no dates.
    """
    if not itinerary or not itinerary.start_date or not itinerary.end_date:
        return []

    days = []
    current = itinerary.start_date
    day_num = 1

    # Safety cap at 30 days
    while current <= itinerary.end_date and day_num <= 30:
        days.append({
            'value': current.strftime('%Y-%m-%d'),
            'label': f'Day {day_num} · {current.strftime("%a %d %b")}',
        })
        current += timezone.timedelta(days=1)
        day_num += 1

    return days

# ============================================================
# DASHBOARD
# ============================================================

@login_required
def dashboard(request):
    """Tourist dashboard with real data"""

    tourist_profile = _get_or_create_tourist(request.user)
    if tourist_profile is None:
        return redirect('/providers/dashboard/')

    today = timezone.now().date()

    # Saved trip (active itinerary)
    try:
        saved_trip = Itinerary.objects.get(visitor=tourist_profile, is_active=True)
        saved_trip_items = ItineraryItem.objects.filter(
            itinerary=saved_trip
        ).select_related('experience')[:3]

        # Uses new range-based method
        saved_trip_cost_display = saved_trip.cost_range_display
        saved_trip_cost_low, saved_trip_cost_high = saved_trip.total_cost_range()

    except Itinerary.DoesNotExist:
        saved_trip = None
        saved_trip_items = []
        saved_trip_cost_display = 'No estimated cost'
        saved_trip_cost_low = 0
        saved_trip_cost_high = 0

    # Bookings
    all_bookings = Booking.objects.filter(
        visitor=tourist_profile
    ).select_related('experience', 'guide', 'guide__profile__user')

    upcoming_bookings = all_bookings.filter(
        status__in=['pending', 'confirmed'],
        booking_date__gte=today
    ).order_by('booking_date')

    # Itinerary (reuse saved_trip — no need to query twice)
    if saved_trip:
        current_itinerary = saved_trip
        itinerary_items = ItineraryItem.objects.filter(
            itinerary=saved_trip
        ).select_related('experience')[:5]
    else:
        current_itinerary = None
        itinerary_items = []

    # Reviews
    reviews = Review.objects.filter(
        visitor=tourist_profile
    ).select_related('guide', 'experience')

    # Notifications
    notifications = Notification.objects.filter(
        recipient=request.user
    ).order_by('-created_at')[:5]

    # Saved experiences count (for hero "Saved" stat)
    saved_count = SavedExperience.objects.filter(visitor=tourist_profile).count()

    # Categories
    categories = Category.objects.filter(is_active=True)
    category_counts = {}
    for cat in categories:
        count = Experience.objects.filter(
            category=cat, status='published', is_available=True
        ).count()
        category_counts[cat.name.lower()] = count

    # Top picks
    top_picks = Experience.objects.filter(
        status='published', is_available=True
    ).order_by('-average_rating', '-total_reviews')[:6]

    # Recommended
    booked_categories = all_bookings.values_list('experience__category', flat=True).distinct()
    if booked_categories:
        recommended = Experience.objects.filter(
            status='published', is_available=True,
            category__in=booked_categories
        ).exclude(bookings__visitor=tourist_profile).order_by('-average_rating')[:4]
    else:
        recommended = Experience.objects.filter(
            status='published', is_available=True
        ).order_by('-average_rating', '-total_reviews')[:4]

    extra = {
        'upcoming_bookings': upcoming_bookings,
        'total_booked': all_bookings.count(),
        'current_itinerary': current_itinerary,
        'itinerary_items': itinerary_items,
        'reviews': reviews,
        'notifications': notifications,
        'recommended': recommended,
        'category_counts': category_counts,
        'top_picks': top_picks,
        'saved_trip': saved_trip,
        'saved_trip_items': saved_trip_items,

        # Range-based cost display
        'saved_trip_cost_display': saved_trip_cost_display,
        'saved_trip_cost_low': saved_trip_cost_low,
        'saved_trip_cost_high': saved_trip_cost_high,

        # Hero "Saved" stat
        'saved_count': saved_count,
    }
    context = get_tourist_page_context(
        tourist_profile, request.user, active_page='dashboard', extra=extra
    )
    return render(request, 'tourist/tourist_dashboard.html', context)
# ============================================================
# PLAN MY TRIP
# ============================================================

@login_required
def plan_my_trip(request):
    """
    Plan My Trip — story-driven, validated, honest.

    Server-side validation for:
      - Trip name (3-100 chars, required)
      - Start date (required, cannot be in the past)
      - End date (required, cannot be before start, max 30 days)
      - Travellers (1-20)
      - Budget (numeric, 0 to 1,000,000)

    Actions:
      - update_trip
      - add_experience
      - remove_item
      - update_item_date   ← NEW
      - save_trip
      - update_budget
    """

    tourist_profile = _get_or_create_tourist(request.user)
    if tourist_profile is None:
        return redirect('/providers/dashboard/')

    # ---- Current step ----
    current_step = request.GET.get('step', '1')
    try:
        current_step = int(current_step)
    except (ValueError, TypeError):
        current_step = 1
    current_step = max(1, min(current_step, 4))

    # ---- Budget ----
    budget, _ = Budget.objects.get_or_create(visitor=tourist_profile)

    # ---- Itinerary ----
    try:
        itinerary = Itinerary.objects.get(visitor=tourist_profile, is_active=True)
        itinerary_items = ItineraryItem.objects.filter(
            itinerary=itinerary
        ).select_related('experience', 'experience__category').order_by('date', 'time')
    except Itinerary.DoesNotExist:
        itinerary = None
        itinerary_items = []

    # ---- Cost (range-based) ----
    if itinerary:
        cost_low, cost_high = itinerary.total_cost_range()
        cost_display = itinerary.cost_range_display
    else:
        cost_low, cost_high = 0, 0
        cost_display = 'No estimated cost'

    budget_total = float(budget.total_budget or 0)

    # ---- Budget status (real, honest) ----
    budget_status = 'no_budget'
    over_budget_amount = 0

    if budget_total > 0 and itinerary and itinerary.has_any_priced_item:
        if cost_high is None:
            # Open-ended range
            if cost_low > budget_total:
                budget_status = 'over_budget'
                over_budget_amount = cost_low - budget_total
            else:
                budget_status = 'tight'   # open-ended, can't be sure
        else:
            if cost_high <= budget_total:
                budget_status = 'fits_comfortably'
            elif cost_low <= budget_total:
                budget_status = 'tight'
            else:
                budget_status = 'over_budget'
                over_budget_amount = cost_low - budget_total

    budget_bar_width = 0
    if budget_total > 0 and cost_low > 0:
        # Base width off the LOW end so it reflects minimum spend
        cost_low_float = float(cost_low)
        budget_bar_width = min((cost_low_float / budget_total) * 100, 150)

    categories = Category.objects.filter(is_active=True)

    # ---- Day options for the picker ----
    day_options = _build_day_options(itinerary)

    # ============================================================
    # POST HANDLING
    # ============================================================
    if request.method == 'POST':
        action = request.POST.get('action')

        # ---------- STEP 1: UPDATE TRIP ----------
        if action == 'update_trip':
            trip_name = (request.POST.get('trip_name') or '').strip()
            start_str = request.POST.get('start_date', '').strip()
            end_str = request.POST.get('end_date', '').strip()
            total_budget_str = request.POST.get('total_budget', '').strip()
            travellers_str = request.POST.get('number_of_travellers', '1').strip()

            errors = []
            today = timezone.now().date()

            # Trip name
            if not trip_name:
                errors.append('Please give your trip a name.')
            elif len(trip_name) < 3:
                errors.append('Trip name must be at least 3 characters.')
            elif len(trip_name) > 100:
                errors.append('Trip name must be 100 characters or less.')

            # Dates
            from datetime import datetime
            start_date = None
            end_date = None

            if not start_str:
                errors.append('Please choose a start date.')
            else:
                try:
                    start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
                except ValueError:
                    errors.append('Invalid start date.')

            if not end_str:
                errors.append('Please choose an end date.')
            else:
                try:
                    end_date = datetime.strptime(end_str, '%Y-%m-%d').date()
                except ValueError:
                    errors.append('Invalid end date.')

            if start_date and start_date < today:
                errors.append('Start date cannot be in the past.')

            if start_date and end_date:
                if end_date < start_date:
                    errors.append('End date must be on or after the start date.')
                elif (end_date - start_date).days > 30:
                    errors.append('Trips cannot be longer than 30 days.')

            # Travellers
            travellers = 1
            if travellers_str:
                try:
                    travellers = int(travellers_str)
                    if travellers < 1:
                        errors.append('Number of travellers must be at least 1.')
                    elif travellers > 20:
                        errors.append('Trips cannot have more than 20 travellers.')
                except ValueError:
                    errors.append('Number of travellers must be a number.')
                    travellers = 1

            # Budget
            total_budget_value = 0
            if total_budget_str:
                try:
                    total_budget_value = float(total_budget_str)
                    if total_budget_value < 0:
                        errors.append('Budget cannot be negative.')
                    elif total_budget_value > 1_000_000:
                        errors.append('Budget cannot exceed R1,000,000.')
                except ValueError:
                    errors.append('Budget must be a number.')

            if errors:
                for e in errors:
                    messages.error(request, e)
                return redirect('/tourist/plan-my-trip/?step=1')

            # ---- Save ----
            if itinerary:
                itinerary.name = trip_name
                itinerary.start_date = start_date
                itinerary.end_date = end_date
                itinerary.number_of_travellers = travellers
                itinerary.save()
            else:
                itinerary = Itinerary.objects.create(
                    visitor=tourist_profile,
                    name=trip_name,
                    start_date=start_date,
                    end_date=end_date,
                    number_of_travellers=travellers,
                    is_active=True,
                )

            if total_budget_value:
                budget.total_budget = total_budget_value
                budget.save()

            messages.success(request, 'Trip details saved.')
            return redirect('/tourist/plan-my-trip/?step=2')

        # ---------- STEP 2: ADD EXPERIENCE ----------
        elif action == 'add_experience':
            experience_id = request.POST.get('experience_id')
            if experience_id:
                experience = get_object_or_404(Experience, id=experience_id, status='published')

                if itinerary is None:
                    messages.error(request, 'Please set your trip details first (Step 1).')
                    return redirect('/tourist/plan-my-trip/?step=1')

                existing = ItineraryItem.objects.filter(
                    itinerary=itinerary, experience=experience
                ).exists()
                if existing:
                    return redirect('/tourist/plan-my-trip/?step=2&toast=Already in your plan')

                ItineraryItem.objects.create(
                    itinerary=itinerary,
                    experience=experience,
                    date=itinerary.start_date,
                    time=timezone.now().time().replace(hour=10, minute=0),
                )
                return redirect('/tourist/plan-my-trip/?step=2&toast=Experience added to your plan')

        # ---------- STEP 2: REMOVE ITEM ----------
        elif action == 'remove_item':
            item_id = request.POST.get('item_id')
            if item_id:
                item = get_object_or_404(
                    ItineraryItem, id=item_id, itinerary__visitor=tourist_profile
                )
                item.delete()
                return redirect('/tourist/plan-my-trip/?step=2&toast=Removed from your plan')

        # ---------- STEP 2: UPDATE ITEM DATE (day picker) ----------
        elif action == 'update_item_date':
            item_id = request.POST.get('item_id')
            new_date_str = request.POST.get('date', '').strip()

            if not item_id or not new_date_str:
                messages.error(request, 'Missing item or date.')
                return redirect('/tourist/plan-my-trip/?step=2')

            item = get_object_or_404(
                ItineraryItem, id=item_id, itinerary__visitor=tourist_profile
            )

            from datetime import datetime
            try:
                new_date = datetime.strptime(new_date_str, '%Y-%m-%d').date()
            except ValueError:
                messages.error(request, 'Invalid date.')
                return redirect('/tourist/plan-my-trip/?step=2')

            if not itinerary or not itinerary.is_within_dates(new_date):
                messages.error(request, 'That date is not within your trip.')
                return redirect('/tourist/plan-my-trip/?step=2')

            item.date = new_date
            item.save()
            return redirect('/tourist/plan-my-trip/?step=2&toast=Day updated')

        # ---------- STEP 3: UPDATE BUDGET ----------
        elif action == 'update_budget':
            total_budget_str = request.POST.get('total_budget', '').strip()
            travellers_str = request.POST.get('number_of_travellers', '').strip()

            if total_budget_str:
                try:
                    value = float(total_budget_str)
                    if value < 0:
                        messages.error(request, 'Budget cannot be negative.')
                    elif value > 1_000_000:
                        messages.error(request, 'Budget cannot exceed R1,000,000.')
                    else:
                        budget.total_budget = value
                        budget.save()
                except ValueError:
                    messages.error(request, 'Budget must be a number.')

            if travellers_str and itinerary:
                try:
                    t = int(travellers_str)
                    if 1 <= t <= 20:
                        itinerary.number_of_travellers = t
                        itinerary.save()
                except ValueError:
                    pass

            return redirect('/tourist/plan-my-trip/?step=3')

        # ---------- STEP 4: SAVE TRIP ----------
        elif action == 'save_trip':
            if itinerary:
                itinerary.is_active = True
                itinerary.save()
                budget.planned_cost = cost_low
                budget.save()
                return redirect('/itineraries/?saved=1')

    saved = request.GET.get('saved', '0') == '1'
    toast_message = request.GET.get('toast', '')

    extra = {
        'budget': budget,
        'itinerary': itinerary,
        'itinerary_items': itinerary_items,

        # Cost range data
        'cost_low': cost_low,
        'cost_high': cost_high,
        'cost_display': cost_display,

        'budget_total': budget_total,
        'budget_status': budget_status,
        'over_budget_amount': over_budget_amount,
        'budget_bar_width': budget_bar_width,

        'categories': categories,
        'current_step': current_step,
        'day_options': day_options,

        'saved': saved,
        'toast_message': toast_message,
    }
    context = get_tourist_page_context(
        tourist_profile, request.user, active_page='plan_trip', extra=extra
    )
    return render(request, 'tourist/plan_my_trip.html', context)


# ============================================================
# ITINERARY (legacy helper endpoints)
# ============================================================

@login_required
def add_to_itinerary(request, experience_id):
    """Add an experience to the current itinerary"""
    tourist_profile = _get_or_create_tourist(request.user)
    if tourist_profile is None:
        return redirect('/providers/dashboard/')

    experience = get_object_or_404(Experience, id=experience_id, status='published')

    itinerary, _ = Itinerary.objects.get_or_create(
        visitor=tourist_profile,
        is_active=True,
        defaults={
            'name': 'My Kimberley Adventure',
            'start_date': timezone.now().date(),
            'end_date': timezone.now().date() + timezone.timedelta(days=3),
            'number_of_travellers': 1,
        }
    )

    if not ItineraryItem.objects.filter(itinerary=itinerary, experience=experience).exists():
        ItineraryItem.objects.create(
            itinerary=itinerary,
            experience=experience,
            date=itinerary.start_date,
            time=timezone.now().time().replace(hour=10, minute=0),
        )

    return redirect(reverse('tourist:plan_my_trip') + '?step=2')


@login_required
def remove_from_itinerary(request, item_id):
    """Remove an item from the itinerary"""
    tourist_profile = _get_or_create_tourist(request.user)
    if tourist_profile is None:
        return redirect('/providers/dashboard/')

    item = get_object_or_404(
        ItineraryItem, id=item_id, itinerary__visitor=tourist_profile
    )
    item.delete()
    return redirect(reverse('tourist:plan_my_trip') + '?step=2&toast=Removed from your plan')


# ============================================================
# SAVED EXPERIENCES
# ============================================================

@login_required
def saved_experiences(request):
    """View saved experiences"""
    tourist_profile = _get_or_create_tourist(request.user)
    if tourist_profile is None:
        return redirect('/providers/dashboard/')

    saved = SavedExperience.objects.filter(
        visitor=tourist_profile
    ).select_related('experience', 'experience__category').order_by('-saved_at')

    is_planning = request.GET.get('planning', '0') == '1'

    extra = {
        'saved_experiences': saved,
        'is_planning': is_planning,
    }
    context = get_tourist_page_context(
        tourist_profile, request.user, active_page='saved', extra=extra
    )
    return render(request, 'tourist/saved_experiences.html', context)


@login_required
@require_POST
def toggle_save_experience(request, experience_id):
    """Toggle save/unsave via AJAX"""
    tourist_profile = _get_or_create_tourist(request.user)
    if tourist_profile is None:
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    experience = get_object_or_404(Experience, id=experience_id, status='published')

    saved, created = SavedExperience.objects.get_or_create(
        visitor=tourist_profile, experience=experience
    )

    if not created:
        saved.delete()
        is_saved = False
        message = 'Removed from your saved list'
    else:
        is_saved = True
        message = 'Saved to your list'

    saved_count = SavedExperience.objects.filter(visitor=tourist_profile).count()

    return JsonResponse({
        'is_saved': is_saved,
        'message': message,
        'saved_count': saved_count
    })


@login_required
def save_experience(request, experience_id):
    """Save an experience"""
    tourist_profile = _get_or_create_tourist(request.user)
    if tourist_profile is None:
        return redirect('/providers/dashboard/')

    experience = get_object_or_404(Experience, id=experience_id, status='published')
    SavedExperience.objects.get_or_create(visitor=tourist_profile, experience=experience)
    return redirect('tourist:saved_experiences')


@login_required
def unsave_experience(request, experience_id):
    """Remove saved experience"""
    tourist_profile = _get_or_create_tourist(request.user)
    if tourist_profile is None:
        return redirect('/providers/dashboard/')

    SavedExperience.objects.filter(
        visitor=tourist_profile, experience_id=experience_id
    ).delete()
    return redirect('tourist:saved_experiences')


# ============================================================
# TOUR GUIDES
# ============================================================

@login_required
def tour_guides(request):
    """
    FR-05: Tourist Browses Tour Guides
    Traceability: UC-05 Browse Tour Guides
    """
    tourist_profile = _get_or_create_tourist(request.user)
    if tourist_profile is None:
        return redirect('/providers/dashboard/')

    from datetime import date, timedelta
    from django.db.models import Q

    today = timezone.now().date()

    base_qs = GuideProfile.objects.filter(
        verification_status='approved',
        is_active=True,
        is_suspended=False,
    ).select_related('profile', 'profile__user').prefetch_related('bookings')

    q = request.GET.get('q', '').strip()
    if q:
        base_qs = base_qs.filter(
            Q(profile__user__first_name__icontains=q)
            | Q(profile__user__last_name__icontains=q)
            | Q(profile__user__username__icontains=q)
        )

    filter_mode = request.GET.get('filter', 'all')

    guides = []
    for guide in base_qs.order_by('-average_rating', '-total_tours_given'):
        guide.availability_badge = _availability_badge(guide, today)

        if filter_mode == 'available':
            if not guide.is_available:
                continue
        elif filter_mode == 'this_week':
            if guide.availability_badge['code'] not in ('available_now', 'available_this_week'):
                continue

        guides.append(guide)

    extra = {
        'guides': guides,
        'filter_mode': filter_mode,
        'search_query': q,
        'total_count': len(guides),
    }
    context = get_tourist_page_context(
        tourist_profile, request.user, active_page='guides', extra=extra
    )
    return render(request, 'tourist/tour_guides.html', context)


# ============================================================
# GUIDE PROFILE
# ============================================================

@login_required
def guide_profile(request, guide_id):
    """
    FR-05.1: Tourist Views Guide Profile
    Traceability: UC-05.1 View Guide Profile
    """
    tourist_profile = _get_or_create_tourist(request.user)
    if tourist_profile is None:
        return redirect('/providers/dashboard/')

    guide = get_object_or_404(
        GuideProfile,
        id=guide_id,
        verification_status='approved',
        is_active=True,
        is_suspended=False,
    )

    experiences = Experience.objects.filter(
        guide=guide, status='published', is_available=True
    )[:5]

    day_names = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    today = timezone.now().date()
    schedule = guide.availability_schedule or {}

    weekly_schedule = []
    for day in day_names:
        config = schedule.get(day, {}) or {}
        weekly_schedule.append({
            'name': day.capitalize(),
            'short': day[:3].capitalize(),
            'available': bool(config.get('available')),
            'start': config.get('start', ''),
            'end': config.get('end', ''),
        })

    guide.availability_badge = _availability_badge(guide, today)

    extra = {
        'guide': guide,
        'experiences': experiences,
        'weekly_schedule': weekly_schedule,
    }
    context = get_tourist_page_context(
        tourist_profile, request.user, active_page='guides', extra=extra
    )
    return render(request, 'tourist/guide_profile.html', context)


# ============================================================
# EXPERIENCES GALLERY
# ============================================================

@login_required
def experiences_gallery(request):
    """Show experiences grouped by category"""
    tourist_profile = _get_or_create_tourist(request.user)
    if tourist_profile is None:
        return redirect('/providers/dashboard/')

    categories = Category.objects.filter(is_active=True)
    experiences_by_category = {}
    for category in categories:
        experiences = Experience.objects.filter(
            category=category, status='published', is_available=True
        ).order_by('-average_rating')
        experiences_by_category[category] = experiences

    extra = {
        'experiences_by_category': experiences_by_category,
        'categories': categories,
    }
    context = get_tourist_page_context(
        tourist_profile, request.user, active_page='experiences', extra=extra
    )
    return render(request, 'tourist/experiences_gallery.html', context)


# ============================================================
# BOOK A GUIDE
# ============================================================

@login_required
def book_guide_directly(request, guide_id):
    """
    FR-06: Tourist Books Guide Directly
    Traceability: UC-06 Book Tour Guide
    """
    tourist = _get_or_create_tourist(request.user)
    if tourist is None:
        return redirect('/providers/dashboard/')

    guide = get_object_or_404(
        GuideProfile,
        id=guide_id,
        verification_status='approved',
        is_active=True,
        is_suspended=False,
    )

    if not guide.is_available:
        messages.error(request, 'This guide is currently not available for bookings.')
        return redirect('tourist:guide_profile', guide_id=guide.id)

    if not guide.has_schedule:
        messages.error(request, 'This guide has not set their working hours yet.')
        return redirect('tourist:guide_profile', guide_id=guide.id)

    if request.method == 'POST':
        booking_date = request.POST.get('booking_date')
        booking_time = request.POST.get('booking_time')
        participants_value = request.POST.get('participants', '1')
        special_requests = request.POST.get('special_requests', '')

        dest_names = request.POST.getlist('destination_name[]')
        dest_notes = request.POST.getlist('destination_notes[]')

        if not booking_date or not booking_time:
            messages.error(request, 'Please select a date and time.')
            return redirect('tourist:book_guide_directly', guide_id=guide_id)

        try:
            participants = int(participants_value)
        except (TypeError, ValueError):
            messages.error(request, 'Enter a valid number of participants.')
            return redirect('tourist:book_guide_directly', guide_id=guide_id)

        if not 1 <= participants <= MAX_BOOKING_PARTICIPANTS:
            messages.error(
                request,
                f'Number of participants must be between 1 and {MAX_BOOKING_PARTICIPANTS}.',
            )
            return redirect('tourist:book_guide_directly', guide_id=guide_id)

        from datetime import datetime
        try:
            date_obj = datetime.strptime(booking_date, '%Y-%m-%d').date()
            time_obj = datetime.strptime(booking_time, '%H:%M').time()
        except ValueError:
            messages.error(request, 'Invalid date or time format.')
            return redirect('tourist:book_guide_directly', guide_id=guide_id)

        if date_obj < timezone.now().date():
            messages.error(request, 'You cannot book a date in the past.')
            return redirect('tourist:book_guide_directly', guide_id=guide_id)

        clean_destinations = []
        for idx, name in enumerate(dest_names):
            name = (name or '').strip()
            if not name:
                continue
            note = ''
            if idx < len(dest_notes):
                note = (dest_notes[idx] or '').strip()
            clean_destinations.append({'name': name, 'notes': note, 'order': len(clean_destinations)})

        if not clean_destinations:
            messages.error(request, 'Please add at least one destination for your tour.')
            return redirect('tourist:book_guide_directly', guide_id=guide_id)

        from bookings.models import BookingDestination

        with transaction.atomic():
            guide = GuideProfile.objects.select_for_update().get(pk=guide.pk)
            clash = guide.has_conflict(date_obj, time_obj)
            if clash['has_clash']:
                messages.error(request, clash['reason'])
                return redirect('tourist:book_guide_directly', guide_id=guide_id)

            booking = Booking.objects.create(
                visitor=tourist,
                guide=guide,
                booking_date=date_obj,
                booking_time=time_obj,
                number_of_participants=int(participants),
                special_requests=special_requests,
                status='pending',
                admin_approved=False,
            )

            for dest in clean_destinations:
                BookingDestination.objects.create(
                    booking=booking,
                    name=dest['name'],
                    notes=dest['notes'],
                    order=dest['order'],
                )

            create_notification(
                recipient=request.user,
                notification_type='booking_created',
                title='Booking Request Received',
                message=(
                    f'Your request for {guide.full_name} on '
                    f'{date_obj.strftime("%d %b %Y")} at '
                    f'{time_obj.strftime("%H:%M")} has been received. '
                    f'Our team will review it and confirm shortly.'
                ),
                link='/bookings/my/',
                entity_type='Booking',
                entity_id=booking.id,
            )

            from django.contrib.auth.models import User
            admins = User.objects.filter(profile__role='admin')
            for admin_user in admins:
                create_notification(
                    recipient=admin_user,
                    notification_type='guide_verification',
                    title='New Booking Awaiting Assignment',
                    message=(
                        f'{tourist.user.get_full_name() or tourist.user.username} '
                        f'requested {guide.full_name} for '
                        f'{date_obj.strftime("%d %b %Y")} at '
                        f'{time_obj.strftime("%H:%M")}. '
                        f'Please review and confirm the assignment.'
                    ),
                    link=f'/admin_dashboard/bookings/{booking.id}/',
                    entity_type='Booking',
                    entity_id=booking.id,
                )

        messages.success(request, 'Your booking request has been submitted.')
        return redirect('bookings:confirmation', booking_id=booking.id)

    extra = {
        'guide': guide,
        'tourist': tourist,
    }
    context = get_tourist_page_context(
        tourist, request.user, active_page='guides', extra=extra
    )
    return render(request, 'tourist/book_guide.html', context)