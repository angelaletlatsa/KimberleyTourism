from django.db import migrations


PROVIDER_COLUMNS = (
    "id, business_name, business_description, business_category, phone, email, "
    "website, social_links, address, city, province, postal_code, operating_hours, "
    "established_year, verification_status, verified_at, rejection_reason, logo, "
    "cover_image, total_experiences, total_bookings, total_reviews, average_rating, "
    "created_at, updated_at, profile_id, verified_by_id"
)
LEGACY_PROVIDER_COLUMNS = PROVIDER_COLUMNS.replace(
    "rejection_reason", "'' AS rejection_reason"
)


def copy_legacy_provider_data(apps, schema_editor):
    connection = schema_editor.connection
    tables = set(connection.introspection.table_names())
    if "providers_providerprofile" not in tables or "provider_providerprofile" not in tables:
        return

    schema_editor.execute(
        f"INSERT OR IGNORE INTO provider_providerprofile ({PROVIDER_COLUMNS}) "
        f"SELECT {LEGACY_PROVIDER_COLUMNS} "
        "FROM providers_providerprofile"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("provider", "0002_repair_provider_schema"),
    ]

    operations = [
        migrations.RunPython(copy_legacy_provider_data, migrations.RunPython.noop),
    ]
