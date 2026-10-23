from django.db.models.signals import post_save
from django.dispatch import receiver
from accounts.models import Profile
from .models import ProviderProfile


@receiver(post_save, sender=Profile)
def create_provider_profile(sender, instance, created, **kwargs):
    """Auto-create ProviderProfile when a provider profile is created"""
    if created and instance.role == 'provider':
        ProviderProfile.objects.create(
            profile=instance,
            business_name=f"{instance.user.first_name}'s Business"
        )


@receiver(post_save, sender=Profile)
def save_provider_profile(sender, instance, **kwargs):
    """Save ProviderProfile when profile is saved"""
    if instance.role == 'provider':
        try:
            instance.provider_profile.save()
        except ProviderProfile.DoesNotExist:
            ProviderProfile.objects.create(
                profile=instance,
                business_name=f"{instance.user.first_name}'s Business"
            )