"""
Incus network API — managed networks.
"""

import logging

logger = logging.getLogger(__name__)


class NetworkApiMixin:
    """Mixin providing network-related API methods."""

    def get_networks(self, project=None):
        """Retrieves the list of networks."""
        qs = self._build_project_query("recursion=1", project)
        data = self._request("GET", f"/1.0/networks{qs}")
        if data.get("type") == "sync":
            return data.get("metadata", [])
        return []
