from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


class ProviderProfile(models.Model):
    """
    FR-13: Provider Profile Management
    Traceability: UC-13 Provider Registers Business
    
    Status Flow:
    PENDING → APPROVED → SUSPENDED
    PENDING → REJECTED
    """
    
    VERIFICATION_STATUS = (
        ('pending', 'Pending Verification'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('suspended', 'Suspended'),
    )
    
    # Link to Profile
    profile = models.OneToOneField(
        'accounts.Profile',
        on_delete=models.CASCADE,
        related_name='provider_profile'
    )
    
    # Business Information
    business_name = models.CharField(max_length=200)
    business_description = models.TextField(blank=True)
    business_category = models.CharField(max_length=100, blank=True)
    
    # Contact Details
    contact_phone = models.CharField(max_length=20, blank=True)
    contact_email = models.EmailField(blank=True)
    website = models.URLField(blank=True, null=True)
    social_links = models.JSONField(default=dict, blank=True)
    
    # Location
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, default='Kimberley')
    province = models.CharField(max_length=100, default='Northern Cape')
    country = models.CharField(max_length=100, default='South Africa')
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    
    # Business Hours
    business_hours = models.JSONField(default=dict, blank=True)
    
    # Logo & Branding
    logo = models.ImageField(upload_to='providers/logos/', blank=True, null=True)
    cover_image = models.ImageField(upload_to='providers/covers/', blank=True, null=True)
    
    # Verification
    verification_status = models.CharField(
        max_length=20,
        choices=VERIFICATION_STATUS,
        default='pending'
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_providers'
    )
    verification_notes = models.TextField(blank=True)
    
    # Documents
    business_license = models.FileField(upload_to='providers/documents/', blank=True, null=True)
    id_document = models.FileField(upload_to='providers/documents/', blank=True, null=True)
    
    # Account Status
    is_active = models.BooleanField(default=True)
    is_suspended = models.BooleanField(default=False)
    suspension_reason = models.TextField(blank=True)
    suspended_at = models.DateTimeField(null=True, blank=True)
    suspended_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='suspended_providers'
    )
    
    # Statistics
    total_experiences = models.PositiveIntegerField(default=0)
    total_bookings = models.PositiveIntegerField(default=0)
    total_reviews = models.PositiveIntegerField(default=0)
    average_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0.00)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['verification_status']),
            models.Index(fields=['business_name']),
            models.Index(fields=['is_active']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    verification_status__in=['pending', 'approved', 'rejected', 'suspended']
                ),
                name='provider_verification_valid',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(total_experiences__gte=0)
                    & models.Q(total_bookings__gte=0)
                    & models.Q(total_reviews__gte=0)
                    & models.Q(average_rating__gte=0)
                    & models.Q(average_rating__lte=5)
                ),
                name='provider_metrics_valid',
            ),
            models.CheckConstraint(
                condition=(models.Q(latitude__isnull=True) | models.Q(latitude__range=(-90, 90))),
                name='provider_latitude_valid',
            ),
            models.CheckConstraint(
                condition=(models.Q(longitude__isnull=True) | models.Q(longitude__range=(-180, 180))),
                name='provider_longitude_valid',
            ),
        ]
    
    def __str__(self):
        return f"{self.business_name} ({self.get_verification_status_display()})"
    
    @property
    def user(self):
        return self.profile.user
    
    @property
    def full_name(self):
        return self.business_name
    
    @property
    def is_verified(self):
        return self.verification_status == 'approved'
    
    @property
    def is_public(self):
        return self.is_verified and self.is_active and not self.is_suspended
    
    @property
    def experiences(self):
        from experiences.models import Experience
        return Experience.objects.filter(provider=self)
    
    @property
    def published_experiences(self):
        return self.experiences.filter(status='published')
    
    @property
    def pending_experiences(self):
        return self.experiences.filter(status__in=['draft', 'under_review'])
    
    @property
    def active_experiences(self):
        return self.experiences.filter(status='published', is_available=True)
    
    @property
    def bookings(self):
        from bookings.models import Booking
        return Booking.objects.filter(experience__provider=self)
    
    @property
    def confirmed_bookings(self):
        return self.bookings.filter(status='confirmed')
    
    @property
    def completed_bookings(self):
        return self.bookings.filter(status='completed')
    
    @property
    def reviews(self):
        from reviews.models import Review
        return Review.objects.filter(experience__provider=self)
    
    @property
    def approved_reviews(self):
        return self.reviews.filter(moderation_status='approved')
    
    @property
    def notification_count(self):
        from notifications.models import Notification
        return Notification.objects.filter(recipient=self.user, is_read=False).count()
    
    def update_stats(self):
        """Update provider statistics"""
        from django.db.models import Avg, Count
        from bookings.models import Booking
        
        # Experience counts
        self.total_experiences = self.experiences.count()
        
        # Booking counts
        self.total_bookings = self.bookings.count()
        
        # Review stats
        reviews = self.approved_reviews
        self.total_reviews = reviews.count()
        self.average_rating = reviews.aggregate(Avg('rating'))['rating__avg'] or 0
        
        self.save()
    
    def approve(self, verified_by=None, notes=""):
        """Approve provider profile"""
        self.verification_status = 'approved'
        self.verified_at = timezone.now()
        if verified_by:
            self.verified_by = verified_by
        if notes:
            self.verification_notes = notes
        self.save()
        
        from notifications.utils import create_notification
        create_notification(
            recipient=self.user,
            notification_type='provider_verified',
            title='Business Verified! 🎉',
            message=f'Your business "{self.business_name}" has been verified. You can now create experiences.',
            entity_type='ProviderProfile',
            entity_id=self.id
        )
    
    def reject(self, reason=""):
        """Reject provider profile"""
        self.verification_status = 'rejected'
        self.verification_notes = reason
        self.save()
        
        from notifications.utils import create_notification
        create_notification(
            recipient=self.user,
            notification_type='provider_rejected',
            title='Business Application Rejected',
            message=f'Your business "{self.business_name}" was rejected. Reason: {reason or "Please update your information and resubmit."}',
            entity_type='ProviderProfile',
            entity_id=self.id
        )
    
    def suspend(self, reason="", suspended_by=None):
        """Suspend provider"""
        self.is_suspended = True
        self.suspension_reason = reason
        self.suspended_at = timezone.now()
        if suspended_by:
            self.suspended_by = suspended_by
        self.save()
        
        from notifications.utils import create_notification
        create_notification(
            recipient=self.user,
            notification_type='account_suspended',
            title='Account Suspended',
            message=f'Your business "{self.business_name}" has been suspended. Reason: {reason or "Please contact support."}',
            entity_type='ProviderProfile',
            entity_id=self.id
        )
    
    def unsuspend(self):
        """Unsuspend provider"""
        self.is_suspended = False
        self.suspension_reason = ""
        self.suspended_at = None
        self.suspended_by = None
        self.save()
        
        from notifications.utils import create_notification
        create_notification(
            recipient=self.user,
            notification_type='account_restored',
            title='Account Restored',
            message=f'Your business "{self.business_name}" has been restored.',
            entity_type='ProviderProfile',
            entity_id=self.id
        )