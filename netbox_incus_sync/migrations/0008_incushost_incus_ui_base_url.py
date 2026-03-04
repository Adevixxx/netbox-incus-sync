from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_incus_sync", "0007_remove_incushost_https_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="incushost",
            name="incus_ui_base_url",
            field=models.URLField(
                max_length=500,
                blank=True,
                verbose_name="Incus UI Base URL",
                help_text=(
                    "Base URL of the Incus web UI (e.g. https://incus.example.com:8443). "
                    "Used to generate direct links to instances, profiles, networks, etc. "
                    "Leave blank to disable UI links."
                ),
            ),
        ),
    ]
