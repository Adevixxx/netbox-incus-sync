import django_tables2 as tables
from netbox.tables import NetBoxTable, ChoiceFieldColumn, ToggleColumn
from .models import IncusHost


class IncusHostTable(NetBoxTable):
    """Table for displaying Incus hosts."""

    pk = ToggleColumn()

    name = tables.Column(
        linkify=True,
        verbose_name='Name'
    )

    connection_type = ChoiceFieldColumn(
        verbose_name='Type'
    )

    connection_info = tables.Column(
        accessor='connection_url',
        verbose_name='Connection',
        orderable=False
    )

    enabled = tables.BooleanColumn(
        verbose_name='Enabled'
    )

    default_cluster = tables.Column(
        linkify=True,
        verbose_name='Cluster'
    )

    class Meta(NetBoxTable.Meta):
        model = IncusHost
        fields = (
            'pk',
            'name',
            'connection_type',
            'connection_info',
            'enabled',
            'default_cluster',
            'tags',
        )
        default_columns = (
            'pk',
            'name',
            'connection_type',
            'connection_info',
            'enabled',
            'default_cluster',
        )