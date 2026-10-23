from django.db import models
from accounts.models import Profile


class TouristProfile(models.Model):
    profile = models.OneToOneField(
        Profile,
        on_delete=models.CASCADE,
        related_name='tourist_profile'
    )

    # Personal Information
    date_of_birth = models.DateField(null=True, blank=True)
    nationality = models.CharField(max_length=100, blank=True)
    preferred_language = models.CharField(max_length=50, default='English')

    # Preferences
    interests = models.JSONField(default=list, blank=True)
    preferred_currency = models.CharField(max_length=3, default='ZAR')

    # Location
    city = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, default='South Africa')

    # Stats (calculated)
    total_bookings = models.IntegerField(default=0)
    total_reviews = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(total_bookings__gte=0)
                    & models.Q(total_reviews__gte=0)
                ),
                name='tourist_stats_nonnegative',
            ),
        ]

    def __str__(self):
        return f"Tourist: {self.profile.user.first_name}"

    @property
    def user(self):
        return self.profile.user
class SavedExperience(models.Model):
    visitor = models.ForeignKey(
        TouristProfile,
        on_delete=models.CASCADE,
        related_name='saved_experiences'
    )
    experience = models.ForeignKey(
        'experiences.Experience',
        on_delete=models.CASCADE,
        related_name='saved_by'
    )
    saved_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = ['visitor', 'experience']
        ordering = ['-saved_at']

    def __str__(self):
        return f"{self.visitor.user.first_name} saved {self.experience.name}"
