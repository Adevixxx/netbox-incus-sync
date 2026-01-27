import django_tables2 as tables
from netbox.tables import NetBoxTable, ChoiceFieldColumn, ToggleColumn
from .models import IncusHost


class IncusHostTable(NetBoxTable):
    """Table d'affichage des hôtes Incus."""
    
    pk = ToggleColumn()
    
    name = tables.Column(
        linkify=True,
        verbose_name='Nom'
    )
    
    socket_path = tables.Column(
        verbose_name='Chemin du socket'
    )
    
    enabled = tables.BooleanColumn(
        verbose_name='Activé'
    )
    
    default_cluster = tables.Column(
        linkify=True,
        verbose_name='Cluster par défaut'
    )

    class Meta(NetBoxTable.Meta):
        model = IncusHost
        fields = (
            'pk',
            'name',
            'socket_path',
            'enabled',
            'default_cluster',
            'tags',
        )
        default_columns = (
            'pk',
            'name',
            'socket_path',
            'enabled',
            'default_cluster',
        )