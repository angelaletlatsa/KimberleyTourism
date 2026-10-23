from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.urls import reverse

from .models import Itinerary, ItineraryItem, Budget
from experiences.models import Experience
from bookings.models import Booking
from reviews.models import Review
from notifications.utils import get_unread_count_for_user


# ============================================================
# ITINERARY — VIEW
# ============================================================

@login_required
def view_itinerary(request):
    """View the user's active itinerary"""

    if request.user.profile.role != 'tourist':
        return redirect('/providers/dashboard/')

    tourist_profile = request.user.profile.tourist_profile

    saved = request.GET.get('saved', '0') == '1'

    try:
        itinerary = Itinerary.objects.get(
            visitor=tourist_profile,
            is_active=True
        )
        items = ItineraryItem.objects.filter(
            itinerary=itinerary
        ).select_related('experience', 'experience__category').order_by('date', 'time')

        # ===== COST (range-based, honest) =====
        cost_low, cost_high = itinerary.total_cost_range()
        cost_display = itinerary.cost_range_display

        # Legacy templates expect `total_cost` — keep a compatible value
        total_cost = cost_low

        total_duration = itinerary.total_duration() // 60

        budget, _ = Budget.objects.get_or_create(visitor=tourist_profile)
        budget_total = float(budget.total_budget or 0)

        # Over-budget only makes sense if we have a "high" estimate.
        # If the range is open-ended (high is None), we can't say definitively.
        if budget_total and cost_high is not None and cost_high > budget_total:
            over_budget = cost_high - budget_total
        elif budget_total and cost_high is None and cost_low > budget_total:
            over_budget = cost_low - budget_total
        else:
            over_budget = 0

    except Itinerary.DoesNotExist:
        itinerary = None
        items = []
        total_cost = 0
        cost_low = 0
        cost_high = 0
        cost_display = 'No estimated cost'
        total_duration = 0
        budget_total = 0
        over_budget = 0

    # Sidebar counts
    upcoming_count = Booking.objects.filter(
        visitor=tourist_profile,
        status__in=['pending', 'confirmed'],
        booking_date__gte=timezone.now()
    ).count()

    review_count = Review.objects.filter(visitor=tourist_profile).count()

    itinerary_count = ItineraryItem.objects.filter(
        itinerary__visitor=tourist_profile,
        itinerary__is_active=True
    ).count()

    context = {
        'user': request.user,
        'profile': request.user.profile,
        'tourist_profile': tourist_profile,
        'now': timezone.now(),
        'active_page': 'itinerary',

        # Itinerary
        'itinerary': itinerary,
        'items': items,

        # Cost
        'total_cost': total_cost,        # legacy compat
        'cost_low': cost_low,
        'cost_high': cost_high,
        'cost_display': cost_display,
        'total_duration': total_duration,

        # Budget
        'budget_total': budget_total,
        'over_budget': over_budget,

        'saved': saved,

        # Sidebar / header
        'unread_count': get_unread_count_for_user(request.user),
        'upcoming_count': upcoming_count,
        'review_count': review_count,
        'itinerary_count': itinerary_count,
    }

    return render(request, 'itineraries/view.html', context)


# ============================================================
# ITINERARY — ADD / REMOVE / DELETE
# ============================================================

@login_required
def add_item(request, experience_id):
    """Add an experience to the itinerary"""

    if request.user.profile.role != 'tourist':
        return redirect('/providers/dashboard/')

    tourist_profile = request.user.profile.tourist_profile
    experience = get_object_or_404(Experience, id=experience_id, status='published')

    itinerary, created = Itinerary.objects.get_or_create(
        visitor=tourist_profile,
        is_active=True,
        defaults={
            'name': 'My Kimberley Adventure',
            'start_date': timezone.now().date(),
            'end_date': timezone.now().date() + timezone.timedelta(days=3),
            'number_of_travellers': 1,
        }
    )

    existing = ItineraryItem.objects.filter(
        itinerary=itinerary,
        experience=experience
    ).exists()

    if not existing:
        ItineraryItem.objects.create(
            itinerary=itinerary,
            experience=experience,
            date=itinerary.start_date,
            time=timezone.now().time().replace(hour=10, minute=0)
        )

    return redirect(reverse('tourist:plan_my_trip') + '?step=2')


@login_required
def remove_item(request, item_id):
    """Remove an item from the itinerary"""

    if request.user.profile.role != 'tourist':
        return redirect('/providers/dashboard/')

    item = get_object_or_404(
        ItineraryItem,
        id=item_id,
        itinerary__visitor=request.user.profile.tourist_profile
    )

    item.delete()

    return redirect(reverse('tourist:plan_my_trip') + '?step=2&toast=Removed from your plan')


@login_required
def delete_itinerary(request, itinerary_id):
    """Delete an entire itinerary"""

    if request.user.profile.role != 'tourist':
        return redirect('/providers/dashboard/')

    itinerary = get_object_or_404(
        Itinerary,
        id=itinerary_id,
        visitor=request.user.profile.tourist_profile
    )

    itinerary.delete()

    return redirect('tourist:dashboard')