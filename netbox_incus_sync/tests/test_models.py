from netbox_incus_sync.models import IncusHost, ConnectionTypeChoices
from netbox_incus_sync.tests.base import IncusSyncTestCase
from django.utils import timezone
from datetime import timedelta


class IncusHostModelTestCase(IncusSyncTestCase):
    def test_incus_host_creation(self):
        """Test that IncusHost is created correctly."""
        host = self.incus_host
        self.assertEqual(host.name, "test-host")
        self.assertEqual(host.connection_type, ConnectionTypeChoices.UNIX_SOCKET)
        self.assertTrue(host.enabled)

    def test_get_absolute_url(self):
        """Test getting the absolute URL."""
        host = self.incus_host
        self.assertIsNotNone(host.get_absolute_url())

    def test_connection_url_property_unix(self):
        """Test connection_url property for unix socket."""
        host = self.incus_host
        self.assertEqual(host.connection_url, host.socket_path)

    def test_connection_url_property_https(self):
        """Test connection_url property for https."""
        host = IncusHost.objects.create(
            name="test-host-https",
            connection_type=ConnectionTypeChoices.HTTPS,
            https_urls="https://incus1.example.com:8443\nhttps://incus2.example.com:8443\n#Comment\n",
        )
        self.assertEqual(
            host.connection_url, "https://incus1.example.com:8443 (+1 more)"
        )

        # Test with cached url
        host.update_working_url("https://incus2.example.com:8443")
        self.assertEqual(
            host.connection_url, "https://incus2.example.com:8443 (cached)"
        )

    def test_get_https_urls(self):
        """Test get_https_urls method cleans and deduplicates correctly."""
        host = IncusHost.objects.create(
            name="test-urls-host",
            connection_type=ConnectionTypeChoices.HTTPS,
            https_urls="https://incus1.example.com:8443\n\nhttps://incus2.example.com:8443\n#Comment\nhttps://incus1.example.com:8443",
        )
        urls = host.get_https_urls()
        self.assertEqual(len(urls), 2)
        self.assertEqual(urls[0], "https://incus1.example.com:8443")
        self.assertEqual(urls[1], "https://incus2.example.com:8443")

    def test_url_cache(self):
        """Test URL cache validity methods."""
        host = IncusHost.objects.create(
            name="test-cache-host",
            connection_type=ConnectionTypeChoices.HTTPS,
            url_cache_ttl=300,
        )
        self.assertFalse(host.is_url_cache_valid())

        host.update_working_url("https://test.local")
        self.assertTrue(host.is_url_cache_valid())
        self.assertEqual(host.last_working_url, "https://test.local")
        self.assertIsNotNone(host.last_working_url_checked)

        # Manually backdate to test expiration
        host.last_working_url_checked = timezone.now() - timedelta(seconds=350)
        host.save()
        self.assertFalse(host.is_url_cache_valid())

        host.clear_url_cache()
        self.assertEqual(host.last_working_url, "")
        self.assertIsNone(host.last_working_url_checked)
        self.assertFalse(host.is_url_cache_valid())
