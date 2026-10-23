from django.db import models, transaction
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.exceptions import ValidationError

User = get_user_model()
MAX_BOOKING_PARTICIPANTS = 200


class Booking(models.Model):
    """
    FR-06: Tourist Books Guide
    Traceability: UC-06 Book Tour Guide

    Status Flow:
        PENDING → CONFIRMED → COMPLETED
        PENDING → REJECTED
        CONFIRMED → CANCELLED (by tourist)
        CONFIRMED → COMPLETED (by guide)

    Admin Gate:
        New bookings start with admin_approved=False.
        The admin must confirm the guide assignment before
        the guide can accept or decline.
    """

    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('rejected', 'Rejected'),
        ('no_show', 'No Show'),
    )

    # ============ DIRECT CONNECTIONS ============
    visitor = models.ForeignKey(
        'tourist.TouristProfile',
        on_delete=models.CASCADE,
        related_name='bookings'
    )

    guide = models.ForeignKey(
        'guides.GuideProfile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bookings'
    )

    experience = models.ForeignKey(
        'experiences.Experience',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bookings'
    )

    # ============ BOOKING DETAILS ============
    booking_date = models.DateField(help_text="Date of the tour")
    booking_time = models.TimeField(help_text="Time of the tour")
    number_of_participants = models.PositiveIntegerField(default=1)
    special_requests = models.TextField(blank=True, null=True)

    # ============ PRICING ============
    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    currency = models.CharField(max_length=3, default='ZAR')

    # ============ STATUS & TRACKING ============
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    # ============ ADMIN ASSIGNMENT APPROVAL ============
    admin_approved = models.BooleanField(
        default=False,
        help_text="Has an admin confirmed the guide assignment?"
    )
    admin_approved_at = models.DateTimeField(null=True, blank=True)
    admin_approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_bookings'
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)

    # Reasons
    cancellation_reason = models.TextField(blank=True, null=True)
    rejection_reason = models.TextField(blank=True, null=True)

    # Who performed actions
    confirmed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='confirmed_bookings'
    )
    cancelled_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cancelled_bookings'
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['visitor', 'status']),
            models.Index(fields=['guide', 'status']),
            models.Index(fields=['booking_date', 'status']),
            models.Index(fields=['status', 'booking_date']),
            models.Index(fields=['admin_approved', 'status']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(number_of_participants__gte=1)
                    & models.Q(number_of_participants__lte=MAX_BOOKING_PARTICIPANTS)
                ),
                name='booking_participants_1_200',
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=[
                    'pending', 'confirmed', 'completed', 'cancelled', 'rejected', 'no_show',
                ]),
                name='booking_status_valid',
            ),
            models.CheckConstraint(
                condition=models.Q(total_price__gte=0),
                name='booking_price_nonnegative',
            ),
        ]

    def __str__(self):
        guide_name = self.guide.full_name if self.guide else "No Guide"
        visitor_name = self.visitor.user.get_full_name() or self.visitor.user.username
        return f"Booking #{self.id}: {visitor_name} → {guide_name} ({self.booking_date})"

    # ============ PROPERTIES ============
    @property
    def is_pending(self):
        return self.status == 'pending'

    @property
    def is_confirmed(self):
        return self.status == 'confirmed'

    @property
    def is_completed(self):
        return self.status == 'completed'

    @property
    def is_cancelled(self):
        return self.status == 'cancelled'

    @property
    def is_rejected(self):
        return self.status == 'rejected'

    @property
    def is_awaiting_admin(self):
        return self.status == 'pending' and not self.admin_approved

    @property
    def is_awaiting_guide(self):
        return self.status == 'pending' and self.admin_approved

    @property
    def can_admin_approve(self):
        return self.status == 'pending' and not self.admin_approved

    @property
    def can_accept(self):
        return self.status == 'pending' and self.admin_approved

    @property
    def can_decline(self):
        return self.status == 'pending' and self.admin_approved

    @property
    def can_complete(self):
        return (
            self.status == 'confirmed'
            and self.booking_date is not None
            and self.booking_date <= timezone.localdate()
        )

    @property
    def can_review(self):
        return self.status == 'completed'

    @property
    def can_cancel(self):
        if self.status not in ['pending', 'confirmed']:
            return False

        from datetime import datetime, timedelta
        try:
            tour_start = datetime.combine(self.booking_date, self.booking_time)
            tour_start = timezone.make_aware(tour_start) if timezone.is_naive(tour_start) else tour_start
        except Exception:
            return False

        cutoff = tour_start - timedelta(hours=24)
        return timezone.now() < cutoff

    @property
    def destination_summary(self):
        stops = list(self.destinations.all().order_by('order'))
        if not stops:
            return "No destination specified"
        names = [s.name for s in stops]
        if len(names) == 1:
            return names[0]
        return f"{names[0]} + {len(names) - 1} more"

    @property
    def destination_list(self):
        return self.destinations.all().order_by('order')

    # ============ REVIEW STATE ============

    @property
    def has_guide_review(self):
        """True if a review about the guide exists for this booking."""
        from reviews.models import Review
        return Review.objects.filter(
            booking=self,
            review_type='guide'
        ).exists()

    @property
    def has_experience_review(self):
        """
        True if a review about the experience exists for this booking.
        Always False when the booking has no experience.
        """
        if not self.experience_id:
            return False
        from reviews.models import Review
        return Review.objects.filter(
            booking=self,
            review_type='experience'
        ).exists()

    @property
    def has_all_reviews(self):
        """
        True when every applicable review is submitted.

        - Booking with guide AND experience → both reviews required.
        - Booking with only a guide → only the guide review.
        """
        if not self.guide_id:
            return False
        if not self.has_guide_review:
            return False
        if self.experience_id and not self.has_experience_review:
            return False
        return True

    @property
    def needs_review(self):
        """
        Booking is completed AND at least one review is still outstanding.
        Used to decide whether to show the 'Leave Review' button.
        """
        return self.status == 'completed' and not self.has_all_reviews

    # ============ AUTO-LINK EXPERIENCE ============

    def auto_link_experience(self):
        """
        Try to find a matching Experience for this booking based on
        the destination names (tourist-typed tour stops).

        Called from complete() so bookings get linked before reviews
        become available.

        Matching strategy (in order):
          1. Exact match (case-insensitive)
          2. Substring match on the destination name

        Returns the matched Experience or None.
        """
        if self.experience_id:
            return None

        destinations = list(self.destinations.all())
        if not destinations:
            return None

        from experiences.models import Experience
        from django.db.models import Q

        for dest in destinations:
            name = (dest.name or '').strip()
            if not name:
                continue

            # 1. Exact (case-insensitive) match
            match = Experience.objects.filter(
                status='published',
                name__iexact=name,
            ).first()

            # 2. Substring match (either direction)
            if not match:
                match = Experience.objects.filter(
                    status='published',
                ).filter(
                    Q(name__icontains=name) | Q(name__icontains=name.split()[0] if name.split() else name)
                ).order_by('-average_rating').first()

            if match:
                self.experience = match
                self.save(update_fields=['experience', 'updated_at'])
                return match

        return None

    # ============ CLASH DETECTION ============

    def has_conflict(self, date=None, time=None, duration_minutes=60):
        date = date or self.booking_date
        time = time or self.booking_time

        if not self.guide:
            return {'has_clash': False, 'severity': 'ok', 'reason': None, 'code': None}

        return self.check_clash(self.guide, date, time, duration_minutes)

    def check_clash(self, guide, date=None, time=None, duration_minutes=60):
        date = date or self.booking_date
        time = time or self.booking_time

        # Rule 1
        if guide.is_suspended or not guide.is_active:
            return {'has_clash': True, 'severity': 'blocker', 'reason': 'This guide account is not active.', 'code': 'suspended'}

        if not guide.is_verified:
            return {'has_clash': True, 'severity': 'blocker', 'reason': 'This guide is not verified yet.', 'code': 'not_verified'}

        # Rule 2
        if not guide.has_schedule:
            return {'has_clash': True, 'severity': 'blocker', 'reason': 'This guide has not set their working hours.', 'code': 'no_schedule'}

        # Rule 3
        from datetime import datetime, timedelta
        day_names = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        day_key = day_names[date.weekday()]
        schedule = guide.availability_schedule or {}
        day_config = schedule.get(day_key, {}) or {}

        if not day_config.get('available'):
            return {'has_clash': True, 'severity': 'blocker', 'reason': f'The guide does not work on {day_key.capitalize()}.', 'code': 'day_off'}

        if not guide.is_time_within_schedule(date, time):
            return {
                'has_clash': True,
                'severity': 'blocker',
                'reason': 'The requested time is outside the guide\'s working hours.',
                'code': 'outside_working_hours',
            }

        # Rule 4
        blocked = schedule.get('blocked_dates', []) or []
        for entry in blocked:
            if not isinstance(entry, dict):
                continue
            try:
                if str(entry.get('date', '')) == date.strftime('%Y-%m-%d'):
                    reason = entry.get('reason') or 'Guide is unavailable on this date.'
                    return {'has_clash': True, 'severity': 'blocker', 'reason': reason, 'code': 'blocked'}
            except Exception:
                continue

        # Rule 5
        start = datetime.combine(date, time)
        window_start = (start - timedelta(minutes=duration_minutes)).time()
        window_end = (start + timedelta(minutes=duration_minutes)).time()

        base_qs = Booking.objects.filter(
            guide=guide,
            booking_date=date,
            booking_time__gte=window_start,
            booking_time__lte=window_end,
        ).exclude(pk=self.pk)

        if base_qs.filter(status='confirmed').exists():
            return {'has_clash': True, 'severity': 'blocker', 'reason': 'The guide already has a confirmed booking at that time.', 'code': 'overlap_confirmed'}

        if base_qs.filter(status='pending').exists():
            return {'has_clash': True, 'severity': 'warning', 'reason': 'Another pending request exists for this guide at this time.', 'code': 'overlap_pending'}

        return {'has_clash': False, 'severity': 'ok', 'reason': None, 'code': None}

    # ============ BUSINESS METHODS ============

    def accept(self, guide=None, confirmed_by=None):
        with transaction.atomic():
            if not self.can_accept:
                raise ValidationError(
                    'Cannot accept this booking. '
                    'It must be pending and confirmed by admin first.'
                )

            if guide:
                self.guide = guide

            if self.guide:
                from guides.models import GuideProfile
                locked_guide = GuideProfile.objects.select_for_update().get(pk=self.guide_id)
                clash = self.check_clash(
                    locked_guide,
                    self.booking_date,
                    self.booking_time,
                )
                if clash['severity'] == 'blocker':
                    raise ValidationError(
                        f'Cannot accept this booking: {clash["reason"]}'
                    )
                self.guide = locked_guide

            self.status = 'confirmed'
            self.confirmed_at = timezone.now()
            if confirmed_by:
                self.confirmed_by = confirmed_by
            self.save()

        from notifications.utils import create_notification
        create_notification(
            recipient=self.visitor.user,
            notification_type='booking_confirmed',
            title='Booking Confirmed',
            message=(
                f'Your booking with {self.guide.full_name} has been confirmed '
                f'for {self.booking_date.strftime("%d %b %Y")} at '
                f'{self.booking_time.strftime("%H:%M")}.'
            ),
            entity_type='Booking',
            entity_id=self.id
        )

        return True

    def decline(self, reason=None):
        if not self.can_decline:
            raise ValidationError(
                'Cannot decline this booking. '
                'It must be pending and confirmed by admin first.'
            )

        self.status = 'rejected'
        self.rejection_reason = reason or 'No reason provided'
        self.rejected_at = timezone.now()
        self.save()

        from notifications.utils import create_notification
        create_notification(
            recipient=self.visitor.user,
            notification_type='booking_rejected',
            title='Booking Declined',
            message=(
                f'Your booking with {self.guide.full_name} was declined. '
                f'Reason: {self.rejection_reason}'
            ),
            entity_type='Booking',
            entity_id=self.id
        )

        return True

    def complete(self):
        """
        Mark the booking as completed.

        Side effects:
          1. Try to auto-link a real Experience (from tour stop names)
          2. Increment the guide's total_tours_given
          3. Send in-app notification with a deep link to the review page
          4. Send email to the tourist asking for a review
        """
        if self.status != 'confirmed':
            raise ValidationError(f"Cannot complete booking with status: {self.status}")
        if not self.can_complete:
            raise ValidationError('A future booking cannot be marked as completed.')

        self.status = 'completed'
        self.completed_at = timezone.now()
        self.save()

        # 1. Try to auto-link a real Experience
        try:
            self.auto_link_experience()
        except Exception:
            pass

        # 2. Increment guide stat
        if self.guide:
            self.guide.total_tours_given += 1
            self.guide.save()

        # 3. In-app notification with deep link
        try:
            from notifications.utils import create_notification
            create_notification(
                recipient=self.visitor.user,
                notification_type='tour_completed',
                title='Tour Completed',
                message=(
                    f'Your tour with {self.guide.full_name if self.guide else "your guide"} on '
                    f'{self.booking_date.strftime("%d %b %Y")} is complete. '
                    f'Please take a moment to leave a review.'
                ),
                link=f'/reviews/create/{self.id}/',
                entity_type='Booking',
                entity_id=self.id
            )
        except Exception:
            pass

        # 4. Email the tourist
        try:
            from accounts.utils import send_tour_completed_email
            send_tour_completed_email(self)
        except Exception:
            pass

        return True

    def cancel(self, user=None, reason=None):
        """Cancel a booking. Notifies BOTH the guide and all admins with the reason."""
        if not self.can_cancel:
            raise ValidationError(f"Cannot cancel booking with status: {self.status}")

        self.status = 'cancelled'
        self.cancellation_reason = reason or 'No reason provided'
        self.cancelled_at = timezone.now()
        if user:
            self.cancelled_by = user
        self.save()

        from notifications.utils import create_notification

        if self.guide:
            create_notification(
                recipient=self.guide.user,
                notification_type='booking_cancelled',
                title='Booking Cancelled',
                message=(
                    f'{self.visitor.user.get_full_name() or self.visitor.user.username} '
                    f'cancelled their booking for '
                    f'{self.booking_date.strftime("%d %b %Y")} at '
                    f'{self.booking_time.strftime("%H:%M")}. '
                    f'Reason: {self.cancellation_reason}'
                ),
                link=f'/guides/tour-detail/{self.id}/',
                entity_type='Booking',
                entity_id=self.id
            )

        admin_users = User.objects.filter(profile__role='admin')
        for admin_user in admin_users:
            create_notification(
                recipient=admin_user,
                notification_type='booking_cancelled',
                title=f'Booking #{self.id} Cancelled',
                message=(
                    f'Booking #{self.id} was cancelled by '
                    f'{self.visitor.user.get_full_name() or self.visitor.user.username}. '
                    f'Reason: {self.cancellation_reason}'
                ),
                link=f'/admin_dashboard/bookings/{self.id}/',
                entity_type='Booking',
                entity_id=self.id
            )

        return True

    def admin_approve(self, admin_user, force=False):
        if not self.can_admin_approve:
            raise ValidationError(
                f"Cannot approve booking with status: {self.status} "
                f"(already approved: {self.admin_approved})"
            )

        if self.guide:
            clash = self.check_clash(self.guide, self.booking_date, self.booking_time)
            if clash['severity'] == 'blocker' and not force:
                raise ValidationError(
                    f'Cannot approve: {clash["reason"]} '
                    f'Please assign a different guide or ask the tourist to pick another slot.'
                )

        self.admin_approved = True
        self.admin_approved_at = timezone.now()
        self.admin_approved_by = admin_user
        self.save()

        from notifications.utils import create_notification

        if self.guide:
            create_notification(
                recipient=self.guide.user,
                notification_type='booking_created',
                title='New Booking Assigned to You',
                message=(
                    f'You have a new booking assigned for '
                    f'{self.booking_date.strftime("%d %b %Y")} at '
                    f'{self.booking_time.strftime("%H:%M")}. '
                    f'Please review and respond.'
                ),
                link='/guides/assignments/',
                entity_type='Booking',
                entity_id=self.id
            )

        create_notification(
            recipient=self.visitor.user,
            notification_type='booking_created',
            title='Booking Confirmed by Team',
            message=(
                f'Your booking with '
                f'{self.guide.full_name if self.guide else "the guide"} '
                f'has been reviewed by our team. The guide will respond shortly.'
            ),
            link='/bookings/my/',
            entity_type='Booking',
            entity_id=self.id
        )

        return True

    def get_status_display(self):
        return dict(self.STATUS_CHOICES).get(self.status, self.status)


class BookingDestination(models.Model):
    booking = models.ForeignKey(
        Booking,
        on_delete=models.CASCADE,
        related_name='destinations'
    )

    name = models.CharField(max_length=200, help_text="Name of the place or stop")
    notes = models.TextField(blank=True, help_text="Optional details about this stop")
    order = models.PositiveIntegerField(default=0, help_text="Display order (0-based)")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'id']
        indexes = [
            models.Index(fields=['booking', 'order']),
        ]
        verbose_name = "Booking Destination"
        verbose_name_plural = "Booking Destinations"

    def __str__(self):
        return f"{self.order + 1}. {self.name}"