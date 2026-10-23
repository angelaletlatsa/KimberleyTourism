from django.contrib.auth.models import User
from .models import Notification


ROLE_NOTIFICATIONS = {
    'tourist': [
        'booking_created', 'booking_confirmed', 'booking_cancelled', 'booking_reminder',
        'booking_no_show', 'review_reminder', 'review_approved', 'review_rejected',
        'tour_completed', 'welcome', 'account_suspended', 'account_restored',
        'booking_security_alert',
    ],
    'guide': [
        'booking_created', 'booking_confirmed', 'booking_cancelled', 'booking_reminder',
        'booking_no_show', 'review_received', 'review_removed', 'tour_completed',
        'guide_approved', 'guide_rejected', 'guide_suspended', 'account_suspended',
        'account_restored', 'welcome',
    ],
    'provider': [
        'booking_created', 'booking_cancelled', 'booking_no_show',
        'experience_created', 'experience_submitted', 'experience_updated',
        'experience_deleted', 'experience_approved', 'experience_rejected',
        'experience_suspended', 'experience_published', 'review_received',
        'provider_profile_submitted', 'provider_profile_updated',
        'provider_profile_deleted', 'provider_approved', 'provider_rejected',
        'provider_suspended', 'provider_restored', 'account_suspended',
        'account_restored', 'welcome',
    ],
    'admin': [
        'provider_verification', 'provider_profile_deleted', 'guide_verification',
        'experience_created', 'experience_submitted', 'experience_updated',
        'review_reported', 'security_alert', 'welcome',
    ],
}


def get_unread_count_for_user(user):
    """Return the unread notification count visible to the user's role."""
    if not user.is_authenticated:
        return 0

    try:
        user_role = user.profile.role
    except Exception:
        return 0

    allowed_types = ROLE_NOTIFICATIONS.get(user_role, [])
    notifications = Notification.objects.filter(recipient=user, is_read=False)
    if allowed_types:
        notifications = notifications.filter(notification_type__in=allowed_types)

    return notifications.count()


def create_notification(recipient, notification_type, title, message, link="", entity_type="", entity_id=None):
    """Helper function to create notifications from anywhere in the system"""
    return Notification.create_notification(
        recipient=recipient,
        notification_type=notification_type,
        title=title,
        message=message,
        link=link,
        entity_type=entity_type,
        entity_id=entity_id
    )


def notify_booking_created(booking):
    """Send notification when booking is created"""
    # Notify visitor
    create_notification(
        recipient=booking.visitor.user,
        notification_type='booking_created',
        title=f"Booking Created: {booking.experience.name}",
        message=f"Your booking for {booking.experience.name} on {booking.booking_date.strftime('%d %b %Y')} has been created. Awaiting confirmation.",
        link=f"/bookings/my/",
        entity_type='Booking',
        entity_id=booking.id
    )
    
    # Notify provider
    create_notification(
        recipient=booking.experience.provider.user,
        notification_type='booking_created',
        title=f"New Booking: {booking.experience.name}",
        message=f"{booking.visitor.user.first_name} booked {booking.experience.name} for {booking.participants} people on {booking.booking_date.strftime('%d %b %Y')}.",
        link=f"/bookings/",
        entity_type='Booking',
        entity_id=booking.id
    )


def notify_booking_confirmed(booking):
    """Send notification when booking is confirmed"""
    create_notification(
        recipient=booking.visitor.user,
        notification_type='booking_confirmed',
        title=f"Booking Confirmed: {booking.experience.name}",
        message=f"Your booking for {booking.experience.name} on {booking.booking_date.strftime('%d %b %Y')} has been confirmed!",
        link=f"/bookings/my/",
        entity_type='Booking',
        entity_id=booking.id
    )


def notify_booking_cancelled(booking):
    """Send notification when booking is cancelled"""
    create_notification(
        recipient=booking.visitor.user,
        notification_type='booking_cancelled',
        title=f"Booking Cancelled: {booking.experience.name}",
        message=f"Your booking for {booking.experience.name} on {booking.booking_date.strftime('%d %b %Y')} has been cancelled.",
        link=f"/bookings/my/",
        entity_type='Booking',
        entity_id=booking.id
    )
    
    # Notify provider
    create_notification(
        recipient=booking.experience.provider.user,
        notification_type='booking_cancelled',
        title=f"Booking Cancelled: {booking.experience.name}",
        message=f"{booking.visitor.user.first_name} cancelled their booking for {booking.experience.name}.",
        link=f"/bookings/",
        entity_type='Booking',
        entity_id=booking.id
    )


def notify_experience_published(experience):
    """Send notification when experience is published"""
    create_notification(
        recipient=experience.provider.user,
        notification_type='experience_published',
        title=f"Experience Published: {experience.name}",
        message=f"Your experience '{experience.name}' has been published and is now available for booking.",
        link=f"/experiences/{experience.id}/",
        entity_type='Experience',
        entity_id=experience.id
    )


def notify_experience_rejected(experience, reason):
    """Send notification when experience is rejected"""
    create_notification(
        recipient=experience.provider.user,
        notification_type='experience_rejected',
        title=f"Experience Rejected: {experience.name}",
        message=f"Your experience '{experience.name}' was rejected. Reason: {reason}",
        link=f"/experiences/my/",
        entity_type='Experience',
        entity_id=experience.id
    )


def notify_review_reminder(booking):
    """Send reminder to review completed booking"""
    create_notification(
        recipient=booking.visitor.user,
        notification_type='review_reminder',
        title=f"Review Reminder: {booking.experience.name}",
        message=f"Don't forget to review your experience at {booking.experience.name}!",
        link=f"/reviews/create/{booking.id}/",
        entity_type='Booking',
        entity_id=booking.id
    )


def notify_welcome(user):
    """Send welcome notification"""
    create_notification(
        recipient=user,
        notification_type='welcome',
        title=f"Welcome to Explore Kimberley, {user.first_name}!",
        message="Start exploring amazing experiences in Kimberley. We're excited to have you!",
        link="/experiences/",
        entity_type='User',
        entity_id=user.id
    )
