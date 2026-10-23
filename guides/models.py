from django.db import models
from django.db import connection
from django.contrib.auth.models import User
from django.utils import timezone
from accounts.models import Profile


def get_or_create_guide_profile(profile):
    """Get or create a guide profile with empty default values"""
    try:
        return GuideProfile.objects.get(profile=profile)
    except GuideProfile.DoesNotExist:
        return GuideProfile.objects.create(
            profile=profile,
            biography='',
            years_experience=0,
            years_experience_set=False,
            languages=[],
            specializations=[],
            qualifications=[],
            areas_of_expertise=[],
            verification_status='pending'
        )


class GuideProfile(models.Model):
    VERIFICATION_STATUS_CHOICES = [
        ('pending', 'Pending Verification'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('suspended', 'Suspended'),
    ]

    # Link to Profile
    profile = models.OneToOneField(
        Profile,
        on_delete=models.CASCADE,
        related_name='guide_profile'
    )

    # Professional Information
    biography = models.TextField(blank=True)
    years_experience = models.IntegerField(default=0)

    # NEW: tracks whether the guide has ever set their years_experience
    # (Option B — distinguishes "never set" from "explicitly set to 0")
    years_experience_set = models.BooleanField(
        default=False,
        help_text="Has the guide ever set their years of experience?"
    )

    # Languages
    languages = models.JSONField(default=list, help_text="List of languages spoken")

    # Specializations
    specializations = models.JSONField(
        default=list,
        blank=True,
        help_text="List of tourism specializations"
    )
    areas_of_expertise = models.JSONField(
        default=list,
        blank=True,
        help_text="List of expertise areas"
    )

    # Qualifications
    qualifications = models.JSONField(
        default=list,
        blank=True,
        help_text="List of qualifications/certifications"
    )

    # Availability
    is_available = models.BooleanField(default=True)
    availability_schedule = models.JSONField(
        default=dict,
        blank=True,
        help_text="Weekly availability schedule"
    )

    # Ratings
    average_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    total_reviews = models.IntegerField(default=0)
    total_tours_given = models.IntegerField(default=0)

    # Verification
    verification_status = models.CharField(
        max_length=20,
        choices=VERIFICATION_STATUS_CHOICES,
        default='pending'
    )

    # NEW: notes from the admin when approving / rejecting / requesting changes
    verification_notes = models.TextField(
        blank=True,
        help_text="Admin notes explaining approval/rejection reason"
    )

    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_guides'
    )

    # Documents (for verification)
    id_document = models.FileField(upload_to='guides/documents/', null=True, blank=True)
    certification_document = models.FileField(upload_to='guides/certifications/', null=True, blank=True)

    # Account Status
    is_active = models.BooleanField(
        default=True,
        help_text="Is this guide account active?"
    )
    is_suspended = models.BooleanField(
        default=False,
        help_text="Has this guide been suspended?"
    )
    suspension_reason = models.TextField(blank=True)
    suspended_at = models.DateTimeField(null=True, blank=True)
    suspended_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='suspended_guides'
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ============ BASIC PROPERTIES ============

    def __str__(self):
        return f"Guide: {self.profile.user.first_name}"

    @property
    def user(self):
        return self.profile.user

    @property
    def full_name(self):
        return f"{self.user.first_name} {self.user.last_name}".strip() or self.user.username

    @property
    def email(self):
        return self.user.email

    @property
    def is_verified(self):
        return self.verification_status == 'approved'

    @property
    def is_public(self):
        return self.is_verified and self.is_active and not self.is_suspended

    @property
    def verification_status_display(self):
        """Human-readable verification status for templates"""
        return dict(self.VERIFICATION_STATUS_CHOICES).get(
            self.verification_status, 'Pending'
        )

    # ============ NEW: AVAILABILITY LOGIC (single source of truth) ============

    @property
    def has_schedule(self):
        """
        True if the guide has set at least one active working day.
        availability_schedule is a dict like:
            {'monday': {'available': True, 'start': '09:00', 'end': '17:00'}, ...}
        """
        schedule = self.availability_schedule or {}
        if not schedule:
            return False
        # Look for any day that is marked available
        for key, value in schedule.items():
            if key == 'blocked_dates':
                continue
            if isinstance(value, dict) and value.get('available'):
                return True
        return False

    @property
    def is_bookable(self):
        """
        THE single source of truth for whether this guide can be booked.

        A guide is bookable ONLY when ALL are true:
          - verified (verification_status == 'approved')
          - active account
          - not suspended
          - master availability switch on (is_available)
          - has a weekly schedule set
        """
        return (
            self.is_verified
            and self.is_active
            and not self.is_suspended
            and self.is_available
            and self.has_schedule
        )

    def is_time_within_schedule(self, date, requested_time):
        """Return whether a requested start time falls within that day's hours."""
        from datetime import datetime

        schedule = self.availability_schedule or {}
        if not isinstance(schedule, dict):
            return False

        day_names = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        day_config = schedule.get(day_names[date.weekday()], {})
        if not isinstance(day_config, dict) or not day_config.get('available'):
            return False

        try:
            start_time = datetime.strptime(day_config.get('start', ''), '%H:%M').time()
            end_time = datetime.strptime(day_config.get('end', ''), '%H:%M').time()
        except (TypeError, ValueError):
            return False

        return start_time <= requested_time < end_time

    @property
    def availability_status(self):
        """
        Return a machine-readable status for templates + badges.
        Values: 'available', 'unavailable', 'no_schedule',
                'pending_verification', 'suspended', 'inactive'
        """
        if self.is_suspended:
            return 'suspended'
        if not self.is_active:
            return 'inactive'
        if self.verification_status != 'approved':
            return 'pending_verification'
        if not self.is_available:
            return 'unavailable'
        if not self.has_schedule:
            return 'no_schedule'
        return 'available'

    # ============ NEW: EXPERIENCE DISPLAY (Option B) ============

    @property
    def experience_display(self):
        """
        Return how 'years of experience' should be displayed on the card.

        Option B rules:
          - If guide has never set years_experience  -> return ''  (blank)
          - If guide set 0 explicitly                -> return '0 years'
          - If guide set a positive number           -> return '{n} years'
        """
        if not self.years_experience_set:
            return ''
        if self.years_experience <= 0:
            return '0 years'
        if self.years_experience == 1:
            return '1 year'
        return f'{self.years_experience} years'

    # ============ BOOKING-RELATED PROPERTIES ============

    @property
    def bookings(self):
        from bookings.models import Booking
        return Booking.objects.filter(guide=self)

    @property
    def pending_bookings(self):
        return self.bookings.filter(status='pending')

    @property
    def confirmed_bookings(self):
        return self.bookings.filter(status='confirmed')

    @property
    def completed_bookings(self):
        return self.bookings.filter(status='completed')

    @property
    def cancelled_bookings(self):
        return self.bookings.filter(status='cancelled')

    @property
    def rejected_bookings(self):
        return self.bookings.filter(status='rejected')

    @property
    def upcoming_tours(self):
        return self.bookings.filter(
            status='confirmed',
            booking_date__gte=timezone.now().date()
        ).order_by('booking_date')

    @property
    def total_bookings(self):
        return self.bookings.count()

    @property
    def total_confirmed(self):
        return self.confirmed_bookings.count()

    @property
    def total_pending(self):
        return self.pending_bookings.count()

       # ============ REVIEWS ============

    @property
    def reviews(self):
        """All reviews about this guide (any moderation status)."""
        from reviews.models import Review
        return Review.objects.filter(guide=self)

    @property
    def approved_reviews(self):
        """Only the reviews approved by admin."""
        return self.reviews.filter(moderation_status='approved')

    @property
    def total_reviews_count(self):
        """Total approved review count."""
        return self.approved_reviews.count()

    @property
    def rating_stars(self):
        """Star display for the average rating."""
        rating = float(self.average_rating)
        return '★' * int(rating) + '☆' * (5 - int(rating))

    # ============ NOTIFICATIONS ============

    @property
    def notifications(self):
        from notifications.models import Notification
        return Notification.objects.filter(recipient=self.user)

    @property
    def unread_notifications(self):
        return self.notifications.filter(is_read=False)

    @property
    def unread_count(self):
        return self.unread_notifications.count()

    # ============ METHODS ============

    def is_approved(self):
        return self.verification_status == 'approved'

    def can_be_assigned(self):
        """
        Whether this guide can currently be assigned new bookings.
        Uses the strict availability rule.
        """
        return self.is_bookable

    def approve(self, verified_by=None, notes=""):
        """
        Admin approves the guide's verification.
        Sets status to 'approved', records who approved it, and notifies the guide.
        """
        self.verification_status = 'approved'
        self.verified_at = timezone.now()
        if verified_by:
            self.verified_by = verified_by
        # FIXED: now writes to the actual field
        if notes:
            self.verification_notes = notes
        else:
            self.verification_notes = ''
        self.save()

        from notifications.models import Notification
        Notification.objects.create(
            recipient=self.user,
            notification_type='verification',
            title='Profile Verified',
            message="Your guide profile has been verified. You can now accept bookings."
        )

    def reject(self, reason=""):
        """
        Admin rejects the guide's verification.
        """
        self.verification_status = 'rejected'
        # FIXED: now writes to the actual field
        self.verification_notes = reason or 'Please update your profile and resubmit.'
        self.save()

        from notifications.models import Notification
        Notification.objects.create(
            recipient=self.user,
            notification_type='verification',
            title='Profile Rejected',
            message=f"Your guide profile was rejected. Reason: {self.verification_notes}"
        )

    def suspend(self, reason="", suspended_by=None):
        """Admin suspends the guide account."""
        self.is_suspended = True
        self.suspension_reason = reason
        self.suspended_at = timezone.now()
        if suspended_by:
            self.suspended_by = suspended_by
        self.save()

        from notifications.models import Notification
        Notification.objects.create(
            recipient=self.user,
            notification_type='account',
            title='Account Suspended',
            message=f"Your guide account has been suspended. Reason: {reason or 'Please contact support.'}"
        )

    def unsuspend(self):
        """Admin restores the guide account."""
        self.is_suspended = False
        self.suspension_reason = ""
        self.suspended_at = None
        self.suspended_by = None
        self.save()

        from notifications.models import Notification
        Notification.objects.create(
            recipient=self.user,
            notification_type='account',
            title='Account Restored',
            message="Your guide account has been restored. You can now accept bookings."
        )

    def accept_booking(self, booking):
        """Guide accepts a pending booking."""
        if booking.status != 'pending':
            return False
        booking.status = 'confirmed'
        booking.confirmed_at = timezone.now()
        booking.save()

        from notifications.models import Notification
        Notification.objects.create(
            recipient=booking.visitor.user,
            notification_type='booking',
            title='Booking Confirmed',
            message=f"Your booking with {self.full_name} has been confirmed for {booking.booking_date.strftime('%d %b %Y')}."
        )
        return True

    def decline_booking(self, booking, reason=""):
        """Guide declines a pending booking."""
        if booking.status != 'pending':
            return False
        booking.status = 'rejected'
        booking.rejection_reason = reason
        booking.rejected_at = timezone.now()
        booking.save()

        from notifications.models import Notification
        Notification.objects.create(
            recipient=booking.visitor.user,
            notification_type='booking',
            title='Booking Declined',
            message=f"Your booking with {self.full_name} was declined. Reason: {reason or 'Guide is unavailable.'}"
        )
        return True

    def mark_tour_completed(self, booking):
        """Guide marks a confirmed booking as completed."""
        if booking.status != 'confirmed':
            return False
        booking.status = 'completed'
        booking.completed_at = timezone.now()
        booking.save()

        self.total_tours_given += 1
        self.save()

        from notifications.models import Notification
        Notification.objects.create(
            recipient=booking.visitor.user,
            notification_type='review',
            title='Tour Completed',
            message=f"Your tour with {self.full_name} on {booking.booking_date.strftime('%d %b %Y')} is complete. Please leave a review."
        )
        return True

    def has_conflict(self, date, time, duration_minutes=60):
        """
        Check whether the guide has any reason they cannot take this
        booking at the given date/time.

        Returns a dict (same shape as Booking.check_clash):
            {
                'has_clash': bool,
                'reason': str or None,
                'code': str or None,
            }

        Codes:
            suspended        — guide is suspended / inactive
            not_verified     — guide not verified
            no_schedule      — guide has no weekly hours set
            day_off          — guide is off that weekday
            blocked          — guide blocked that specific date
            overlap          — guide already confirmed booking nearby
        """
        from datetime import datetime, timedelta

        # ---- Rule 1: Guide status ----
        if self.is_suspended or not self.is_active:
            return {
                'has_clash': True,
                'reason': 'This guide account is not active.',
                'code': 'suspended',
            }

        if not self.is_verified:
            return {
                'has_clash': True,
                'reason': 'This guide is not verified yet.',
                'code': 'not_verified',
            }

        # ---- Rule 2: Guide has a schedule ----
        if not self.has_schedule:
            return {
                'has_clash': True,
                'reason': 'This guide has not set their working hours.',
                'code': 'no_schedule',
            }

        # ---- Rule 3: Day-of-week ----
        day_names = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        day_key = day_names[date.weekday()]
        schedule = self.availability_schedule or {}
        day_config = schedule.get(day_key, {}) or {}

        if not day_config.get('available'):
            return {
                'has_clash': True,
                'reason': f'The guide does not work on {day_key.capitalize()}.',
                'code': 'day_off',
            }

        if not self.is_time_within_schedule(date, time):
            return {
                'has_clash': True,
                'reason': 'The requested time is outside the guide\'s working hours.',
                'code': 'outside_working_hours',
            }

        # ---- Rule 4: Blocked dates ----
        blocked = schedule.get('blocked_dates', []) or []
        for entry in blocked:
            if not isinstance(entry, dict):
                continue
            try:
                if str(entry.get('date', '')) == date.strftime('%Y-%m-%d'):
                    reason = entry.get('reason') or 'Guide is unavailable on this date.'
                    return {
                        'has_clash': True,
                        'reason': reason,
                        'code': 'blocked',
                    }
            except Exception:
                continue

        # ---- Rule 5: Overlapping confirmed booking ----
        start = datetime.combine(date, time)
        window_start = (start - timedelta(minutes=duration_minutes)).time()
        window_end = (start + timedelta(minutes=duration_minutes)).time()

        overlapping = self.bookings.filter(
            status='confirmed',
            booking_date=date,
            booking_time__gte=window_start,
            booking_time__lte=window_end,
        ).exists()

        if overlapping:
            return {
                'has_clash': True,
                'reason': 'The guide already has a confirmed booking at that time.',
                'code': 'overlap',
            }

        # ---- No clash ----
        return {'has_clash': False, 'reason': None, 'code': None}

    def get_availability_for_day(self, day_of_week):
        """Return the schedule entry for a given weekday index (0=Monday)."""
        schedule = self.availability_schedule or {}
        day_names = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        day_key = day_names[day_of_week] if 0 <= day_of_week < 7 else 'monday'
        return schedule.get(day_key, {})

    def set_availability_schedule(self, schedule):
        self.availability_schedule = schedule
        self.save()

    def update_review_stats(self):
        """Recalculate average rating and total reviews."""
        from django.db.models import Avg, Count
        from reviews.models import Review

        stats = Review.objects.filter(
            guide=self,
            moderation_status='approved'
        ).aggregate(
            avg_rating=Avg('rating'),
            total=Count('id')
        )

        self.average_rating = stats['avg_rating'] or 0
        self.total_reviews = stats['total'] or 0
        self.save()

    class Meta:
        indexes = [
            models.Index(fields=['verification_status']),
            models.Index(fields=['average_rating']),
            models.Index(fields=['is_available']),
            models.Index(fields=['is_suspended']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    verification_status__in=['pending', 'approved', 'rejected', 'suspended']
                ),
                name='guide_verification_valid',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(years_experience__gte=0)
                    & models.Q(average_rating__gte=0)
                    & models.Q(average_rating__lte=5)
                    & models.Q(total_reviews__gte=0)
                    & models.Q(total_tours_given__gte=0)
                ),
                name='guide_metrics_valid',
            ),
        ]