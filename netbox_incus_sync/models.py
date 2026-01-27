from django.db import models
from django.urls import reverse
from netbox.models import NetBoxModel


class IncusHost(NetBoxModel):
    """
    Modèle représentant un hôte Incus à synchroniser avec NetBox.
    """
    name = models.CharField(
        max_length=100, 
        unique=True,
        verbose_name='Nom'
    )
    
    socket_path = models.CharField(
        max_length=255, 
        default='http+unix://%2Fvar%2Flib%2Fincus%2Funix.socket',
        verbose_name='Chemin du socket',
        help_text="Format requis : http+unix://%2Fchemin%2Fvers%2Fsocket"
    )
    
    enabled = models.BooleanField(
        default=True,
        verbose_name='Activé'
    )
    
    default_cluster = models.ForeignKey(
        to='virtualization.Cluster',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='incus_hosts',
        verbose_name='Cluster par défaut'
    )
    
    comments = models.TextField(
        blank=True,
        verbose_name='Commentaires'
    )

    class Meta:
        ordering = ('name',)
        verbose_name = 'Hôte Incus'
        verbose_name_plural = 'Hôtes Incus'

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        """URL de la vue détail - OBLIGATOIRE pour NetBox."""
        return reverse('plugins:netbox_incus_sync:incushost', args=[self.pk])