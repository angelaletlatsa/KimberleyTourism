from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db import transaction

from .models import Booking
from tourist.utils import get_tourist_page_context
from django.views.decorators.http import require_POST


# ============================================================
# HELPERS
# ============================================================

def _get_tourist(user):
    """Return the TouristProfile for this user, or None."""
    profile = getattr(user, 'profile', None)
    if not profile or profile.role != 'tourist':
        return None
    return getattr(profile, 'tourist_profile', None)


# ============================================================
# BOOKING CONFIRMATION
# ============================================================

@login_required
def booking_confirmation(request, booking_id):
    """Show booking confirmation page after successful request"""
    tourist = _get_tourist(request.user)
    if tourist is None:
        return redirect('/providers/dashboard/')

    booking = get_object_or_404(
        Booking.objects.select_related(
            'guide', 'guide__profile__user', 'experience'
        ),
        id=booking_id,
        visitor=tourist
    )

    extra = {
        'booking': booking,
    }
    context = get_tourist_page_context(
        tourist, request.user, active_page='bookings', extra=extra
    )
    return render(request, 'bookings/booking_confirmation.html', context)


# ============================================================
# MY BOOKINGS (Current / Past)
# ============================================================

@login_required
def my_bookings(request):
    """
    Show the tourist's bookings in two groups:
        - Current: pending or confirmed with future date
        - Past:    completed / cancelled / rejected / no_show
                   OR confirmed with a date in the past
    """
    tourist = _get_tourist(request.user)
    if tourist is None:
        return redirect('/providers/dashboard/')

    today = timezone.now().date()

    bookings = Booking.objects.filter(
        visitor=tourist
    ).select_related(
        'guide', 'guide__profile__user', 'experience'
    ).order_by('-booking_date', '-booking_time')

    # ---- Current: still upcoming or awaiting action ----
    current = bookings.filter(
        status__in=['pending', 'confirmed'],
        booking_date__gte=today
    )

    # ---- Past: finished, rejected, or date already passed ----
    from django.db.models import Q
    past = bookings.filter(
        Q(status__in=['completed', 'cancelled', 'rejected', 'no_show'])
        | Q(status='confirmed', booking_date__lt=today)
    )

    extra = {
        'current_bookings': current,
        'past_bookings': past,
    }
    context = get_tourist_page_context(
        tourist, request.user, active_page='bookings', extra=extra
    )
    return render(request, 'bookings/my_bookings.html', context)


# ============================================================
# CANCEL BOOKING
# ============================================================

@login_required
def cancel_booking(request, booking_id):
    """Cancel a booking — only allowed 24h+ before the tour."""
    tourist = _get_tourist(request.user)
    if tourist is None:
        return redirect('/providers/dashboard/')

    booking = get_object_or_404(
        Booking, id=booking_id, visitor=tourist
    )

    if not booking.can_cancel:
        messages.error(
            request,
            'This booking can no longer be cancelled. '
            'Cancellations are only allowed up to 24 hours before the tour.'
        )
        return redirect('bookings:my_bookings')

    if request.method == 'POST':
        reason = request.POST.get('reason', 'Cancelled by tourist')

        with transaction.atomic():
            booking.cancel(user=request.user, reason=reason)

        messages.success(request, 'Your booking has been cancelled.')
        return redirect('bookings:my_bookings')

    extra = {
        'booking': booking,
    }
    context = get_tourist_page_context(
        tourist, request.user, active_page='bookings', extra=extra
    )
    return render(request, 'bookings/cancel_booking.html', context)


# ============================================================
# BOOKING DETAIL
# ============================================================

@login_required
def booking_detail(request, booking_id):
    """View a single booking's details"""
    tourist = _get_tourist(request.user)
    if tourist is None:
        return redirect('/providers/dashboard/')

    booking = get_object_or_404(
        Booking.objects.select_related(
            'guide', 'guide__profile__user',
            'experience', 'experience__category',
            'visitor'
        ),
        id=booking_id,
        visitor=tourist
    )

    extra = {
        'booking': booking,
    }
    context = get_tourist_page_context(
        tourist, request.user, active_page='bookings', extra=extra
    )
    return render(request, 'bookings/booking_detail.html', context)

# ============================================================
# MARK TOUR AS COMPLETE (by tourist)
# ============================================================

@login_required
@require_POST
def mark_tour_complete(request, booking_id):
    """
    FR-06.6: Tourist Marks Booking as Completed
    Traceability: UC-06.6 Tourist Closes Booking

    Allows the tourist to close their own confirmed booking once the
    tour date has arrived (or passed). This protects the loop when
    the guide forgets to mark complete — the tourist can still
    close it and leave a review.
    """
    from django.utils import timezone

    tourist = _get_tourist(request.user)
    if tourist is None:
        return redirect('/providers/dashboard/')

    booking = get_object_or_404(
        Booking.objects.select_related('guide', 'visitor'),
        id=booking_id,
        visitor=tourist,
    )

    # ---- Guards ----
    if booking.status != 'confirmed':
        messages.error(
            request,
            'Only confirmed bookings can be marked as completed.'
        )
        return redirect('bookings:detail', booking_id=booking.id)

    today = timezone.now().date()
    if booking.booking_date > today:
        messages.error(
            request,
            'You cannot mark this tour as completed before the tour date.'
        )
        return redirect('bookings:detail', booking_id=booking.id)

    # ---- Complete the booking ----
    try:
        booking.complete()
        messages.success(
            request,
            'Tour marked as completed. Thank you — you can now leave a review.'
        )
        return redirect('bookings:my_bookings')
    except Exception as e:
        messages.error(request, f'Could not complete this booking: {e}')

    return redirect('bookings:detail', booking_id=booking.id)
