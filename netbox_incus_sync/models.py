from django.db import models
from django.urls import reverse
from django.core.exceptions import ValidationError
from django.utils import timezone
from netbox.models import NetBoxModel
import os


class ConnectionTypeChoices(models.TextChoices):
    UNIX_SOCKET = "unix", "Unix Socket"
    HTTPS = "https", "HTTPS (TLS certificate)"


def validate_file_exists(path):
    """Validates that the file exists and is readable."""
    if path and not os.path.isfile(path):
        raise ValidationError(f"File does not exist: {path}")
    if path and not os.access(path, os.R_OK):
        raise ValidationError(f"File is not readable: {path}")


class IncusHost(NetBoxModel):
    """
    Model representing an Incus host to synchronize with NetBox.

    Certificate Security:
    - Certificates are stored as FILES on the server, not in DB
    - Only paths are stored in database
    - Files must have restrictive permissions (600)
    """

    name = models.CharField(max_length=100, unique=True, verbose_name="Name")

    connection_type = models.CharField(
        max_length=10,
        choices=ConnectionTypeChoices.choices,
        default=ConnectionTypeChoices.UNIX_SOCKET,
        verbose_name="Connection Type",
    )

    # ========== Unix Socket Connection ==========
    socket_path = models.CharField(
        max_length=255,
        default="http+unix://%2Fvar%2Flib%2Fincus%2Funix.socket",
        blank=True,
        verbose_name="Socket Path",
        help_text="Format: http+unix://%2Fvar%2Flib%2Fincus%2Funix.socket",
    )

    # ========== HTTPS Connection ==========
    https_urls = models.TextField(
        blank=True,
        verbose_name="HTTPS URLs",
        help_text=(
            "Server URLs, one per line. "
            "Lines starting with # are ignored.\n"
            "The system tests each URL in order until one works, then caches the result.\n"
            "Example:\nhttps://incus1.example.com:8443\nhttps://incus2.example.com:8443"
        ),
    )

    last_working_url = models.URLField(
        max_length=255,
        blank=True,
        verbose_name="Last Working URL",
        help_text="Automatically updated when a connection succeeds",
    )

    last_working_url_checked = models.DateTimeField(
        null=True, blank=True, verbose_name="Last URL Check"
    )

    url_cache_ttl = models.IntegerField(
        default=300,
        verbose_name="URL Cache TTL (seconds)",
        help_text="How long to use the cached working URL before re-testing (default: 300s = 5min)",
    )

    client_cert_path = models.CharField(
        max_length=500,
        blank=True,
        verbose_name="Client Certificate Path",
        help_text="Absolute path to .crt file (e.g. /etc/netbox/incus/client.crt)",
        validators=[validate_file_exists],
    )

    client_key_path = models.CharField(
        max_length=500,
        blank=True,
        verbose_name="Private Key Path",
        help_text="Absolute path to .key file (e.g. /etc/netbox/incus/client.key)",
        validators=[validate_file_exists],
    )

    ca_cert_path = models.CharField(
        max_length=500,
        blank=True,
        verbose_name="CA Certificate Path (optional)",
        help_text="To validate Incus server certificate",
        validators=[validate_file_exists],
    )

    verify_ssl = models.BooleanField(
        default=True,
        verbose_name="Verify SSL Certificate",
        help_text="Uncheck only for test environments",
    )

    # ========== General Configuration ==========
    enabled = models.BooleanField(default=True, verbose_name="Enabled")

    default_cluster = models.ForeignKey(
        to="virtualization.Cluster",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incus_hosts",
        verbose_name="Default Cluster",
    )

    default_site = models.ForeignKey(
        to="dcim.Site",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incus_hosts",
        verbose_name="Default Site",
        help_text="Site assigned to auto-created Devices for cluster nodes",
    )

    sync_projects = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Projects to Sync",
        help_text='Projects to sync (empty = all). Example: ["default", "prod"]',
    )

    class Meta:
        ordering = ("name",)
        verbose_name = "Incus Host"
        verbose_name_plural = "Incus Hosts"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("plugins:netbox_incus_sync:incushost", args=[self.pk])

    @property
    def connection_url(self):
        """Returns connection URL based on type (for display purposes)."""
        if self.connection_type == ConnectionTypeChoices.HTTPS:
            if self.last_working_url:
                return f"{self.last_working_url} (cached)"
            urls = self.get_https_urls()
            if urls:
                if len(urls) == 1:
                    return urls[0]
                return f"{urls[0]} (+{len(urls)-1} more)"
            return "No URL configured"
        return self.socket_path

    # ========== Multi-URL Methods ==========

    def get_https_urls(self):
        """Returns the list of all configured HTTPS URLs (deduplicated, ordered)."""
        if not self.https_urls:
            return []

        seen = set()
        unique_urls = []
        for line in self.https_urls.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line not in seen:
                seen.add(line)
                unique_urls.append(line)

        return unique_urls

    def is_url_cache_valid(self):
        """Checks if the cached working URL is still valid."""
        if not self.last_working_url or not self.last_working_url_checked:
            return False
        age = timezone.now() - self.last_working_url_checked
        return age.total_seconds() < self.url_cache_ttl

    def update_working_url(self, url):
        """Updates the cached working URL."""
        self.last_working_url = url
        self.last_working_url_checked = timezone.now()
        self.save(update_fields=["last_working_url", "last_working_url_checked"])

    def clear_url_cache(self):
        """Clears the cached working URL, forcing a re-test on next connection."""
        self.last_working_url = ""
        self.last_working_url_checked = None
        self.save(update_fields=["last_working_url", "last_working_url_checked"])
