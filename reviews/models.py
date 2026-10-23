from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.db.models import Avg, Count


class Review(models.Model):
    """
    A review written by a TouristProfile (the 'visitor') after a completed booking.

    FR-13: Tourist Reviews Guide and Experience
    Traceability: UC-13 Tourist Leaves Review

    Domain rules:
        - Every review MUST link to a Booking (proof it happened).
        - Every review has a REVIEW_TYPE:
            'guide'      → the review is about the guide
            'experience' → the review is about the experience
        - A booking can have up to TWO reviews (one of each type).
        - Only reviews with moderation_status='approved' count toward ratings.
    """

    MODERATION_STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('reported', 'Reported'),
        ('removed', 'Removed'),
    ]

    REVIEW_TYPE_CHOICES = [
        ('guide', 'Guide Review'),
        ('experience', 'Experience Review'),
    ]

    # ============ WHO WROTE IT ============
    visitor = models.ForeignKey(
        'tourist.TouristProfile',
        on_delete=models.CASCADE,
        related_name='reviews'
    )

    # ============ TYPE OF REVIEW ============
    review_type = models.CharField(
        max_length=20,
        choices=REVIEW_TYPE_CHOICES,
        default='guide',
        help_text="What is this review about?"
    )

    # ============ SUBJECTS ============
    guide = models.ForeignKey(
        'guides.GuideProfile',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='received_reviews',
        help_text="The guide this review is about (required for guide reviews)"
    )

    experience = models.ForeignKey(
        'experiences.Experience',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviews',
        help_text="The experience this review is about (required for experience reviews)"
    )

    # ============ PROOF OF BOOKING ============
    booking = models.ForeignKey(
        'bookings.Booking',
        on_delete=models.CASCADE,
        related_name='reviews',
        help_text="The booking this review was written for"
    )

    # ============ RATING ============
    rating = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )

    # ============ CONTENT ============
    title = models.CharField(max_length=100, blank=True)
    comment = models.TextField()
    pros = models.TextField(blank=True, help_text="What was good?")
    cons = models.TextField(blank=True, help_text="What could be improved?")

    # ============ IMAGES ============
    images = models.JSONField(default=list, blank=True, help_text="List of image URLs")

    # ============ MODERATION ============
    moderation_status = models.CharField(
        max_length=20,
        choices=MODERATION_STATUS_CHOICES,
        default='pending'
    )
    moderated_at = models.DateTimeField(null=True, blank=True)
    moderated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='moderated_reviews'
    )
    moderation_notes = models.TextField(blank=True)

    # ============ REMOVAL (escalation from rejected) ============
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='removed_reviews'
    )

    # ============ REPORTS ============
    report_count = models.IntegerField(default=0)
    reports = models.JSONField(default=list, blank=True, help_text="List of report reasons")

    # ============ HELPFULNESS ============
    helpful_count = models.IntegerField(default=0)
    not_helpful_count = models.IntegerField(default=0)

    # ============ TIMESTAMPS ============
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        reviewer = self.visitor.user.first_name if self.visitor_id else "Unknown"
        target = self.subject_name
        return f"{self.get_review_type_display()} by {reviewer} about {target} — {self.rating}★"

    # ============ SAVE OVERRIDE ============
    def save(self, *args, **kwargs):
        """
        Save the review, then recalculate the subject's rating.

        Ensures average_rating and total_reviews stay in sync on every
        create / edit / status change — even if a caller forgets to call
        recalculate_ratings() manually.
        """
        super().save(*args, **kwargs)

        # Refresh the affected subject's stats.
        # Guarded with `_id` checks so we never touch a deleted FK.
        if self.review_type == 'guide' and self.guide_id:
            self._update_guide_stats(self.guide)
        elif self.review_type == 'experience' and self.experience_id:
            self._update_experience_stats(self.experience)

    # ============ PROPERTIES ============

    @property
    def is_approved(self):
        return self.moderation_status == 'approved'

    @property
    def is_pending(self):
        return self.moderation_status == 'pending'

    @property
    def is_rejected(self):
        return self.moderation_status == 'rejected'

    @property
    def is_reported(self):
        return self.moderation_status == 'reported'

    @property
    def is_removed(self):
        return self.moderation_status == 'removed'

    @property
    def is_visible_publicly(self):
        return self.moderation_status not in ['rejected', 'removed']

    @property
    def stars_display(self):
        return '★' * self.rating + '☆' * (5 - self.rating)

    @property
    def subject_name(self):
        """Human-readable subject of this review."""
        if self.review_type == 'guide' and self.guide_id:
            return self.guide.full_name
        if self.review_type == 'experience' and self.experience_id:
            return self.experience.name
        if self.guide_id:
            return self.guide.full_name
        if self.experience_id:
            return self.experience.name
        return "Unknown"

    @property
    def reviewer_name(self):
        if self.visitor_id and self.visitor.profile.user:
            user = self.visitor.profile.user
            return f"{user.first_name} {user.last_name}".strip() or user.username
        return "Anonymous"

    # ============ METHODS ============

    def report(self, reason, reported_by):
        """Add a report for this review. Auto-flags if 3+ reports."""
        self.report_count += 1
        self.reports.append({
            'reported_by': reported_by.id,
            'reason': reason,
            'timestamp': timezone.now().isoformat()
        })
        if self.report_count >= 3:
            self.moderation_status = 'reported'
        self.save()

    def moderate(self, moderator, status, notes=""):
        """
        Moderate the review (approve, reject, etc.)
        Recalculates the affected subject's stats after moderation.
        """
        self.moderation_status = status
        self.moderated_at = timezone.now()
        self.moderated_by = moderator
        self.moderation_notes = notes

        # If moderating to 'removed', also record removal metadata
        if status == 'removed':
            self.removed_at = timezone.now()
            self.removed_by = moderator

        self.save()

        # save() already recalculates, but call explicitly for clarity
        self.recalculate_ratings()

    def recalculate_ratings(self):
        """
        Recalculate average_rating and total_reviews for the subject
        of this review, based on review_type.

        Only counts reviews with moderation_status='approved'.
        """
        if self.review_type == 'guide' and self.guide_id:
            self._update_guide_stats(self.guide)
        elif self.review_type == 'experience' and self.experience_id:
            self._update_experience_stats(self.experience)

        if self.experience_id and self.experience and self.experience.guide:
            self._update_guide_stats(self.experience.guide)

    def _update_guide_stats(self, guide):
        """Recalc one guide's average_rating and total_reviews."""
        stats = Review.objects.filter(
            guide=guide,
            review_type='guide',
            moderation_status='approved'
        ).aggregate(avg=Avg('rating'), total=Count('id'))

        guide.average_rating = stats['avg'] or 0
        guide.total_reviews = stats['total'] or 0
        guide.save(update_fields=['average_rating', 'total_reviews'])

    def _update_experience_stats(self, experience):
        """Recalc one experience's average_rating and total_reviews."""
        stats = Review.objects.filter(
            experience=experience,
            review_type='experience',
            moderation_status='approved'
        ).aggregate(avg=Avg('rating'), total=Count('id'))

        experience.average_rating = stats['avg'] or 0
        experience.total_reviews = stats['total'] or 0
        experience.save(update_fields=['average_rating', 'total_reviews'])

    # ============ META ============

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['visitor']),
            models.Index(fields=['guide']),
            models.Index(fields=['experience']),
            models.Index(fields=['booking']),
            models.Index(fields=['review_type']),
            models.Index(fields=['rating']),
            models.Index(fields=['moderation_status']),
            models.Index(fields=['created_at']),
        ]
        unique_together = [
            ('booking', 'review_type'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(review_type__in=['guide', 'experience']),
                name='review_type_valid',
            ),
            models.CheckConstraint(
                condition=models.Q(
                    moderation_status__in=['pending', 'approved', 'rejected', 'reported', 'removed']
                ),
                name='review_status_valid',
            ),
            models.CheckConstraint(
                condition=models.Q(rating__gte=1) & models.Q(rating__lte=5),
                name='review_rating_valid',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(report_count__gte=0)
                    & models.Q(helpful_count__gte=0)
                    & models.Q(not_helpful_count__gte=0)
                ),
                name='review_counts_valid',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(review_type='guide', guide__isnull=False)
                    | models.Q(review_type='experience', experience__isnull=False)
                ),
                name='review_subject_required',
            ),
        ]
        verbose_name = "Review"
        verbose_name_plural = "Reviews"