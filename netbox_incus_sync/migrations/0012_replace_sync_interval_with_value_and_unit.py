from django.db import migrations, models


def convert_sync_interval_forward(apps, schema_editor):
    """Convert old sync_interval (minutes) to value + unit."""
    IncusHost = apps.get_model("netbox_incus_sync", "IncusHost")
    for host in IncusHost.objects.exclude(sync_interval__isnull=True):
        old = host.sync_interval
        if old % 1440 == 0 and old >= 1440:
            host.sync_interval_value = old // 1440
            host.sync_interval_unit = "days"
        elif old % 60 == 0 and old >= 60:
            host.sync_interval_value = old // 60
            host.sync_interval_unit = "hours"
        else:
            host.sync_interval_value = old
            host.sync_interval_unit = "minutes"
        host.save(update_fields=["sync_interval_value", "sync_interval_unit"])


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_incus_sync", "0011_remove_incushost_incus_ui_templates_and_add_url_fields"),
    ]

    operations = [
        # Add new fields first (before removing old one, so data migration can read both)
        migrations.AddField(
            model_name="incushost",
            name="sync_interval_value",
            field=models.PositiveSmallIntegerField(
                blank=True, null=True,
                verbose_name="Sync Interval",
                help_text="How often to automatically synchronize this host. Leave blank to disable.",
            ),
        ),
        migrations.AddField(
            model_name="incushost",
            name="sync_interval_unit",
            field=models.CharField(
                blank=True, max_length=10, null=True,
                verbose_name="Interval Unit",
            ),
        ),
        # Convert data
        migrations.RunPython(convert_sync_interval_forward, migrations.RunPython.noop),
        # Remove old field
        migrations.RemoveField(
            model_name="incushost",
            name="sync_interval",
        ),
    ]
