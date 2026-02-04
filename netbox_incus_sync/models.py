from django.db import models
from django.urls import reverse
from django.core.exceptions import ValidationError
from django.utils import timezone
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
    # Single URL
    https_url = models.URLField(
        max_length=255,
        blank=True,
        verbose_name='HTTPS URL',
        help_text="Single URL. Ex: https://incus.example.com:8443 (use 'HTTPS URLs' for multiple servers)"
    )
    
    # Multiple URLs support (new)
    https_urls = models.TextField(
        blank=True,
        verbose_name='HTTPS URLs (Multi-server)',
        help_text=(
            "Multiple URLs, one per line. The system will test each until one works.\n"
            "Example:\n"
            "https://incus1.example.com:8443\n"
            "https://incus2.example.com:8443"
        )
    )
    
    # URL caching for performance
    last_working_url = models.URLField(
        max_length=255,
        blank=True,
        verbose_name='Last Working URL',
        help_text="Automatically updated when a connection succeeds"
    )
    
    last_working_url_checked = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Last URL Check'
    )
    
    url_cache_ttl = models.IntegerField(
        default=300,
        verbose_name='URL Cache TTL (seconds)',
        help_text="How long to use the cached working URL before re-testing (default: 300s = 5min)"
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
        """Returns connection URL based on type (for display purposes)."""
        if self.connection_type == ConnectionTypeChoices.HTTPS:
            # Show cached URL if available, otherwise first configured URL
            if self.last_working_url:
                return f"{self.last_working_url} (cached)"
            urls = self.get_https_urls()
            if urls:
                if len(urls) == 1:
                    return urls[0]
                return f"{urls[0]} (+{len(urls)-1} more)"
            return self.https_url
        return self.socket_path

    # ========== Multi-URL Methods ==========
    
    def get_https_urls(self):
        """
        Returns the list of all configured HTTPS URLs.
        Handles both single URL and multi-URL fields.
        
        Returns:
            list: List of URLs to try
        """
        urls = []
        
        # Add single URL if configured
        if self.https_url:
            urls.append(self.https_url.strip())
        
        # Add multi-URLs
        if self.https_urls:
            for line in self.https_urls.strip().split('\n'):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                urls.append(line)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_urls = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        return unique_urls

    def is_url_cache_valid(self):
        """
        Checks if the cached working URL is still valid.
        
        Returns:
            bool: True if cache is valid and should be used
        """
        if not self.last_working_url:
            return False
        
        if not self.last_working_url_checked:
            return False
        
        age = timezone.now() - self.last_working_url_checked
        return age.total_seconds() < self.url_cache_ttl

    def update_working_url(self, url):
        """
        Updates the cached working URL.
        
        Args:
            url: The URL that successfully connected
        """
        self.last_working_url = url
        self.last_working_url_checked = timezone.now()
        self.save(update_fields=['last_working_url', 'last_working_url_checked'])

    def clear_url_cache(self):
        """Clears the cached working URL, forcing a re-test on next connection."""
        self.last_working_url = ''
        self.last_working_url_checked = None
        self.save(update_fields=['last_working_url', 'last_working_url_checked'])

    # ========== Validation ==========

    def clean(self):
        """Model validation."""
        super().clean()
        
        if self.connection_type == ConnectionTypeChoices.UNIX_SOCKET:
            if not self.socket_path:
                raise ValidationError({
                    'socket_path': "Socket path is required."
                })
                
        elif self.connection_type == ConnectionTypeChoices.HTTPS:
            # Need at least one URL (single or multi)
            if not self.https_url and not self.https_urls:
                raise ValidationError({
                    'https_url': "At least one HTTPS URL is required (single or multiple)."
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