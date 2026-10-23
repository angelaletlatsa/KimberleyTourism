from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True, help_text="Font Awesome icon class")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Categories"


class Experience(models.Model):
    STATUS_CHOICES = [
        ('submitted', 'Submitted'),
        ('under_review', 'Under Review'),
        ('approved', 'Approved'),
        ('published', 'Published'),
        ('rejected', 'Rejected'),
        ('suspended', 'Suspended'),
        ('archived', 'Archived'),
    ]

    LISTING_TYPE_CHOICES = [
        ('food_dining', 'Food & Dining'),
        ('places_to_stay', 'Places to Stay'),
        ('attractions', 'Attractions'),
        ('activities', 'Activities'),
    ]

    PRICE_UNIT_CHOICES = [
        ('', 'No unit'),
        ('per_person', 'per person'),
        ('per_night', 'per night'),
        ('per_meal', 'per meal'),
        ('per_group', 'per group'),
        ('per_hour', 'per hour'),
    ]

    # ============ BRACKET SCALES (INTERNAL ONLY) ============
    # These are ONLY used to classify a provider's range into
    # filterable buckets. The provider never sees these. Tourists
    # never see these either — they see the provider's own range.
    #
    # Bracket codes are kept identical to the old price_range codes
    # so any existing data / filter queries still work.
    #
    # Each bracket: (code, low, high) — 'high': None means no upper limit.
    CATEGORY_BRACKETS = {
        'food_dining': [
            ('under_150', Decimal('0'),    Decimal('150')),
            ('150_300',   Decimal('150'),  Decimal('300')),
            ('300_600',   Decimal('300'),  Decimal('600')),
            ('over_600',  Decimal('600'),  None),
        ],
        'places_to_stay': [
            ('under_150', Decimal('0'),    Decimal('400')),
            ('150_300',   Decimal('400'),  Decimal('800')),
            ('300_600',   Decimal('800'),  Decimal('1500')),
            ('over_600',  Decimal('1500'), None),
        ],
        'attractions': [
            ('under_150', Decimal('0'),    Decimal('100')),
            ('150_300',   Decimal('100'),  Decimal('250')),
            ('300_600',   Decimal('250'),  Decimal('500')),
            ('over_600',  Decimal('500'),  None),
        ],
        'activities': [
            ('under_150', Decimal('0'),    Decimal('200')),
            ('150_300',   Decimal('200'),  Decimal('450')),
            ('300_600',   Decimal('450'),  Decimal('900')),
            ('over_600',  Decimal('900'),  None),
        ],
    }

    DIFFICULTY_CHOICES = [
        ('easy', 'Easy'),
        ('moderate', 'Moderate'),
        ('challenging', 'Challenging'),
    ]

    CANCELLATION_CHOICES = [
        ('free_24h', 'Free cancellation up to 24 hours before'),
        ('free_48h', 'Free cancellation up to 48 hours before'),
        ('refund_50', '50% refund up to 24 hours before'),
        ('no_refund', 'No refund after booking'),
        ('custom', 'Custom policy'),
    ]

    # Basic Information
    name = models.CharField(max_length=200)
    description = models.TextField()
    short_description = models.CharField(max_length=300, blank=True)

    # Listing Type
    listing_type = models.CharField(
        max_length=30,
        choices=LISTING_TYPE_CHOICES,
        default='activities',
        help_text="Type of listing determines which fields are shown"
    )

    # Relationships
    provider = models.ForeignKey(
        'provider.ProviderProfile',
        on_delete=models.CASCADE,
        related_name='experiences'
    )
    guide = models.ForeignKey(
        'guides.GuideProfile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='experiences'
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        related_name='experiences'
    )

    # Location
    location = models.CharField(max_length=200)
    address = models.TextField(blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # ============ PRICE (provider decides their own range) ============
    # The provider types their own honest range. The app NEVER tells
    # them what to pick. Both ends are optional.

    price_range_min = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Lowest typical price in Rand (optional)"
    )
    price_range_max = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Highest typical price in Rand (optional)"
    )
    price_unit = models.CharField(
        max_length=20, choices=PRICE_UNIT_CHOICES, blank=True, default='',
        help_text="What the price is per (optional)"
    )

    # LEGACY: old hardcoded bracket code. Kept only so old filter queries
    # don't break. Not shown to providers. Not shown to tourists.
    price_range = models.CharField(
        max_length=20, blank=True,
        help_text="(Legacy) Categorised bracket code — auto-derived"
    )

    # Capacity (for Activities)
    max_capacity = models.IntegerField(default=10, help_text="Maximum capacity per booking")
    min_participants = models.IntegerField(default=1, help_text="Minimum needed to run this experience")

    # Duration (for Activities and Attractions)
    duration_minutes = models.IntegerField(null=True, blank=True, help_text="Duration in minutes")

    # Availability
    is_available = models.BooleanField(default=True)
    available_days = models.JSONField(default=list, blank=True, help_text="List of days: 0=Mon, 6=Sun")
    available_from = models.TimeField(null=True, blank=True)
    available_to = models.TimeField(null=True, blank=True)

    # Accessibility
    is_accessible = models.BooleanField(default=False)
    accessibility_info = models.TextField(blank=True)

    # ===== FOOD & DINING SPECIFIC =====
    opening_hours = models.JSONField(default=dict, blank=True)
    cuisine_type = models.CharField(max_length=100, blank=True)
    meal_types = models.TextField(blank=True)
    features = models.TextField(blank=True)
    contact_number = models.CharField(max_length=20, blank=True)
    contact_email = models.EmailField(blank=True)

    # ===== PLACES TO STAY SPECIFIC =====
    check_in_time = models.TimeField(null=True, blank=True)
    check_out_time = models.TimeField(null=True, blank=True)
    amenities = models.JSONField(default=list, blank=True)

    # ===== ACTIVITIES SPECIFIC =====
    meeting_point = models.CharField(max_length=300, blank=True)
    what_to_bring = models.TextField(blank=True)
    age_requirement = models.CharField(max_length=50, blank=True)
    difficulty_level = models.CharField(max_length=20, choices=DIFFICULTY_CHOICES, blank=True)
    languages = models.JSONField(default=list, blank=True)

    # ===== CANCELLATION POLICY =====
    cancellation_policy = models.CharField(max_length=20, choices=CANCELLATION_CHOICES, default='free_24h')
    cancellation_policy_custom = models.TextField(blank=True)

    # Images
    main_image = models.ImageField(upload_to='experiences/', null=True, blank=True)
    images = models.JSONField(default=list, blank=True)

    # Status & Workflow
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='submitted')
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='approved_experiences'
    )
    rejection_reason = models.TextField(blank=True)

    # Suspension
    suspension_reason = models.TextField(blank=True)
    suspended_at = models.DateTimeField(null=True, blank=True)
    suspended_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='suspended_experiences'
    )

    # Booking Notes
    booking_notes = models.TextField(blank=True)

    # Ratings (calculated)
    average_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    total_reviews = models.IntegerField(default=0)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def is_published(self):
        return self.status == 'published'

    def can_be_booked(self):
        return self.is_published() and self.is_available

    # ============ PRICE DISPLAY ============

    @property
    def has_price_info(self):
        """True if the provider has entered at least one number."""
        return self.price_range_min is not None or self.price_range_max is not None

    @property
    def price_unit_display(self):
        """Human label for the unit, or '' if blank."""
        return self.get_price_unit_display() if self.price_unit else ''

    def _format_rand(self, value):
        """Format a Decimal like 1500 -> 'R1,500' (no decimals if whole)."""
        if value is None:
            return None
        # Convert to int if it's a whole number for cleaner display
        if value == value.to_integral_value():
            amount = int(value)
        else:
            amount = float(value)
        return f'R{amount:,}'

    @property
    def price_display(self):
        """
        Honest display of the provider's range.
        Examples:
          'R250 – R700 per person'
          'From R250 per night'
          'Up to R700 per person'
          'R250'
          'Price on request'
        """
        low = self._format_rand(self.price_range_min)
        high = self._format_rand(self.price_range_max)
        unit = self.price_unit_display

        if low and high:
            text = f'{low} – {high}'
        elif low:
            text = f'From {low}'
        elif high:
            text = f'Up to {high}'
        else:
            return 'Price on request'

        if unit:
            text = f'{text} {unit}'

        return text

    @property
    def price_display_short(self):
        """
        Short form for card grids: 'R250 – R700' (no unit).
        """
        low = self._format_rand(self.price_range_min)
        high = self._format_rand(self.price_range_max)

        if low and high:
            return f'{low} – {high}'
        if low:
            return f'From {low}'
        if high:
            return f'Up to {high}'
        return 'Price on request'

    # ============ BRACKET CLASSIFICATION (INTERNAL) ============

    def _brackets_for_type(self):
        """Return the bracket list for this experience's listing_type."""
        return self.CATEGORY_BRACKETS.get(self.listing_type, [])

    @property
    def bracket_codes_for_filter(self):
        """
        Return ALL bracket codes this experience's range touches.
        Option D: a range that spans multiple brackets is included in all.

        If no range is set, returns an empty list (so the experience
        won't appear in any bracket-filtered view).
        """
        if not self.has_price_info:
            return []

        # Use whichever bounds we have; if only one is set, treat it as a point
        low = self.price_range_min if self.price_range_min is not None else self.price_range_max
        high = self.price_range_max if self.price_range_max is not None else self.price_range_min
        if low is None or high is None:
            return []

        # Ensure low <= high
        if low > high:
            low, high = high, low

        codes = []
        for code, b_low, b_high in self._brackets_for_type():
            # bracket range: [b_low, b_high) — b_high None means "and above"
            bracket_top = b_high  # may be None
            # overlap check
            if bracket_top is None:
                # bracket is [b_low, +inf) — overlaps if high >= b_low
                if high >= b_low:
                    codes.append(code)
            else:
                # bracket is [b_low, b_high)
                # overlaps if low < b_high AND high >= b_low
                if low < bracket_top and high >= b_low:
                    codes.append(code)
        return codes

    @property
    def bracket_labels_for_display(self):
        """Human-readable labels of the brackets this experience touches."""
        code_labels = {
            'under_150': 'Budget',
            '150_300': 'Mid-range',
            '300_600': 'Premium',
            'over_600': 'Top',
        }
        return [code_labels.get(c, c) for c in self.bracket_codes_for_filter]

    def save(self, *args, **kwargs):
        """
        Auto-fill the legacy `price_range` field from the first bracket
        the range touches. This keeps old queries working.
        """
        codes = self.bracket_codes_for_filter
        self.price_range = codes[0] if codes else ''
        super().save(*args, **kwargs)

    # ============ RATING / CANCELLATION HELPERS ============

    def get_rating_display(self):
        if self.total_reviews == 0:
            return "No reviews"
        return f"{self.average_rating:.1f} ★ ({self.total_reviews} reviews)"

    def get_cancellation_display(self):
        if self.cancellation_policy == 'custom':
            return self.cancellation_policy_custom or "Custom policy"
        return self.get_cancellation_policy_display()

    @property
    def meal_types_list(self):
        if not self.meal_types:
            return []
        return [m.strip() for m in self.meal_types.split(',') if m.strip()]

    @property
    def features_list(self):
        if not self.features:
            return []
        return [f.strip() for f in self.features.split(',') if f.strip()]

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'is_available']),
            models.Index(fields=['category']),
            models.Index(fields=['average_rating']),
            models.Index(fields=['listing_type']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=[
                    'submitted', 'under_review', 'approved', 'published',
                    'rejected', 'suspended', 'archived',
                ]),
                name='experience_status_valid',
            ),
            models.CheckConstraint(
                condition=models.Q(listing_type__in=[
                    'food_dining', 'places_to_stay', 'attractions', 'activities',
                ]),
                name='experience_listing_valid',
            ),
            models.CheckConstraint(
                condition=models.Q(price_unit__in=[
                    '', 'per_person', 'per_night', 'per_meal', 'per_group', 'per_hour',
                ]),
                name='experience_price_unit_valid',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(difficulty_level='')
                    | models.Q(difficulty_level__in=['easy', 'moderate', 'challenging'])
                ),
                name='experience_difficulty_valid',
            ),
            models.CheckConstraint(
                condition=models.Q(cancellation_policy__in=[
                    'free_24h', 'free_48h', 'refund_50', 'no_refund', 'custom',
                ]),
                name='experience_cancel_valid',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(min_participants__gte=1)
                    & models.Q(max_capacity__gte=models.F('min_participants'))
                ),
                name='experience_capacity_valid',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(duration_minutes__isnull=True)
                    | models.Q(duration_minutes__gte=1)
                ),
                name='experience_duration_valid',
            ),
            models.CheckConstraint(
                condition=(
                    (models.Q(price_range_min__isnull=True) | models.Q(price_range_min__gte=0))
                    & (models.Q(price_range_max__isnull=True) | models.Q(price_range_max__gte=0))
                ),
                name='experience_price_nonnegative',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(price_range_min__isnull=True)
                    | models.Q(price_range_max__isnull=True)
                    | models.Q(price_range_min__lte=models.F('price_range_max'))
                ),
                name='experience_price_order',
            ),
            models.CheckConstraint(
                condition=(models.Q(latitude__isnull=True) | models.Q(latitude__range=(-90, 90))),
                name='experience_latitude_valid',
            ),
            models.CheckConstraint(
                condition=(models.Q(longitude__isnull=True) | models.Q(longitude__range=(-180, 180))),
                name='experience_longitude_valid',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(average_rating__gte=0)
                    & models.Q(average_rating__lte=5)
                    & models.Q(total_reviews__gte=0)
                ),
                name='experience_rating_valid',
            ),
        ]


class Availability(models.Model):
    experience = models.ForeignKey(
        Experience,
        on_delete=models.CASCADE,
        related_name='availability_slots'
    )
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    max_capacity = models.IntegerField()
    booked_count = models.IntegerField(default=0)
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.experience.name} - {self.date} {self.start_time}"

    def remaining_capacity(self):
        return self.max_capacity - self.booked_count

    def is_full(self):
        return self.booked_count >= self.max_capacity

    class Meta:
        unique_together = ['experience', 'date', 'start_time']
        ordering = ['date', 'start_time']
        indexes = [
            models.Index(fields=['date', 'is_available']),
            models.Index(fields=['experience', 'date']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(max_capacity__gte=1)
                    & models.Q(booked_count__gte=0)
                    & models.Q(booked_count__lte=models.F('max_capacity'))
                ),
                name='availability_capacity_valid',
            ),
            models.CheckConstraint(
                condition=models.Q(end_time__gt=models.F('start_time')),
                name='availability_time_valid',
            ),
        ]