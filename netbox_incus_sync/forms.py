"""
Forms for the Incus Sync plugin.

Contains:
    - IncusHostForm:          Create/Edit a single host
    - IncusHostClearCacheForm: Confirm cache clearing
    - IncusHostFilterForm:    Sidebar filters in list view
    - IncusHostBulkEditForm:  Edit multiple hosts at once
    - IncusHostImportForm:    CSV bulk import
"""

from django import forms
from netbox.forms import (
    NetBoxModelForm,
    NetBoxModelFilterSetForm,
    NetBoxModelImportForm,
    NetBoxModelBulkEditForm,
)
from utilities.forms.fields import (
    DynamicModelChoiceField,
    DynamicModelMultipleChoiceField,
    TagFilterField,
)
from utilities.forms.rendering import FieldSet
from utilities.forms.widgets import BulkEditNullBooleanSelect
from virtualization.models import Cluster
from dcim.models import Site
from .models import IncusHost, ConnectionTypeChoices

# ============================================
# Create / Edit Form
# ============================================


class IncusHostForm(NetBoxModelForm):
    """
    Form for creating and editing an Incus host.

    Certificates are referenced by their filesystem paths,
    not stored in the database for security reasons.
    """

    default_cluster = DynamicModelChoiceField(
        queryset=Cluster.objects.all(),
        required=False,
        label="Default Cluster",
        help_text="NetBox Cluster where synchronized VMs will be created",
    )

    default_site = DynamicModelChoiceField(
        queryset=Site.objects.all(),
        required=False,
        label="Default Site",
        help_text="Site assigned to auto-created Devices for cluster nodes",
    )

    fieldsets = (
        FieldSet("name", "connection_type", "enabled", name="General"),
        FieldSet("socket_path", name="Unix Socket Connection"),
        FieldSet("https_urls", "url_cache_ttl", name="HTTPS Connection - URLs"),
        FieldSet(
            "client_cert_path",
            "client_key_path",
            "ca_cert_path",
            "verify_ssl",
            name="HTTPS Connection - Certificates",
        ),
        FieldSet("default_cluster", "default_site", "tags", name="NetBox Association"),
        FieldSet("incus_ui_base_url", name="Incus UI Integration"),
    )

    class Meta:
        model = IncusHost
        fields = (
            "name",
            "connection_type",
            "socket_path",
            "https_urls",
            "url_cache_ttl",
            "client_cert_path",
            "client_key_path",
            "ca_cert_path",
            "verify_ssl",
            "enabled",
            "default_cluster",
            "default_site",
            "incus_ui_base_url",
            "tags",
        )
        widgets = {
            "https_urls": forms.Textarea(
                attrs={
                    "placeholder": (
                        "# One URL per line, lines starting with # are ignored\n"
                        "https://incus1.example.com:8443\n"
                        "https://incus2.example.com:8443\n"
                    ),
                    "rows": 5,
                }
            ),
            "client_cert_path": forms.TextInput(
                attrs={"placeholder": "/etc/netbox/incus/client.crt"}
            ),
            "client_key_path": forms.TextInput(
                attrs={"placeholder": "/etc/netbox/incus/client.key"}
            ),
            "ca_cert_path": forms.TextInput(
                attrs={"placeholder": "/etc/netbox/incus/server.crt (optional)"}
            ),
            "incus_ui_base_url": forms.URLInput(
                attrs={"placeholder": "https://incus.example.com:8443"}
            ),
        }
        help_texts = {
            "https_urls": (
                "Server URLs for failover. One per line.\n"
                "The system tests each URL until one works and caches the result."
            ),
            "url_cache_ttl": (
                "How long (in seconds) to use a working URL before re-testing. "
                "Set to 0 to always test. Default: 300 (5 minutes)."
            ),
            "client_cert_path": (
                "Absolute path to client certificate. "
                "File must be readable by NetBox user."
            ),
            "client_key_path": (
                "Absolute path to private key. " "Recommended permissions: chmod 600"
            ),
        }

    def clean(self):
        cleaned_data = super().clean()

        # S'assurer que cleaned_data existe
        if cleaned_data is None:
            return cleaned_data

        connection_type = cleaned_data.get("connection_type")

        if connection_type == ConnectionTypeChoices.HTTPS:
            https_urls = cleaned_data.get("https_urls") or ""
            https_urls = https_urls.strip()

            # Need at least one URL
            has_url = False
            if https_urls:
                for line in https_urls.split("\n"):
                    line = line.strip()
                    if line and not line.startswith("#"):
                        has_url = True
                        break

            if not has_url:
                raise forms.ValidationError(
                    {"https_urls": "At least one HTTPS URL is required."}
                )

            # Validate URL format
            for i, line in enumerate(https_urls.split("\n"), 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                # Basic URL validation
                if not line.startswith(("http://", "https://")):
                    raise forms.ValidationError(
                        {
                            "https_urls": f"Line {i}: URL must start with http:// or https://"
                        }
                    )

        return cleaned_data


# ============================================
# Cache Clear Form
# ============================================


class IncusHostClearCacheForm(forms.Form):
    """Simple form to confirm cache clearing."""

    confirm = forms.BooleanField(
        required=True,
        label="Confirm cache clear",
        help_text="This will force a re-test of all URLs on next connection.",
    )


# ============================================
# Filter Form (sidebar in list view)
# ============================================


class IncusHostFilterForm(NetBoxModelFilterSetForm):
    """
    Filter form displayed in the sidebar of the IncusHost list view.

    Each field here corresponds to a filter in IncusHostFilterSet.
    The field names MUST match the filterset filter names exactly.

    NetBoxModelFilterSetForm automatically provides:
        - q:   the search box at the top
        - tag: the tag filter widget
    """

    model = IncusHost

    fieldsets = (
        FieldSet("q", "filter_id", "tag"),
        FieldSet("connection_type", "enabled", "verify_ssl", name="Connection"),
        FieldSet("default_cluster_id", "default_site_id", name="NetBox Association"),
    )

    connection_type = forms.MultipleChoiceField(
        choices=ConnectionTypeChoices.choices,
        required=False,
        label="Connection Type",
    )

    enabled = forms.NullBooleanField(
        required=False,
        label="Enabled",
        widget=forms.Select(
            choices=(
                ("", "---------"),
                ("true", "Yes"),
                ("false", "No"),
            )
        ),
    )

    verify_ssl = forms.NullBooleanField(
        required=False,
        label="Verify SSL",
        widget=forms.Select(
            choices=(
                ("", "---------"),
                ("true", "Yes"),
                ("false", "No"),
            )
        ),
    )

    default_cluster_id = DynamicModelMultipleChoiceField(
        queryset=Cluster.objects.all(),
        required=False,
        label="Default Cluster",
    )

    default_site_id = DynamicModelMultipleChoiceField(
        queryset=Site.objects.all(),
        required=False,
        label="Default Site",
    )

    tag = TagFilterField(model)


# ============================================
# Bulk Edit Form (edit multiple hosts at once)
# ============================================


class IncusHostBulkEditForm(NetBoxModelBulkEditForm):
    """
    Form for editing multiple IncusHost objects at once.

    Only fields that make sense to change in bulk are exposed.
    All fields are optional (nullable=True for FKs, required=False
    for others) because bulk edit only updates fields that the user
    explicitly sets.
    """

    model = IncusHost

    connection_type = forms.ChoiceField(
        choices=ConnectionTypeChoices.choices,
        required=False,
        label="Connection Type",
    )

    enabled = forms.NullBooleanField(
        required=False,
        label="Enabled",
        widget=BulkEditNullBooleanSelect,
    )

    verify_ssl = forms.NullBooleanField(
        required=False,
        label="Verify SSL",
        widget=BulkEditNullBooleanSelect,
    )

    url_cache_ttl = forms.IntegerField(
        required=False,
        label="URL Cache TTL (seconds)",
        min_value=0,
    )

    default_cluster = DynamicModelChoiceField(
        queryset=Cluster.objects.all(),
        required=False,
        label="Default Cluster",
    )

    default_site = DynamicModelChoiceField(
        queryset=Site.objects.all(),
        required=False,
        label="Default Site",
    )

    incus_ui_base_url = forms.URLField(
        required=False,
        label="Incus UI Base URL",
    )

    fieldsets = (
        FieldSet("connection_type", "enabled", name="General"),
        FieldSet("verify_ssl", "url_cache_ttl", name="HTTPS Settings"),
        FieldSet("default_cluster", "default_site", name="NetBox Association"),
        FieldSet("incus_ui_base_url", name="Incus UI Integration"),
    )

    nullable_fields = ("default_cluster", "default_site", "incus_ui_base_url")


# ============================================
# Import Form (CSV bulk import)
# ============================================


class IncusHostImportForm(NetBoxModelImportForm):
    """
    Form for importing IncusHost objects from CSV.

    CSV columns map to these fields. Example CSV:
        name,connection_type,enabled,socket_path,https_urls,url_cache_ttl,verify_ssl
        prod-host,https,true,,https://incus.prod.local:8443,300,true
        dev-host,unix,true,http+unix://%2Fvar%2Flib%2Fincus%2Funix.socket,,300,true

    ForeignKey fields (default_cluster, default_site) are resolved
    by name thanks to the to_field_name parameter.
    """

    # Resolve cluster by name
    default_cluster = DynamicModelChoiceField(
        queryset=Cluster.objects.all(),
        required=False,
        to_field_name="name",
        label="Default Cluster",
        help_text="Cluster name (must already exist)",
    )

    # Resolve site by slug (NetBox convention for imports)
    default_site = DynamicModelChoiceField(
        queryset=Site.objects.all(),
        required=False,
        to_field_name="slug",
        label="Default Site",
        help_text="Site slug (must already exist)",
    )

    class Meta:
        model = IncusHost
        fields = (
            "name",
            "connection_type",
            "enabled",
            "socket_path",
            "https_urls",
            "url_cache_ttl",
            "verify_ssl",
            "default_cluster",
            "default_site",
            "incus_ui_base_url",
            "tags",
        )
