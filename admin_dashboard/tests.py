from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from accounts.models import Profile
from notifications.models import Notification
from notifications.utils import get_unread_count_for_user
from .models import AdminAction


class DirectDatabaseUserDeleteAuditTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        migration = import_module(
            'admin_dashboard.migrations.0005_database_user_delete_audit'
        )
        migration.install_user_delete_trigger(
            apps,
            SimpleNamespace(connection=connection),
        )

    def test_sql_delete_creates_admin_audit_entry_and_notification(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                "AND name = 'audit_auth_user_delete'"
            )
            self.assertIsNotNone(cursor.fetchone(), 'Delete audit trigger was not installed')

        admin_user = User.objects.create_user(
            username='audit-admin@example.com',
            email='audit-admin@example.com',
            password='ValidPassword1',
        )
        Profile.objects.create(user=admin_user, role='admin')
        deleted_user = User.objects.create_user(
            username='db-delete-test@example.com',
            email='db-delete-test@example.com',
            password='ValidPassword1',
        )
        deleted_user_id = deleted_user.pk

        with connection.cursor() as cursor:
            cursor.execute(
                'DELETE FROM auth_user WHERE id = %s',
                [deleted_user_id],
            )

        audit_entry = AdminAction.objects.get(
            action_type='delete_user',
            entity_id=deleted_user_id,
        )
        self.assertIsNone(audit_entry.admin)
        self.assertIn('db-delete-test@example.com', audit_entry.entity_name)
        self.assertIn('cannot identify', audit_entry.description)
        self.assertFalse(audit_entry.metadata['actor_identifiable'])

        notification = Notification.objects.get(
            recipient=admin_user,
            notification_type='security_alert',
            entity_id=deleted_user_id,
        )
        self.assertIn('db-delete-test@example.com', notification.message)
        self.assertEqual(
            notification.link,
            '/admin_dashboard/audit-logs/?type=user',
        )
        self.assertEqual(get_unread_count_for_user(admin_user), 1)

        self.client.force_login(admin_user)
        audit_response = self.client.get(
            reverse('admin_dashboard:audit_logs'),
            {'type': 'user'},
        )
        notification_response = self.client.get(
            reverse('notifications:my_notifications'),
        )

        self.assertEqual(audit_response.status_code, 200)
        self.assertContains(audit_response, 'Deleted User from Database')
        self.assertContains(audit_response, 'Database change (actor not identified)')
        self.assertContains(audit_response, 'db-delete-test@example.com')
        self.assertEqual(notification_response.status_code, 200)
        self.assertContains(notification_response, 'Database user deleted')
