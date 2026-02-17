"""
Incus cluster API — cluster info, members, groups.
"""

import logging

logger = logging.getLogger(__name__)


class ClusterApiMixin:
    """Mixin providing cluster-related API methods."""

    def get_cluster(self):
        """
        Retrieves cluster information.

        Returns:
            dict: Cluster information or None if no cluster
        """
        try:
            data = self._request('GET', '/1.0/cluster')
            if data.get('type') == 'sync':
                return data.get('metadata')
        except Exception as e:
            logger.debug(f"No cluster configured: {e}")
        return None

    def get_cluster_members(self, recursion=1):
        """
        Retrieves the list of cluster members.

        Args:
            recursion: Detail level (0=URLs, 1=full details)

        Returns:
            list: List of cluster members
        """
        try:
            data = self._request('GET', f'/1.0/cluster/members?recursion={recursion}')
            if data.get('type') == 'sync':
                return data.get('metadata', [])
        except Exception as e:
            logger.debug(f"Unable to retrieve cluster members: {e}")
        return []

    def get_cluster_member(self, name):
        """
        Retrieves details of a cluster member.

        Args:
            name: Member name

        Returns:
            dict: Member details or None
        """
        try:
            data = self._request('GET', f'/1.0/cluster/members/{name}')
            if data.get('type') == 'sync':
                return data.get('metadata')
        except Exception as e:
            logger.debug(f"Member {name} not found: {e}")
        return None

    def get_cluster_member_state(self, name):
        """
        Retrieves the state of a cluster member (CPU, memory, etc.).

        Args:
            name: Member name

        Returns:
            dict: Member state or None
        """
        try:
            data = self._request('GET', f'/1.0/cluster/members/{name}/state')
            if data.get('type') == 'sync':
                return data.get('metadata')
        except Exception as e:
            logger.debug(f"Member state {name} not available: {e}")
        return None

    def get_cluster_groups(self, recursion=1):
        """
        Retrieves the list of cluster groups.

        Args:
            recursion: Detail level

        Returns:
            list: List of cluster groups
        """
        try:
            data = self._request('GET', f'/1.0/cluster/groups?recursion={recursion}')
            if data.get('type') == 'sync':
                return data.get('metadata', [])
        except Exception as e:
            logger.debug(f"Unable to retrieve cluster groups: {e}")
        return []

    def get_cluster_group(self, name):
        """
        Retrieves details of a cluster group.

        Args:
            name: Group name

        Returns:
            dict: Group details or None
        """
        try:
            data = self._request('GET', f'/1.0/cluster/groups/{name}')
            if data.get('type') == 'sync':
                return data.get('metadata')
        except Exception as e:
            logger.debug(f"Group {name} not found: {e}")
        return None