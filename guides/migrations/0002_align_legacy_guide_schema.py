from django.db import migrations


def align_legacy_schema(apps, schema_editor):
    connection = schema_editor.connection
    table_name = 'guides_guideprofile'
    with connection.cursor() as cursor:
        columns = {
            column.name
            for column in connection.introspection.get_table_description(cursor, table_name)
        }

        columns_to_add = {
            'profile_id': 'integer',
            'biography': "text NOT NULL DEFAULT ''",
            'years_experience': 'integer NOT NULL DEFAULT 0',
            'languages': "text NOT NULL DEFAULT '[]'",
            'specializations': "text NOT NULL DEFAULT '[]'",
            'areas_of_expertise': "text NOT NULL DEFAULT '[]'",
            'qualifications': "text NOT NULL DEFAULT '[]'",
            'availability_schedule': "text NOT NULL DEFAULT '{}'",
            'average_rating': 'decimal NOT NULL DEFAULT 0',
            'total_reviews': 'integer NOT NULL DEFAULT 0',
            'total_tours_given': 'integer NOT NULL DEFAULT 0',
            'verification_status': "varchar(20) NOT NULL DEFAULT 'pending'",
            'verified_at': 'datetime',
            'verified_by_id': 'integer',
            'id_document': 'varchar(100)',
            'certification_document': 'varchar(100)',
        }
        for column_name, definition in columns_to_add.items():
            if column_name not in columns:
                cursor.execute(
                    f'ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}'
                )
        columns.update(columns_to_add)

        if 'user_id' in columns and 'profile_id' in columns and 'accounts_profile' in connection.introspection.table_names():
            cursor.execute(
                'UPDATE guides_guideprofile SET profile_id = '
                '(SELECT id FROM accounts_profile WHERE accounts_profile.user_id = guides_guideprofile.user_id) '
                'WHERE profile_id IS NULL'
            )
        if 'bio' in columns:
            cursor.execute(
                "UPDATE guides_guideprofile SET biography = bio "
                "WHERE biography = '' AND bio IS NOT NULL"
            )
        if 'experience' in columns:
            cursor.execute(
                'UPDATE guides_guideprofile SET years_experience = experience '
                'WHERE years_experience = 0 AND experience IS NOT NULL'
            )
        if 'is_approved' in columns:
            cursor.execute(
                "UPDATE guides_guideprofile SET verification_status = 'approved' "
                'WHERE is_approved = 1'
            )
        cursor.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS guides_guideprofile_profile_id_unique '
            'ON guides_guideprofile(profile_id)'
        )


class Migration(migrations.Migration):
    dependencies = [
        ('guides', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(
            code=align_legacy_schema,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
