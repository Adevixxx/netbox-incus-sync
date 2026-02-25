from unittest.mock import patch, MagicMock
from netbox_incus_sync.models import IncusHost, ConnectionTypeChoices
from netbox_incus_sync.tests.base import IncusSyncTestCase
from netbox_incus_sync.incus_client.base import IncusClientBase
import requests

class IncusClientBaseTestCase(IncusSyncTestCase):
    @patch('netbox_incus_sync.incus_client.base.requests_unixsocket.Session')
    def test_unix_socket_setup(self, mock_session):
        """Test Unix socket setup."""
        client = IncusClientBase(host=self.incus_host)
        self.assertEqual(client.base_url, self.incus_host.socket_path)
        mock_session.assert_called_once()
        
    @patch('netbox_incus_sync.incus_client.base.IncusClientBase._get_working_url')
    @patch('netbox_incus_sync.incus_client.base.requests.Session')
    def test_https_setup(self, mock_session, mock_get_url):
        """Test HTTPS setup with certificates."""
        mock_get_url.return_value = 'https://incus.example.com'
        
        # Test requires actual files if we don't mock os.path.isfile
        # We can bypass the file check by using patch on os.path.isfile
        with patch('netbox_incus_sync.incus_client.base.os.path.isfile', return_value=True), \
             patch('netbox_incus_sync.incus_client.base.os.access', return_value=True):
                 
            host = IncusHost.objects.create(
                name='https-client-test',
                connection_type=ConnectionTypeChoices.HTTPS,
                https_urls='https://incus.example.com',
                client_cert_path='/fake/cert.crt',
                client_key_path='/fake/key.key',
            )
            
            client = IncusClientBase(host=host)
            self.assertEqual(client.base_url, 'https://incus.example.com')
            mock_session.assert_called_once()
            
    @patch('netbox_incus_sync.incus_client.base.requests_unixsocket.Session')
    def test_request_success(self, mock_session):
        """Test a successful API request."""
        # Setup mock session response
        mock_response = MagicMock()
        mock_response.json.return_value = {"metadata": {"some": "data"}}
        mock_response.raise_for_status.return_value = None
        
        mock_session_instance = MagicMock()
        mock_session_instance.request.return_value = mock_response
        mock_session.return_value = mock_session_instance
        
        client = IncusClientBase(host=self.incus_host)
        result = client._request('GET', '/1.0/instances')
        
        self.assertEqual(result, {"metadata": {"some": "data"}})
        mock_session_instance.request.assert_called_with(
            'GET', 
            f'{self.incus_host.socket_path}/1.0/instances', 
            timeout=30
        )
        
    @patch('netbox_incus_sync.incus_client.base.requests_unixsocket.Session')
    def test_request_connection_error(self, mock_session):
        """Test API request handling of connection errors."""
        mock_session_instance = MagicMock()
        mock_session_instance.request.side_effect = requests.exceptions.ConnectionError("Failed")
        mock_session.return_value = mock_session_instance
        
        client = IncusClientBase(host=self.incus_host)
        
        with self.assertRaises(ConnectionError):
            client._request('GET', '/1.0/instances')
