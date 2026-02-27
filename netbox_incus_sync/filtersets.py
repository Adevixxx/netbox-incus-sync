"""
FilterSets for the Incus Sync plugin.

FilterSets define how model objects can be filtered in both the UI
(list view filter sidebar) and the REST API (query parameters).
"""

import django_filters
from django.db.models import Q
from netbox.filtersets import NetBoxModelFilterSet
from virtualization.models import Cluster
from dcim.models import Site
from .models import IncusHost, ConnectionTypeChoices


class IncusHostFilterSet(NetBoxModelFilterSet):
    """
    FilterSet for the IncusHost model.

    Provides filtering on all meaningful fields:
    - name:             text search (exact, contains, etc. via django-filters lookups)
    - connection_type:  multiple choice (unix, https)
    - enabled:          boolean
    - verify_ssl:       boolean
    - default_cluster:  by ID or by name
    - default_site:     by ID or by name
    - q:                global search (searches in name, socket_path, https_urls)
    """

    # ── Text / Choice filters ──────────────────────────────────────────

    name = django_filters.CharFilter(
        lookup_expr='icontains',
        label='Name (contains)',
    )

    connection_type = django_filters.MultipleChoiceFilter(
        choices=ConnectionTypeChoices.choices,
        label='Connection Type',
    )

    enabled = django_filters.BooleanFilter(
        label='Enabled',
    )

    verify_ssl = django_filters.BooleanFilter(
        label='Verify SSL',
    )

    # ── Related object filters ─────────────────────────────────────────

    default_cluster_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Cluster.objects.all(),
        field_name='default_cluster',
        label='Default Cluster (ID)',
    )

    default_cluster = django_filters.ModelMultipleChoiceFilter(
        queryset=Cluster.objects.all(),
        field_name='default_cluster__name',
        to_field_name='name',
        label='Default Cluster (name)',
    )

    default_site_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Site.objects.all(),
        field_name='default_site',
        label='Default Site (ID)',
    )

    default_site = django_filters.ModelMultipleChoiceFilter(
        queryset=Site.objects.all(),
        field_name='default_site__name',
        to_field_name='name',
        label='Default Site (name)',
    )

    class Meta:
        model = IncusHost
        fields = (
            'id',
            'name',
            'connection_type',
            'enabled',
            'verify_ssl',
            'default_cluster_id',
            'default_cluster',
            'default_site_id',
            'default_site',
        )

    def search(self, queryset, name, value):
        """
        Global search handler for the `q` parameter.

        Searches across:
        - name:        the host display name
        - socket_path: for unix socket hosts
        - https_urls:  for HTTPS hosts (may contain multiple URLs)

        This is called automatically by NetBoxModelFilterSet when
        a user types in the search bar or uses ?q= in the API.
        """
        if not value.strip():
            return queryset

        return queryset.filter(
            Q(name__icontains=value)
            | Q(socket_path__icontains=value)
            | Q(https_urls__icontains=value)
        )