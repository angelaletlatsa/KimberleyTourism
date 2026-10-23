from django.db import models
from django.utils import timezone
from tourist.models import TouristProfile


class Itinerary(models.Model):
    visitor = models.ForeignKey(
        TouristProfile,
        on_delete=models.CASCADE,
        related_name='itineraries'
    )
    name = models.CharField(max_length=100, default="My Kimberley Trip")
    start_date = models.DateField()
    end_date = models.DateField()
    number_of_travellers = models.PositiveIntegerField(
        default=1,
        help_text="How many people are travelling (used for cost estimation)"
    )
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.visitor.user.first_name}'s Itinerary - {self.name}"

    # ============ COST (RANGES, NOT FAKE POINTS) ============

    def total_cost_range(self):
        """
        Return (low, high) totals in Rands.

        For each experience in the itinerary:
          - low  uses exp.price_range_min (or 0 if only max was set)
          - high uses exp.price_range_max (or min if only min was set)

        Multiplies both by number_of_travellers.

        Skips experiences with no price info.
        Returns (0, 0) if no priced items.
        """
        low_total = 0
        high_total = 0
        has_any_priced = False

        for item in self.items.select_related('experience').all():
            exp = item.experience
            if not exp.has_price_info:
                continue
            has_any_priced = True

            # Low end — if only max is set, use max as the low
            low = exp.price_range_min if exp.price_range_min is not None else exp.price_range_max
            # High end — if only min is set, use min as the high
            high = exp.price_range_max if exp.price_range_max is not None else exp.price_range_min

            if low is None or high is None:
                # Safety net — should not happen given has_price_info check
                continue

            low_total += low * self.number_of_travellers
            high_total += high * self.number_of_travellers

        if not has_any_priced:
            return (0, 0)

        return (low_total, high_total)

    @property
    def cost_range_display(self):
        """
        Human-readable range, e.g. 'R450 – R900'.
        Returns 'No estimated cost' if no priced items.
        """
        low, high = self.total_cost_range()
        if low == 0 and high == 0:
            return 'No estimated cost'
        if low == high:
            return f'R{low:,}'
        return f'R{low:,} – R{high:,}'

    @property
    def has_any_priced_item(self):
        """True if at least one item has a provider-entered price."""
        for item in self.items.select_related('experience').all():
            if item.experience.has_price_info:
                return True
        return False

    def total_duration(self):
        """Return total duration in minutes across all items."""
        total = 0
        for item in self.items.all():
            total += item.experience.duration_minutes or 0
        return total

    def has_conflicts(self):
        """Check if any items overlap in time on the same day."""
        items = list(self.items.order_by('date', 'time'))
        for i in range(len(items) - 1):
            current = items[i]
            next_item = items[i + 1]
            if current.date == next_item.date:
                duration = current.experience.duration_minutes or 0
                current_end = timezone.datetime.combine(
                    current.date, current.time
                ) + timezone.timedelta(minutes=duration)
                next_start = timezone.datetime.combine(next_item.date, next_item.time)
                if current_end > next_start:
                    return True
        return False

    def is_within_dates(self, check_date):
        """True if the given date falls within this itinerary's range."""
        return self.start_date <= check_date <= self.end_date

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['visitor', 'is_active']),
            models.Index(fields=['start_date', 'end_date']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(start_date__lte=models.F('end_date')),
                name='itinerary_date_order_valid',
            ),
            models.CheckConstraint(
                condition=models.Q(number_of_travellers__gte=1),
                name='itinerary_travellers_valid',
            ),
        ]


class ItineraryItem(models.Model):
    itinerary = models.ForeignKey(
        Itinerary,
        on_delete=models.CASCADE,
        related_name='items'
    )
    experience = models.ForeignKey(
        'experiences.Experience',
        on_delete=models.CASCADE,
        related_name='itinerary_items'
    )
    date = models.DateField()
    time = models.TimeField()
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.itinerary.name} - {self.experience.name} ({self.date})"

    class Meta:
        ordering = ['date', 'time']
        unique_together = ['itinerary', 'experience', 'date']


class Budget(models.Model):
    visitor = models.OneToOneField(
        'tourist.TouristProfile',
        on_delete=models.CASCADE,
        related_name='budget'
    )
    total_budget = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    planned_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    remaining_budget = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default='ZAR')
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(total_budget__gte=0)
                    & models.Q(planned_cost__gte=0)
                ),
                name='budget_amounts_nonnegative',
            ),
        ]

    def __str__(self):
        return f"{self.visitor.user.first_name}'s Budget"

    def calculate_remaining(self):
        self.remaining_budget = self.total_budget - self.planned_cost
        self.save()
        return self.remaining_budget

    def can_add_experience(self, cost):
        return (self.remaining_budget - cost) >= 0

    def get_warning_message(self, cost):
        if not self.can_add_experience(cost):
            overspend = abs(self.remaining_budget - cost)
            return f"⚠️ Adding this experience will exceed your planned budget by R{overspend:.2f}"
        return None