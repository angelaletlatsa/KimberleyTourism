from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from accounts.models import AdminInvite, Profile
from admin_dashboard.models import AdminAction


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='noreply@example.com',
    SITE_URL='https://example.com',
    OWNER_EMAIL_HOST='smtp.gmail.com',
    OWNER_EMAIL_PORT=587,
    OWNER_EMAIL_USE_TLS=True,
    OWNER_EMAIL_HOST_USER='owner@example.com',
    OWNER_EMAIL_HOST_PASSWORD='owner-app-password',
)
class OwnerAdminManagementTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_superuser(
            username='owner@example.com',
            email='owner@example.com',
            password='Owner-password-928!',
        )
        Profile.objects.create(user=self.owner, role='admin')
        self.client.force_login(self.owner)

    def test_owner_can_open_admin_management_page(self):
        response = self.client.get(reverse('admin_dashboard:admin_management'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Administrators')

    def test_owner_actions_use_app_confirmation_dialog(self):
        response = self.client.get(reverse('admin_dashboard:admin_management'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<dialog id="appConfirmDialog"', html=False)
        self.assertContains(response, 'data-app-confirm', html=False)
        self.assertNotContains(response, 'onsubmit="return confirm(')

    def test_user_detail_actions_use_app_confirmation_dialog(self):
        target = User.objects.create_user(
            username='existing-user@example.com',
            email='existing-user@example.com',
            password='Existing-password-928!',
        )
        profile = Profile.objects.create(user=target, role='admin')

        response = self.client.get(
            reverse('admin_dashboard:user_detail', kwargs={'user_id': profile.id})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<dialog id="appConfirmDialog"', html=False)
        self.assertContains(response, 'data-app-confirm', html=False)
        self.assertNotContains(response, 'confirm(')

    def test_owner_dashboard_shows_administrator_management_link(self):
        response = self.client.get(reverse('admin_dashboard:dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="{reverse("admin_dashboard:admin_management")}"',
        )

    def test_owner_administrator_link_stays_in_sidebar_across_admin_pages(self):
        page_names = (
            'all_users',
            'providers',
            'guides',
            'experiences',
            'reviews',
            'bookings',
            'pending_assignments',
            'analytics',
            'audit_logs',
        )

        for page_name in page_names:
            with self.subTest(page=page_name):
                response = self.client.get(
                    reverse(f'admin_dashboard:{page_name}')
                )

                self.assertEqual(response.status_code, 200)
                self.assertContains(
                    response,
                    f'href="{reverse("admin_dashboard:admin_management")}"',
                )

    def test_owner_invites_admin_and_invitation_email_is_sent(self):
        response = self.client.post(
            reverse('admin_dashboard:invite_admin'),
            {'email': 'new-admin@example.com', 'message': 'Welcome'},
        )

        invite = AdminInvite.objects.get(email='new-admin@example.com')
        self.assertRedirects(
            response,
            reverse('admin_dashboard:admin_management'),
        )
        self.assertEqual(invite.status, 'pending')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['new-admin@example.com'])
        self.assertEqual(
            mail.outbox[0].from_email,
            'Explore Kimberley <owner@example.com>',
        )
        self.assertEqual(mail.outbox[0].reply_to, ['owner@example.com'])
        self.assertIn(
            f'/accounts/accept-admin-invite/{invite.token}/',
            mail.outbox[0].body,
        )
        self.assertTrue(
            AdminAction.objects.filter(
                action_type='admin_invite_sent',
                entity_type='AdminInvite',
                entity_id=invite.id,
            ).exists()
        )

    @patch('accounts.utils.get_connection')
    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
    )
    def test_invitation_uses_owner_smtp_credentials(self, get_smtp_connection):
        from django.core.mail.backends.locmem import EmailBackend
        from accounts.utils import send_admin_invite_email

        get_smtp_connection.return_value = EmailBackend()
        invite = AdminInvite.objects.create(
            email='new-admin@example.com',
            invited_by=self.owner,
        )

        send_admin_invite_email(invite)

        get_smtp_connection.assert_called_once_with(
            'django.core.mail.backends.smtp.EmailBackend',
            host='smtp.gmail.com',
            port=587,
            username='owner@example.com',
            password='owner-app-password',
            use_tls=True,
            fail_silently=False,
        )
        self.assertEqual(
            mail.outbox[-1].from_email,
            'Explore Kimberley <owner@example.com>',
        )

    @patch(
        'accounts.utils.send_admin_invite_email',
        side_effect=OSError('SMTP unavailable'),
    )
    def test_email_failure_cancels_invitation_and_reports_failure(self, send_email):
        response = self.client.post(
            reverse('admin_dashboard:invite_admin'),
            {'email': 'failed-admin@example.com'},
            follow=True,
        )

        invite = AdminInvite.objects.get(email='failed-admin@example.com')
        self.assertEqual(invite.status, 'revoked')
        self.assertContains(response, 'The invitation email could not be sent')
        self.assertEqual(send_email.call_count, 1)

    def test_invitee_accepts_invitation_then_can_sign_in_as_admin(self):
        invite = AdminInvite.objects.create(
            email='new-admin@example.com',
            invited_by=self.owner,
        )
        accept_url = reverse(
            'accounts:accept_admin_invite',
            kwargs={'token': invite.token},
        )
        password = 'Unique-admin-password-928!'

        response = self.client.post(
            accept_url,
            {
                'full_name': 'New Administrator',
                'password': password,
                'confirm_password': password,
            },
        )

        invited_user = User.objects.get(username='new-admin@example.com')
        invited_profile = Profile.objects.get(user=invited_user)
        invite.refresh_from_db()

        self.assertRedirects(response, '/accounts/login/?invited=1')
        self.assertEqual(invited_profile.role, 'admin')
        self.assertFalse(invited_user.is_superuser)
        self.assertTrue(invited_user.check_password(password))
        self.assertEqual(invite.status, 'accepted')
        self.assertEqual(invite.accepted_by, invited_user)

        self.client.logout()
        login_response = self.client.post(
            reverse('accounts:login'),
            {'email': invited_user.email, 'password': password},
        )
        self.assertEqual(login_response.status_code, 302)
        self.assertEqual(login_response['Location'], '/admin_dashboard/')
        self.assertEqual(
            self.client.get(reverse('admin_dashboard:dashboard')).status_code,
            200,
        )

    def test_owner_can_revoke_pending_invitation(self):
        invite = AdminInvite.objects.create(
            email='revoke-admin@example.com',
            invited_by=self.owner,
        )

        response = self.client.post(
            reverse(
                'admin_dashboard:revoke_admin_invite',
                kwargs={'invite_id': invite.id},
            )
        )

        invite.refresh_from_db()
        self.assertRedirects(
            response,
            reverse('admin_dashboard:admin_management'),
        )
        self.assertEqual(invite.status, 'revoked')

    def test_owner_can_promote_existing_active_account(self):
        user = User.objects.create_user(
            username='existing-user@example.com',
            email='existing-user@example.com',
            password='Existing-password-928!',
        )
        profile = Profile.objects.create(user=user, role='tourist')

        response = self.client.post(
            reverse(
                'admin_dashboard:promote_admin',
                kwargs={'profile_id': profile.id},
            )
        )

        profile.refresh_from_db()
        self.assertRedirects(
            response,
            reverse('admin_dashboard:user_detail', kwargs={'user_id': profile.id}),
        )
        self.assertEqual(profile.role, 'admin')
        self.assertFalse(user.is_superuser)
        self.assertTrue(
            AdminAction.objects.filter(
                action_type='other',
                entity_type='Profile',
                entity_id=profile.id,
                metadata__event='admin_promoted',
            ).exists()
        )

    def test_owner_can_remove_another_admin_but_not_last_owner(self):
        regular_admin = User.objects.create_user(
            username='admin@example.com',
            email='admin@example.com',
            password='Regular-admin-password-928!',
        )
        admin_profile = Profile.objects.create(user=regular_admin, role='admin')

        response = self.client.post(
            reverse(
                'admin_dashboard:remove_admin',
                kwargs={'profile_id': admin_profile.id},
            )
        )

        admin_profile.refresh_from_db()
        self.assertRedirects(
            response,
            reverse('admin_dashboard:admin_management'),
        )
        self.assertEqual(admin_profile.role, 'tourist')

        self_profile = self.owner.profile
        response = self.client.post(
            reverse(
                'admin_dashboard:remove_admin',
                kwargs={'profile_id': self_profile.id},
            ),
            follow=True,
        )
        self_profile.refresh_from_db()
        self.assertEqual(self_profile.role, 'admin')
        self.assertContains(response, 'You cannot remove your own administrator access.')

    def test_non_owner_administrator_cannot_manage_administrators(self):
        ordinary_admin = User.objects.create_user(
            username='ordinary-admin@example.com',
            email='ordinary-admin@example.com',
            password='Regular-admin-password-928!',
        )
        Profile.objects.create(user=ordinary_admin, role='admin')
        self.client.force_login(ordinary_admin)

        response = self.client.get(
            reverse('admin_dashboard:admin_management'),
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response['Location'],
            reverse('admin_dashboard:dashboard'),
        )

        dashboard_response = self.client.get(
            reverse('admin_dashboard:dashboard'),
        )
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertNotContains(
            dashboard_response,
            reverse('admin_dashboard:admin_management'),
        )
