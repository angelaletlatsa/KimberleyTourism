"""
Shared utility functions for the tourist app.

Every tourist page uses get_tourist_page_context() so the sidebar,
badges, and avatar stay consistent.
"""

from django.utils import timezone

from bookings.models import Booking
from itineraries.models import Itinerary, ItineraryItem
from reviews.models import Review
from notifications.utils import get_unread_count_for_user


def get_tourist_nav_context(tourist, user):
    """
    Values every tourist page needs for its sidebar.

    Returns a dict with:
        upcoming_count  - badge on "My Bookings"
        itinerary_count - badge on "Plan My Trip"
        review_count    - badge on "My Reviews"
        unread_count    - badge on notification bell
    """
    today = timezone.now().date()

    upcoming_count = Booking.objects.filter(
        visitor=tourist,
        status__in=['pending', 'confirmed'],
        booking_date__gte=today
    ).count()

    itinerary_count = ItineraryItem.objects.filter(
        itinerary__visitor=tourist,
        itinerary__is_active=True
    ).count()

    review_count = Review.objects.filter(visitor=tourist).count()

    return {
        'upcoming_count': upcoming_count,
        'itinerary_count': itinerary_count,
        'review_count': review_count,
        'unread_count': get_unread_count_for_user(user),
    }


def get_tourist_page_context(tourist, user, active_page='', extra=None):
    """
    Full context every tourist page needs.

    Args:
        tourist     : TouristProfile instance
        user        : request.user
        active_page : string used by sidebar to highlight current link
                      (dashboard, guides, experiences, plan_trip, saved,
                       bookings, reviews)
        extra       : dict of page-specific values to merge in
    """
    ctx = {
        'user': user,
        'profile': user.profile,
        'tourist_profile': tourist,
        'now': timezone.now(),
        'active_page': active_page,
    }
    ctx.update(get_tourist_nav_context(tourist, user))
    if extra:
        ctx.update(extra)
    return ctx