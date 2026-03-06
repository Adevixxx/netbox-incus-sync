from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_incus_sync", "0010_remove_incushost_incus_ui_base_url_incushost_incus_ui_templates"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="incushost",
            name="incus_ui_templates",
        ),
        migrations.AddField(
            model_name="incushost",
            name="incus_ui_instance_url",
            field=models.CharField(
                blank=True, help_text="Placeholders: {host}, {project}, {name}",
                max_length=500, verbose_name="Instance URL Template",
            ),
        ),
        migrations.AddField(
            model_name="incushost",
            name="incus_ui_profile_url",
            field=models.CharField(
                blank=True, help_text="Placeholders: {host}, {project}, {name}",
                max_length=500, verbose_name="Profile URL Template",
            ),
        ),
        migrations.AddField(
            model_name="incushost",
            name="incus_ui_network_url",
            field=models.CharField(
                blank=True, help_text="Placeholders: {host}, {project}, {name}",
                max_length=500, verbose_name="Network URL Template",
            ),
        ),
        migrations.AddField(
            model_name="incushost",
            name="incus_ui_storage_pool_url",
            field=models.CharField(
                blank=True, help_text="Placeholders: {host}, {project}, {name}",
                max_length=500, verbose_name="Storage Pool URL Template",
            ),
        ),
        migrations.AddField(
            model_name="incushost",
            name="incus_ui_storage_volume_url",
            field=models.CharField(
                blank=True, help_text="Placeholders: {host}, {project}, {pool}, {name}",
                max_length=500, verbose_name="Storage Volume URL Template",
            ),
        ),
        migrations.AddField(
            model_name="incushost",
            name="incus_ui_project_url",
            field=models.CharField(
                blank=True, help_text="Placeholders: {host}, {name}",
                max_length=500, verbose_name="Project URL Template",
            ),
        ),
    ]
