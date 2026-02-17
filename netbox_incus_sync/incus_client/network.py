"""
Incus network API — managed networks.
"""

import logging

logger = logging.getLogger(__name__)


class NetworkApiMixin:
    """Mixin providing network-related API methods."""

    def get_networks(self):
        """Retrieves the list of networks."""
        data = self._request('GET', '/1.0/networks?recursion=1')
        if data.get('type') == 'sync':
            return data.get('metadata', [])
        return []