"""
Incus server info and connection testing API.
"""

import logging

logger = logging.getLogger(__name__)


class ServerApiMixin:
    """Mixin providing server info and connection testing methods."""

    def get_server_info(self):
        """Retrieves Incus server information."""
        data = self._request('GET', '/1.0')
        if data.get('type') == 'sync':
            return data.get('metadata')
        return None

    def test_connection(self):
        """
        Tests connection to the Incus server.

        Returns:
            tuple: (success: bool, message: str, extra_info: dict)
        """
        try:
            info = self.get_server_info()
            if info:
                env = info.get('environment', {})
                server_name = env.get('server_name', 'Unknown')
                version = env.get('server_version', 'Unknown')

                # Check if it is a cluster
                cluster_info = self.get_cluster()
                cluster_enabled = cluster_info.get('enabled', False) if cluster_info else False

                extra_info = {
                    'server_name': server_name,
                    'version': version,
                    'cluster_enabled': cluster_enabled,
                    'connected_url': self.base_url,
                }

                if cluster_enabled:
                    members = self.get_cluster_members()
                    extra_info['cluster_members'] = len(members)
                    return True, f"Connected to {server_name} (version {version}) - Cluster with {len(members)} nodes", extra_info

                return True, f"Connected to {server_name} (version {version})", extra_info
            return False, "Invalid server response", {}
        except FileNotFoundError as e:
            return False, f"Missing certificate file: {e}", {}
        except PermissionError as e:
            return False, f"Permission denied: {e}", {}
        except ConnectionError as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"Unexpected error: {e}", {}

    def test_all_urls(self, host):
        """
        Tests all configured URLs and returns their status.

        Args:
            host: IncusHost instance

        Returns:
            list: List of dicts with 'url', 'success', 'message' keys
        """
        results = []
        urls = host.get_https_urls()

        for url in urls:
            try:
                success = self._test_url_connection(url, host)
                if success:
                    results.append({
                        'url': url,
                        'success': True,
                        'message': 'Connection successful'
                    })
                else:
                    results.append({
                        'url': url,
                        'success': False,
                        'message': 'Connection failed'
                    })
            except Exception as e:
                results.append({
                    'url': url,
                    'success': False,
                    'message': str(e)
                })

        return results