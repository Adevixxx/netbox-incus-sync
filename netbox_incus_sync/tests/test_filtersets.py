"""
Tests for netbox_incus_sync.filtersets

Validates that every filter on IncusHostFilterSet works correctly:
- Text search (q parameter)
- Exact / choice filters (connection_type, enabled, verify_ssl)
- Related object filters (default_cluster, default_site)
- Tag filter (inherited from NetBoxModelFilterSet)
"""

from dcim.models import Site
from virtualization.models import Cluster, ClusterType
from extras.models import Tag

from netbox_incus_sync.models import IncusHost, ConnectionTypeChoices
from netbox_incus_sync.filtersets import IncusHostFilterSet
from netbox_incus_sync.tests.base import IncusSyncTestCase


class IncusHostFilterSetTestCase(IncusSyncTestCase):
    """
    Tests for IncusHostFilterSet.

    setUpTestData from IncusSyncTestCase already provides:
        - cls.site          (Site: 'Test Site')
        - cls.cluster       (Cluster: 'Test Cluster')
        - cls.incus_host    (IncusHost: 'test-host', unix, enabled, cluster+site)
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # Second site & cluster for filtering
        cls.site2 = Site.objects.create(name="Other Site", slug="other-site")
        cls.cluster2 = Cluster.objects.create(
            name="Other Cluster",
            type=cls.cluster_type,
        )

        # Additional hosts with varying attributes
        cls.host_https = IncusHost.objects.create(
            name="prod-https",
            connection_type=ConnectionTypeChoices.HTTPS,
            https_urls="https://incus.prod.local:8443",
            verify_ssl=True,
            enabled=True,
            default_cluster=cls.cluster2,
            default_site=cls.site2,
        )

        cls.host_disabled = IncusHost.objects.create(
            name="staging-disabled",
            connection_type=ConnectionTypeChoices.UNIX_SOCKET,
            enabled=False,
            verify_ssl=False,
        )

        cls.host_no_ssl = IncusHost.objects.create(
            name="dev-nossl",
            connection_type=ConnectionTypeChoices.HTTPS,
            https_urls="https://incus.dev.local:8443",
            verify_ssl=False,
            enabled=True,
        )

        # Tag for tag filter test
        cls.tag = Tag.objects.create(name="production", slug="production")
        cls.host_https.tags.add(cls.tag)

    # ── Helper ─────────────────────────────────────────────────────────

    def _filter(self, params):
        """Shortcut: apply filterset and return the resulting queryset."""
        fs = IncusHostFilterSet(params, IncusHost.objects.all())
        self.assertTrue(fs.is_valid(), fs.errors)
        return fs.qs

    # ── Global search (q) ──────────────────────────────────────────────

    def test_search_by_name(self):
        """?q=prod should match 'prod-https'."""
        qs = self._filter({"q": "prod"})
        self.assertIn(self.host_https, qs)
        self.assertNotIn(self.host_disabled, qs)

    def test_search_by_socket_path(self):
        """?q= on socket_path content should match relevant hosts."""
        qs = self._filter({"q": "incus.prod"})
        self.assertIn(self.host_https, qs)
        self.assertNotIn(self.incus_host, qs)
        self.assertEqual(qs.count(), 1)

    def test_search_by_https_url(self):
        """?q=incus.dev.local should match the dev host."""
        qs = self._filter({"q": "incus.dev.local"})
        self.assertIn(self.host_no_ssl, qs)
        self.assertNotIn(self.incus_host, qs)

    def test_search_empty_returns_all(self):
        """?q= (empty) should return all hosts."""
        qs = self._filter({"q": ""})
        self.assertEqual(qs.count(), IncusHost.objects.count())

    # ── connection_type ────────────────────────────────────────────────

    def test_filter_connection_type_unix(self):
        qs = self._filter({"connection_type": [ConnectionTypeChoices.UNIX_SOCKET]})
        for host in qs:
            self.assertEqual(host.connection_type, ConnectionTypeChoices.UNIX_SOCKET)

    def test_filter_connection_type_https(self):
        qs = self._filter({"connection_type": [ConnectionTypeChoices.HTTPS]})
        for host in qs:
            self.assertEqual(host.connection_type, ConnectionTypeChoices.HTTPS)

    def test_filter_connection_type_both(self):
        """Selecting both types should return all hosts."""
        qs = self._filter(
            {
                "connection_type": [
                    ConnectionTypeChoices.UNIX_SOCKET,
                    ConnectionTypeChoices.HTTPS,
                ]
            }
        )
        self.assertEqual(qs.count(), IncusHost.objects.count())

    # ── enabled ────────────────────────────────────────────────────────

    def test_filter_enabled_true(self):
        qs = self._filter({"enabled": True})
        for host in qs:
            self.assertTrue(host.enabled)
        self.assertNotIn(self.host_disabled, qs)

    def test_filter_enabled_false(self):
        qs = self._filter({"enabled": False})
        self.assertIn(self.host_disabled, qs)
        self.assertNotIn(self.incus_host, qs)

    # ── verify_ssl ─────────────────────────────────────────────────────

    def test_filter_verify_ssl_true(self):
        qs = self._filter({"verify_ssl": True})
        for host in qs:
            self.assertTrue(host.verify_ssl)

    def test_filter_verify_ssl_false(self):
        qs = self._filter({"verify_ssl": False})
        self.assertIn(self.host_disabled, qs)
        self.assertIn(self.host_no_ssl, qs)

    # ── default_cluster (by ID) ────────────────────────────────────────

    def test_filter_cluster_id(self):
        qs = self._filter({"default_cluster_id": [self.cluster.pk]})
        self.assertIn(self.incus_host, qs)
        self.assertNotIn(self.host_https, qs)

    def test_filter_cluster_id_other(self):
        qs = self._filter({"default_cluster_id": [self.cluster2.pk]})
        self.assertIn(self.host_https, qs)
        self.assertNotIn(self.incus_host, qs)

    # ── default_cluster (by name) ──────────────────────────────────────

    def test_filter_cluster_name(self):
        qs = self._filter({"default_cluster": ["Test Cluster"]})
        self.assertIn(self.incus_host, qs)
        self.assertNotIn(self.host_https, qs)

    # ── default_site (by ID) ──────────────────────────────────────────

    def test_filter_site_id(self):
        qs = self._filter({"default_site_id": [self.site.pk]})
        self.assertIn(self.incus_host, qs)
        self.assertNotIn(self.host_https, qs)

    def test_filter_site_id_other(self):
        qs = self._filter({"default_site_id": [self.site2.pk]})
        self.assertIn(self.host_https, qs)
        self.assertNotIn(self.incus_host, qs)

    # ── default_site (by name) ────────────────────────────────────────

    def test_filter_site_name(self):
        qs = self._filter({"default_site": ["Other Site"]})
        self.assertIn(self.host_https, qs)
        self.assertNotIn(self.incus_host, qs)

    # ── Hosts without cluster/site (null) ──────────────────────────────

    def test_filter_cluster_excludes_null(self):
        """Hosts without a cluster should not appear when filtering by cluster."""
        qs = self._filter({"default_cluster_id": [self.cluster.pk]})
        self.assertNotIn(self.host_disabled, qs)  # no cluster assigned
        self.assertNotIn(self.host_no_ssl, qs)  # no cluster assigned

    # ── tag ────────────────────────────────────────────────────────────

    def test_filter_by_tag(self):
        qs = self._filter({"tag": ["production"]})
        self.assertIn(self.host_https, qs)
        self.assertNotIn(self.incus_host, qs)
        self.assertNotIn(self.host_disabled, qs)

    # ── Combined filters ──────────────────────────────────────────────

    def test_combined_enabled_and_https(self):
        """Combining enabled=true + connection_type=https."""
        qs = self._filter(
            {
                "enabled": True,
                "connection_type": [ConnectionTypeChoices.HTTPS],
            }
        )
        self.assertIn(self.host_https, qs)
        self.assertIn(self.host_no_ssl, qs)
        self.assertNotIn(self.incus_host, qs)  # unix
        self.assertNotIn(self.host_disabled, qs)  # disabled

    def test_combined_search_and_connection_type(self):
        """?q=prod + connection_type=https should narrow to prod-https only."""
        qs = self._filter(
            {
                "q": "prod",
                "connection_type": [ConnectionTypeChoices.HTTPS],
            }
        )
        self.assertEqual(qs.count(), 1)
        self.assertIn(self.host_https, qs)
