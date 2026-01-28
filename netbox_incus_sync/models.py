from django.db import models
from django.urls import reverse
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError
from netbox.models import NetBoxModel
import os


class ConnectionTypeChoices(models.TextChoices):
    UNIX_SOCKET = 'unix', 'Socket Unix'
    HTTPS = 'https', 'HTTPS (certificat TLS)'


def validate_file_exists(path):
    """Valide que le fichier existe et est lisible."""
    if path and not os.path.isfile(path):
        raise ValidationError(f"Le fichier n'existe pas : {path}")
    if path and not os.access(path, os.R_OK):
        raise ValidationError(f"Le fichier n'est pas lisible : {path}")


def validate_file_permissions(path):
    """Valide que le fichier a des permissions sécurisées (600 ou 400)."""
    if not path or not os.path.isfile(path):
        return
    mode = os.stat(path).st_mode & 0o777
    if mode not in (0o600, 0o400, 0o640, 0o440):
        raise ValidationError(
            f"Permissions du fichier trop permissives ({oct(mode)}). "
            f"Utilisez chmod 600 {path}"
        )


class IncusHost(NetBoxModel):
    """
    Modèle représentant un hôte Incus à synchroniser avec NetBox.
    
    Sécurité des certificats :
    - Les certificats sont stockés comme FICHIERS sur le serveur, pas dans la DB
    - Seuls les chemins sont stockés dans la base de données
    - Les fichiers doivent avoir des permissions restrictives (600)
    """
    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name='Nom'
    )

    connection_type = models.CharField(
        max_length=10,
        choices=ConnectionTypeChoices.choices,
        default=ConnectionTypeChoices.UNIX_SOCKET,
        verbose_name='Type de connexion'
    )

    # ========== Connexion Unix Socket ==========
    socket_path = models.CharField(
        max_length=255,
        default='http+unix://%2Fvar%2Flib%2Fincus%2Funix.socket',
        blank=True,
        verbose_name='Chemin du socket',
        help_text="Format: http+unix://%2Fvar%2Flib%2Fincus%2Funix.socket"
    )

    # ========== Connexion HTTPS ==========
    https_url = models.URLField(
        max_length=255,
        blank=True,
        verbose_name='URL HTTPS',
        help_text="Ex: https://incus.example.com:8443"
    )

    # Chemins vers les fichiers de certificats (PAS le contenu!)
    client_cert_path = models.CharField(
        max_length=500,
        blank=True,
        verbose_name='Chemin du certificat client',
        help_text="Chemin absolu vers le fichier .crt (ex: /etc/netbox/incus/client.crt)",
        validators=[validate_file_exists]
    )

    client_key_path = models.CharField(
        max_length=500,
        blank=True,
        verbose_name='Chemin de la clé privée',
        help_text="Chemin absolu vers le fichier .key (ex: /etc/netbox/incus/client.key)",
        validators=[validate_file_exists]
    )

    ca_cert_path = models.CharField(
        max_length=500,
        blank=True,
        verbose_name='Chemin du certificat CA (optionnel)',
        help_text="Pour valider le certificat du serveur Incus",
        validators=[validate_file_exists]
    )

    verify_ssl = models.BooleanField(
        default=True,
        verbose_name='Vérifier le certificat SSL',
        help_text="Décocher uniquement pour les environnements de test"
    )

    # ========== Configuration générale ==========
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

    class Meta:
        ordering = ('name',)
        verbose_name = 'Hôte Incus'
        verbose_name_plural = 'Hôtes Incus'

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('plugins:netbox_incus_sync:incushost', args=[self.pk])

    @property
    def connection_url(self):
        """Retourne l'URL de connexion selon le type."""
        if self.connection_type == ConnectionTypeChoices.HTTPS:
            return self.https_url
        return self.socket_path

    def clean(self):
        """Validation du modèle."""
        super().clean()
        
        if self.connection_type == ConnectionTypeChoices.UNIX_SOCKET:
            if not self.socket_path:
                raise ValidationError({
                    'socket_path': "Le chemin du socket est requis."
                })
                
        elif self.connection_type == ConnectionTypeChoices.HTTPS:
            if not self.https_url:
                raise ValidationError({
                    'https_url': "L'URL HTTPS est requise."
                })
            if not self.client_cert_path:
                raise ValidationError({
                    'client_cert_path': "Le chemin du certificat client est requis."
                })
            if not self.client_key_path:
                raise ValidationError({
                    'client_key_path': "Le chemin de la clé privée est requis."
                })
            
            # Vérifier les permissions des fichiers sensibles
            for path_field in ['client_key_path']:
                path = getattr(self, path_field)
                if path:
                    try:
                        validate_file_permissions(path)
                    except ValidationError as e:
                        raise ValidationError({path_field: e.message})

    def check_certificates(self):
        """
        Vérifie que les certificats sont accessibles et valides.
        Retourne (success, message).
        """
        if self.connection_type != ConnectionTypeChoices.HTTPS:
            return True, "Connexion Unix socket (pas de certificats)"
        
        errors = []
        
        for field, label in [
            ('client_cert_path', 'Certificat client'),
            ('client_key_path', 'Clé privée'),
        ]:
            path = getattr(self, field)
            if not path:
                errors.append(f"{label}: chemin non défini")
            elif not os.path.isfile(path):
                errors.append(f"{label}: fichier introuvable ({path})")
            elif not os.access(path, os.R_OK):
                errors.append(f"{label}: fichier non lisible ({path})")
        
        if errors:
            return False, "; ".join(errors)
        return True, "Certificats OK"