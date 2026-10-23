"""
Shared utility functions for the guides app.

Every guide page uses get_guide_page_context() so the sidebar,
badges, avatar, and availability indicator stay consistent.
"""

from django.utils import timezone

from bookings.models import Booking
from notifications.utils import get_unread_count_for_user


def get_guide_nav_context(guide, user):
    """
    Values every guide page needs for its sidebar.

    Used by sidebar markup inside each template:
        - pending_assignments  → badge on "Assignments"
        - upcoming_tours       → badge on "My Tours"
        - total_reviews        → badge on "Reviews"
        - unread_count         → badge on notification bell
        - is_available         → "Off" badge next to Availability
        - verification_status  → "!" badge next to Profile
    """
    today = timezone.now().date()
    bookings = Booking.objects.filter(guide=guide)

    return {
        'pending_assignments': bookings.filter(
            status='pending', admin_approved=True
        ).count(),
        'upcoming_tours': bookings.filter(
            status='confirmed', booking_date__gte=today
        ).count(),
        'total_reviews': guide.approved_reviews.count(),
        'unread_count': get_unread_count_for_user(user),

        # Sidebar indicators
        'is_available': guide.is_available,
        'is_bookable': guide.is_bookable,
        'availability_status': guide.availability_status,
        'is_verified': guide.is_verified,
        'verification_status': guide.verification_status,
    }


def get_guide_page_context(guide, user, active_page='', extra=None):
    """
    Full context every guide page needs.

    Args:
        guide       : GuideProfile instance
        user        : request.user
        active_page : string used by sidebar to highlight the current link
                      (dashboard, profile, availability, assignments,
                       my_tours, schedule, reviews)
        extra       : dict of page-specific values to merge in
    """
    ctx = {
        'user': user,
        'profile': user.profile,
        'guide': guide,
        'now': timezone.now(),
        'active_page': active_page,
    }
    ctx.update(get_guide_nav_context(guide, user))
    if extra:
        ctx.update(extra)
    return ctx