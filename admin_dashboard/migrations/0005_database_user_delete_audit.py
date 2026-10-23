from django.db import migrations, models


def install_user_delete_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != 'sqlite':
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS audit_auth_user_delete
            AFTER DELETE ON auth_user
            BEGIN
                INSERT INTO admin_dashboard_adminaction (
                    admin_id,
                    action_type,
                    entity_type,
                    entity_id,
                    entity_name,
                    description,
                    metadata,
                    ip_address,
                    created_at
                )
                VALUES (
                    NULL,
                    'delete_user',
                    'User',
                    OLD.id,
                    COALESCE(OLD.username, '') || ' (' || COALESCE(OLD.email, '') || ')',
                    'A user row was deleted directly from the database. SQLite cannot identify the person or tool that performed this change.',
                    '{"source":"sqlite_delete_trigger","actor_identifiable":false}',
                    NULL,
                    CURRENT_TIMESTAMP
                );

                INSERT INTO notifications_notification (
                    recipient_id,
                    notification_type,
                    title,
                    message,
                    link,
                    entity_type,
                    entity_id,
                    is_read,
                    read_at,
                    email_sent,
                    email_sent_at,
                    created_at,
                    updated_at
                )
                SELECT
                    admin_user.id,
                    'security_alert',
                    'Database user deleted',
                    'A database user row was deleted: ' ||
                        COALESCE(OLD.username, '') || ' (' || COALESCE(OLD.email, '') ||
                        '). The database cannot identify who performed this action.',
                    '/admin_dashboard/audit-logs/?type=user',
                    'User',
                    OLD.id,
                    0,
                    NULL,
                    0,
                    NULL,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                FROM auth_user AS admin_user
                INNER JOIN accounts_profile AS admin_profile
                    ON admin_profile.user_id = admin_user.id
                WHERE admin_profile.role = 'admin'
                    AND admin_user.is_active = 1;
            END
        """)


def remove_user_delete_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != 'sqlite':
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP TRIGGER IF EXISTS audit_auth_user_delete")


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_profile_is_suspended_profile_suspended_at_and_more'),
        ('admin_dashboard', '0002_reportedcontent_systemsetting'),
        ('notifications', '0002_alter_notification_notification_type'),
    ]

    operations = [
        migrations.AlterField(
            model_name='adminaction',
            name='action_type',
            field=models.CharField(
                choices=[
                    ('approve_provider', 'Approved Provider'),
                    ('reject_provider', 'Rejected Provider'),
                    ('suspend_provider', 'Suspended Provider'),
                    ('approve_guide', 'Approved Guide'),
                    ('reject_guide', 'Rejected Guide'),
                    ('suspend_guide', 'Suspended Guide'),
                    ('approve_experience', 'Approved Experience'),
                    ('reject_experience', 'Rejected Experience'),
                    ('suspend_experience', 'Suspended Experience'),
                    ('approve_review', 'Approved Review'),
                    ('reject_review', 'Rejected Review'),
                    ('suspend_user', 'Suspended User'),
                    ('activate_user', 'Activated User'),
                    ('deactivate_user', 'Deactivated User'),
                    ('delete_user', 'Deleted User from Database'),
                    ('delete_review', 'Deleted Review'),
                    ('other', 'Other Action'),
                ],
                max_length=50,
            ),
        ),
        migrations.RunPython(
            install_user_delete_trigger,
            reverse_code=remove_user_delete_trigger,
        ),
    ]
