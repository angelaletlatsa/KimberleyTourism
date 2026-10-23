import re
from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from django.urls import reverse


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class PasswordResetEmailTests(TestCase):
	def test_reset_request_sends_email_for_active_user(self):
		User.objects.create_user(
			username='reset-user@example.com',
			email='reset-user@example.com',
			password='A-valid-test-password-123',
		)

		response = self.client.post(
			reverse('accounts:password_reset'),
			{'email': 'reset-user@example.com'},
		)

		self.assertRedirects(response, reverse('accounts:password_reset_done'))
		self.assertEqual(len(mail.outbox), 1)
		self.assertEqual(mail.outbox[0].to, ['reset-user@example.com'])
		self.assertNotIn('<!DOCTYPE html>', mail.outbox[0].body)
		self.assertEqual(len(mail.outbox[0].alternatives), 1)
		self.assertEqual(mail.outbox[0].alternatives[0].mimetype, 'text/html')
		self.assertIn('<!DOCTYPE html>', mail.outbox[0].alternatives[0].content)


@override_settings(
	EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
	SITE_URL='https://explorekimberley.com',
)
class RegistrationWelcomeEmailTests(TestCase):
	def register_tourist(self):
		return self.client.post(
			reverse('accounts:register'),
			{
				'full_name': 'New Tourist',
				'email': 'new-tourist@example.com',
				'password': 'ValidPassword1',
				'confirm_password': 'ValidPassword1',
				'account_type': 'tourist',
				'terms': 'on',
			},
		)

	def verification_url(self):
		match = re.search(
			r'https://explorekimberley\.com(/accounts/verify-email/[^/\s]+/)',
			mail.outbox[0].body,
		)
		self.assertIsNotNone(match)
		return match.group(1)

	def test_registration_sends_verification_email_and_blocks_login(self):
		response = self.register_tourist()

		self.assertTemplateUsed(response, 'accounts/verification_sent.html')
		user = User.objects.get(username='new-tourist@example.com')
		self.assertTrue(user.check_password('ValidPassword1'))
		self.assertFalse(user.profile.email_verified)
		self.assertFalse(user.is_active)
		self.assertEqual(len(mail.outbox), 1)
		self.assertEqual(mail.outbox[0].to, ['new-tourist@example.com'])
		self.assertIn('/accounts/verify-email/', mail.outbox[0].body)

		login_response = self.client.post(
			reverse('accounts:login'),
			{'email': user.email, 'password': 'ValidPassword1'},
		)
		self.assertContains(login_response, 'Please verify your email address')
		self.assertContains(login_response, reverse('accounts:resend_verification'))
		self.assertNotIn('_auth_user_id', self.client.session)

	def test_email_confirmation_requires_post_and_then_allows_login(self):
		self.register_tourist()
		user = User.objects.get(username='new-tourist@example.com')
		verification_url = self.verification_url()

		get_response = self.client.get(verification_url)
		self.assertTemplateUsed(get_response, 'accounts/verify_email.html')
		user.profile.refresh_from_db()
		self.assertFalse(user.profile.email_verified)

		response = self.client.post(verification_url)
		self.assertContains(response, 'Your email is verified')
		user.profile.refresh_from_db()
		self.assertTrue(user.profile.email_verified)
		self.assertIsNotNone(user.profile.email_verified_at)
		user.refresh_from_db()
		self.assertTrue(user.is_active)
		self.assertEqual(len(mail.outbox), 2)
		self.assertEqual(mail.outbox[1].subject, 'Welcome to Explore Kimberley, New Tourist!')

		login_response = self.client.post(
			reverse('accounts:login'),
			{'email': user.email, 'password': 'ValidPassword1'},
		)
		self.assertRedirects(login_response, '/tourist/dashboard/')

	def test_invalid_confirmation_token_does_not_verify_account(self):
		self.register_tourist()
		user = User.objects.get(username='new-tourist@example.com')

		response = self.client.post(reverse(
			'accounts:verify_email',
			kwargs={'token': 'invalid-token'},
		))

		self.assertContains(response, 'Confirmation link invalid or expired')
		user.profile.refresh_from_db()
		self.assertFalse(user.profile.email_verified)

	def test_expired_confirmation_token_does_not_verify_account(self):
		self.register_tourist()
		user = User.objects.get(username='new-tourist@example.com')
		verification_url = self.verification_url()

		with override_settings(EMAIL_VERIFICATION_MAX_AGE=-1):
			response = self.client.post(verification_url)

		self.assertContains(response, 'Confirmation link invalid or expired')
		user.refresh_from_db()
		self.assertFalse(user.profile.email_verified)
		self.assertFalse(user.is_active)

	def test_resend_endpoint_does_not_disclose_unknown_email(self):
		response = self.client.post(
			reverse('accounts:resend_verification'),
			{'email': 'unknown@example.com'},
		)

		self.assertContains(response, 'If an unverified account matches')
		self.assertEqual(len(mail.outbox), 0)

	def test_resend_endpoint_limits_repeated_requests(self):
		self.register_tourist()
		response = self.client.post(
			reverse('accounts:resend_verification'),
			{'email': 'new-tourist@example.com'},
		)
		self.assertContains(response, 'limited to one per minute')
		self.assertEqual(len(mail.outbox), 1)

		profile = User.objects.get(username='new-tourist@example.com').profile
		profile.email_verification_sent_at = timezone.now() - timedelta(minutes=2)
		profile.save(update_fields=['email_verification_sent_at'])
		self.client.post(
			reverse('accounts:resend_verification'),
			{'email': 'new-tourist@example.com'},
		)
		self.assertEqual(len(mail.outbox), 2)
