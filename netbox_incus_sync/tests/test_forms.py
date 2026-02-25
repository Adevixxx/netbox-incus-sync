from netbox_incus_sync.forms import IncusHostForm
from netbox_incus_sync.models import ConnectionTypeChoices
from netbox_incus_sync.tests.base import IncusSyncTestCase


class IncusHostFormTestCase(IncusSyncTestCase):

    def test_valid_unix_form(self):
        data = {
            'name': 'form-host-unix',
            'connection_type': ConnectionTypeChoices.UNIX_SOCKET,
            'socket_path': 'http+unix://%2Fvar%2Flib%2Fincus%2Funix.socket',
            'url_cache_ttl': 300,
            'enabled': True,
        }
        form = IncusHostForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)

    def test_valid_https_form(self):
        data = {
            'name': 'form-host-https',
            'connection_type': ConnectionTypeChoices.HTTPS,
            'https_urls': 'https://incus.example.com:8443',
            'url_cache_ttl': 300,
            'enabled': True,
        }
        form = IncusHostForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)

    def test_required_url_cache_ttl(self):
        """url_cache_ttl is required."""
        data = {
            'name': 'form-no-ttl',
            'connection_type': ConnectionTypeChoices.UNIX_SOCKET,
            'enabled': True,
        }
        form = IncusHostForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('url_cache_ttl', form.errors)

    def test_multiple_https_urls(self):
        """Multiple HTTPS URLs with comments should be accepted."""
        data = {
            'name': 'form-multi-url',
            'connection_type': ConnectionTypeChoices.HTTPS,
            'https_urls': 'https://incus1.example.com:8443\n# backup\nhttps://incus2.example.com:8443',
            'url_cache_ttl': 300,
            'enabled': True,
        }
        form = IncusHostForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)