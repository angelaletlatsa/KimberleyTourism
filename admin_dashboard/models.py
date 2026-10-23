from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


class AdminAction(models.Model):
    """Track all administrative actions for audit purposes"""
    ACTION_TYPES = [
        ('approve_provider', 'Approved Provider'),
        ('reject_provider', 'Rejected Provider'),
        ('suspend_provider', 'Suspended Provider'),
        ('approve_guide', 'Approved Guide'),
        ('reject_guide', 'Rejected Guide'),
        ('suspend_guide', 'Suspended Guide'),
        ('approve_experience', 'Approved Experience'),
        ('reject_experience', 'Rejected Experience'),
        ('suspend_experience', 'Suspended Experience'),
        ('approve_review', 'Approved Review'),
        ('reject_review', 'Rejected Review'),
        ('suspend_user', 'Suspended User'),
        ('activate_user', 'Activated User'),
        ('deactivate_user', 'Deactivated User'),
        ('delete_user', 'Deleted User from Database'),
        ('delete_review', 'Deleted Review'),
        ('other', 'Other Action'),
    ]

    admin = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='admin_actions')
    action_type = models.CharField(max_length=50, choices=ACTION_TYPES)
    entity_type = models.CharField(max_length=50)
    entity_id = models.PositiveIntegerField()
    entity_name = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['action_type']),
            models.Index(fields=['admin', '-created_at']),
            models.Index(fields=['entity_type', 'entity_id']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"{self.admin} - {self.get_action_type_display()} - {self.entity_name}"

    @property
    def time_ago(self):
        return timezone.now() - self.created_at


class SystemSetting(models.Model):
    """Platform-wide configuration"""
    key = models.CharField(max_length=100, unique=True)
    value = models.TextField(blank=True)
    description = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['key']

    def __str__(self):
        return f"{self.key} = {self.value[:50]}"


class ReportedContent(models.Model):
    """Track reported reviews and content"""
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('resolved', 'Resolved'),
        ('dismissed', 'Dismissed'),
    ]

    reporter = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reports_made')
    review = models.ForeignKey('reviews.Review', on_delete=models.CASCADE, related_name='reported_content_entries')
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reports_resolved')
    resolved_at = models.DateTimeField(null=True, blank=True)
    admin_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Report on {self.review} - {self.status}"