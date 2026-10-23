from django.db import migrations


def repair_provider_schema(apps, schema_editor):
    connection = schema_editor.connection
    existing_tables = set(connection.introspection.table_names())

    if "providers_providerprofile" in existing_tables and "provider_providerprofile" not in existing_tables:
        schema_editor.execute(
            "ALTER TABLE providers_providerprofile RENAME TO provider_providerprofile"
        )
        existing_tables.remove("providers_providerprofile")
        existing_tables.add("provider_providerprofile")

    if "provider_providerprofile" not in existing_tables:
        return

    columns = {
        column.name
        for column in connection.introspection.get_table_description(
            connection.cursor(), "provider_providerprofile"
        )
    }
    if "rejection_reason" not in columns:
        schema_editor.execute(
            "ALTER TABLE provider_providerprofile "
            "ADD COLUMN rejection_reason TEXT NOT NULL DEFAULT ''"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("provider", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(repair_provider_schema, migrations.RunPython.noop),
    ]
