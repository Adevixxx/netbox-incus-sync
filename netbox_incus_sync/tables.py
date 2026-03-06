import django_tables2 as tables
from netbox.tables import NetBoxTable, ChoiceFieldColumn, ToggleColumn
from django.utils.html import format_html
from .models import IncusHost


class IncusHostTable(NetBoxTable):
    """Table for displaying Incus hosts."""

    pk = ToggleColumn()

    name = tables.Column(linkify=True, verbose_name="Name")

    connection_type = ChoiceFieldColumn(verbose_name="Type")

    connection_info = tables.Column(
        accessor="connection_url", verbose_name="Connection", orderable=False
    )

    url_count = tables.Column(verbose_name="URLs", empty_values=(), orderable=False)

    cache_status = tables.Column(verbose_name="Cache", empty_values=(), orderable=False)

    enabled = tables.BooleanColumn(verbose_name="Enabled")

    sync_interval = tables.Column(
        verbose_name="Sync Interval", empty_values=(), orderable=False
    )

    default_cluster = tables.Column(linkify=True, verbose_name="Cluster")

    actions = tables.Column(verbose_name="", empty_values=(), orderable=False)

    class Meta(NetBoxTable.Meta):
        model = IncusHost
        fields = (
            "pk",
            "name",
            "connection_type",
            "connection_info",
            "url_count",
            "cache_status",
            "enabled",
            "sync_interval",
            "default_cluster",
            "actions",
            "tags",
        )
        default_columns = (
            "pk",
            "name",
            "connection_type",
            "connection_info",
            "url_count",
            "cache_status",
            "enabled",
            "sync_interval",
            "default_cluster",
            "actions",
        )

    def render_sync_interval(self, record):
        """Render sync interval as human-readable label."""
        display = record.sync_interval_display
        if not display:
            return format_html(
                '<span class="badge bg-secondary text-dark">Disabled</span>'
            )
        return format_html('<span class="badge bg-info text-dark">{}</span>', display)

    def render_url_count(self, record):
        """Render the URL count for HTTPS connections."""
        if record.connection_type != "https":
            return "-"

        urls = record.get_https_urls()
        count = len(urls)

        if count == 0:
            return format_html('<span class="badge bg-danger text-dark">0</span>')
        if count == 1:
            return format_html('<span class="badge bg-secondary text-dark">1</span>')
        return format_html('<span class="badge bg-info text-dark">{}</span>', count)

    def render_cache_status(self, record):
        """Render the URL cache status."""
        if record.connection_type != "https":
            return "-"

        if not record.last_working_url:
            return format_html('<span class="badge bg-secondary text-dark">none</span>')

        if record.is_url_cache_valid():
            return format_html(
                '<span class="badge bg-success text-dark" title="{}">valid</span>',
                record.last_working_url,
            )
        return format_html(
            '<span class="badge bg-warning text-dark" title="{}">expired</span>',
            record.last_working_url,
        )

    def render_actions(self, record):
        """Render a sync button for each host."""
        if not record.enabled:
            return format_html(
                '<span class="badge bg-secondary text-dark" title="Host disabled">'
                '<i class="mdi mdi-sync-off"></i>'
                "</span>"
            )
        return format_html(
            '<a href="/plugins/incus-sync/sync/host/{}/?next=/plugins/incus-sync/hosts/" '
            'class="btn btn-sm btn-outline-blue" title="Sync this host">'
            '<i class="mdi mdi-sync"></i>'
            "</a>",
            record.pk,
        )
