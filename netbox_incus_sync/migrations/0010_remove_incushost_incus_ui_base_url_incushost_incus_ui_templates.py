from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_incus_sync", "0009_incushost_sync_interval"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="incushost",
            name="incus_ui_base_url",
        ),
        migrations.AddField(
            model_name="incushost",
            name="incus_ui_templates",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    "Custom URL templates for linking to the Incus web UI. "
                    "JSON dict with keys: instance, profile, network, storage_pool, "
                    "storage_volume, project. "
                    "Use placeholders: {host}, {project}, {name}, {pool}. "
                    "Leave empty to use defaults. "
                    'Example: {"instance": "{host}/ui/project/{project}/instance/{name}"}'
                ),
                verbose_name="Incus UI URL Templates",
            ),
        ),
    ]
