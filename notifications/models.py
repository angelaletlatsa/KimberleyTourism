from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
class Notification(models.Model):
    TYPE_CHOICES = [
        ('booking_created', 'Booking Created'),
        ('booking_confirmed', 'Booking Confirmed'),
        ('booking_cancelled', 'Booking Cancelled'),
        ('booking_updated', 'Booking Updated'),
        ('booking_reminder', 'Booking Reminder'),
        ('experience_approved', 'Experience Approved'),
        ('experience_rejected', 'Experience Rejected'),
        ('guide_verified', 'Guide Verified'),
        ('provider_verified', 'Provider Verified'),
        ('provider_verification', 'Provider Verification Request'),
        ('provider_profile_submitted', 'Provider Profile Submitted'),
        ('provider_profile_updated', 'Provider Profile Updated'),
        ('provider_rejected', 'Provider Rejected'),
        ('provider_profile_deleted', 'Provider Profile Deleted'),
        ('provider_approved', 'Provider Approved'),
        ('account_suspended', 'Account Suspended'),
        ('account_restored', 'Account Restored'),
        ('provider_suspended', 'Provider Suspended'),
        ('provider_restored', 'Provider Restored'),
        ('experience_created', 'Experience Created'),
        ('experience_submitted', 'Experience Submitted'),
        ('experience_updated', 'Experience Updated'),
        ('experience_deleted', 'Experience Deleted'),
        ('experience_published', 'Experience Published'),
        ('review_reminder', 'Review Reminder'),
        ('system_alert', 'System Alert'),
        ('welcome', 'Welcome'),
        ('guide_verification', 'Guide Verification Request'),
        ('guide_approved', 'Guide Approved'),
        ('guide_rejected', 'Guide Rejected'),
        ('guide_suspended', 'Guide Suspended'),
        ('booking_rejected', 'Booking Rejected'),
        ('booking_no_show', 'Booking Marked as No-Show'),
        ('tour_completed', 'Tour Completed'),
        ('review_approved', 'Review Approved'),
        ('review_received', 'Review Received'),
        ('review_rejected', 'Review Rejected'),
        ('review_removed', 'Review Removed'),
        ('experience_suspended', 'Experience Suspended'),
        ('security_alert', 'Security Alert'),
        ('verification', 'Verification Update'),
        ('account', 'Account Update'),
        ('booking', 'Booking Update'),
        ('review', 'Review Update'),
    ]

    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    notification_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    title = models.CharField(max_length=200)
    message = models.TextField()
    link = models.URLField(blank=True, help_text="URL to related content")
    # Related entity (for reference)
    entity_type = models.CharField(max_length=50, blank=True)
    entity_id = models.IntegerField(null=True, blank=True)
    # Status
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    # Email
    email_sent = models.BooleanField(default=False)
    email_sent_at = models.DateTimeField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.recipient.username} - {self.title}"

    @classmethod
    def create_notification(cls, recipient, notification_type, title, message,
                            link="", entity_type="", entity_id=None):
        return cls.objects.create(
            recipient=recipient,
            notification_type=notification_type,
            title=title,
            message=message,
            link=link,
            entity_type=entity_type,
            entity_id=entity_id,
        )

    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save()

    def mark_as_unread(self):
        self.is_read = False
        self.read_at = None
        self.save()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'is_read']),
            models.Index(fields=['notification_type']),
            models.Index(fields=['created_at']),
        ]