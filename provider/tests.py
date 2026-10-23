from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Profile
from experiences.models import Experience
from provider.models import ProviderProfile


class ProviderExperienceDeletionTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='experience-provider',
            password='StrongPass123!',
        )
        profile = Profile.objects.create(user=self.user, role='provider')
        self.provider = profile.provider_profile
        self.provider.business_name = 'Test Tourism'
        self.provider.save(update_fields=['business_name'])
        self.client.force_login(self.user)

    def test_provider_can_delete_experience_in_any_status(self):
        for status, _label in Experience.STATUS_CHOICES:
            with self.subTest(status=status):
                experience = Experience.objects.create(
                    provider=self.provider,
                    name=f'{status} experience',
                    description='Test description',
                    location='Kimberley',
                    status=status,
                )

                response = self.client.post(
                    reverse(
                        'provider:delete_experience',
                        args=[experience.id],
                    )
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['success'], True)
                self.assertFalse(
                    Experience.objects.filter(pk=experience.pk).exists()
                )
