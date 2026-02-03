from django.db import models
from django.urls import reverse
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError
from netbox.models import NetBoxModel
import os


class ConnectionTypeChoices(models.TextChoices):
    UNIX_SOCKET = 'unix', 'Unix Socket'
    HTTPS = 'https', 'HTTPS (TLS certificate)'


def validate_file_exists(path):
    """Validates that the file exists and is readable."""
    if path and not os.path.isfile(path):
        raise ValidationError(f"File does not exist: {path}")
    if path and not os.access(path, os.R_OK):
        raise ValidationError(f"File is not readable: {path}")


def validate_file_permissions(path):
    """Validates that the file has secure permissions (600 or 400)."""
    if not path or not os.path.isfile(path):
        return
    mode = os.stat(path).st_mode & 0o777
    if mode not in (0o600, 0o400, 0o640, 0o440):
        raise ValidationError(
            f"File permissions too permissive ({oct(mode)}). "
            f"Use chmod 600 {path}"
        )


class IncusHost(NetBoxModel):
    """
    Model representing an Incus host to synchronize with NetBox.
    
    Certificate Security:
    - Certificates are stored as FILES on the server, not in DB
    - Only paths are stored in database
    - Files must have restrictive permissions (600)
    """
    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name='Name'
    )

    connection_type = models.CharField(
        max_length=10,
        choices=ConnectionTypeChoices.choices,
        default=ConnectionTypeChoices.UNIX_SOCKET,
        verbose_name='Connection Type'
    )

    # ========== Unix Socket Connection ==========
    socket_path = models.CharField(
        max_length=255,
        default='http+unix://%2Fvar%2Flib%2Fincus%2Funix.socket',
        blank=True,
        verbose_name='Socket Path',
        help_text="Format: http+unix://%2Fvar%2Flib%2Fincus%2Funix.socket"
    )

    # ========== HTTPS Connection ==========
    https_url = models.URLField(
        max_length=255,
        blank=True,
        verbose_name='HTTPS URL',
        help_text="Ex: https://incus.example.com:8443"
    )

    # Paths to certificate files (NOT the content!)
    client_cert_path = models.CharField(
        max_length=500,
        blank=True,
        verbose_name='Client Certificate Path',
        help_text="Absolute path to .crt file (e.g. /etc/netbox/incus/client.crt)",
        validators=[validate_file_exists]
    )

    client_key_path = models.CharField(
        max_length=500,
        blank=True,
        verbose_name='Private Key Path',
        help_text="Absolute path to .key file (e.g. /etc/netbox/incus/client.key)",
        validators=[validate_file_exists]
    )

    ca_cert_path = models.CharField(
        max_length=500,
        blank=True,
        verbose_name='CA Certificate Path (optional)',
        help_text="To validate Incus server certificate",
        validators=[validate_file_exists]
    )

    verify_ssl = models.BooleanField(
        default=True,
        verbose_name='Verify SSL Certificate',
        help_text="Uncheck only for test environments"
    )

    # ========== General Configuration ==========
    enabled = models.BooleanField(
        default=True,
        verbose_name='Enabled'
    )

    default_cluster = models.ForeignKey(
        to='virtualization.Cluster',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='incus_hosts',
        verbose_name='Default Cluster'
    )

    class Meta:
        ordering = ('name',)
        verbose_name = 'Incus Host'
        verbose_name_plural = 'Incus Hosts'

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('plugins:netbox_incus_sync:incushost', args=[self.pk])

    @property
    def connection_url(self):
        """Returns connection URL based on type."""
        if self.connection_type == ConnectionTypeChoices.HTTPS:
            return self.https_url
        return self.socket_path

    def clean(self):
        """Model validation."""
        super().clean()
        
        if self.connection_type == ConnectionTypeChoices.UNIX_SOCKET:
            if not self.socket_path:
                raise ValidationError({
                    'socket_path': "Socket path is required."
                })
                
        elif self.connection_type == ConnectionTypeChoices.HTTPS:
            if not self.https_url:
                raise ValidationError({
                    'https_url': "HTTPS URL is required."
                })
            if not self.client_cert_path:
                raise ValidationError({
                    'client_cert_path': "Client certificate path is required."
                })
            if not self.client_key_path:
                raise ValidationError({
                    'client_key_path': "Private key path is required."
                })
            
            # Check permissions of sensitive files
            for path_field in ['client_key_path']:
                path = getattr(self, path_field)
                if path:
                    try:
                        validate_file_permissions(path)
                    except ValidationError as e:
                        raise ValidationError({path_field: e.message})

    def check_certificates(self):
        """
        Checks that certificates are accessible and valid.
        Returns (success, message).
        """
        if self.connection_type != ConnectionTypeChoices.HTTPS:
            return True, "Unix Socket Connection (no certificates)"
        
        errors = []
        
        for field, label in [
            ('client_cert_path', 'Client Certificate'),
            ('client_key_path', 'Private Key'),
        ]:
            path = getattr(self, field)
            if not path:
                errors.append(f"{label}: path not defined")
            elif not os.path.isfile(path):
                errors.append(f"{label}: file not found ({path})")
            elif not os.access(path, os.R_OK):
                errors.append(f"{label}: file not readable ({path})")
        
        if errors:
            return False, "; ".join(errors)
        return True, "Certificates OK"