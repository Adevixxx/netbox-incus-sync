"""
Incus storage API — pools, volumes, volume state.
"""

import logging

logger = logging.getLogger(__name__)


class StorageApiMixin:
    """Mixin providing storage-related API methods."""

    def get_storage_pools(self):
        """Retrieves the list of storage pools."""
        data = self._request('GET', '/1.0/storage-pools?recursion=1')
        if data.get('type') == 'sync':
            return data.get('metadata', [])
        return []

    def get_storage_pool_info(self, pool_name):
        """
        Retrieves information about a specific storage pool.

        Args:
            pool_name: Storage pool name

        Returns:
            dict: Pool information including driver type, or None
        """
        try:
            data = self._request('GET', f'/1.0/storage-pools/{pool_name}')
            if data.get('type') == 'sync':
                return data.get('metadata')
        except Exception as e:
            logger.debug(f"Pool {pool_name} not found: {e}")
        return None

    def get_storage_pool_resources(self, pool_name):
        """
        Retrieves resource usage information for a storage pool.

        Args:
            pool_name: Storage pool name

        Returns:
            dict: Pool resources (space used, total, inodes, etc.)
        """
        try:
            data = self._request('GET', f'/1.0/storage-pools/{pool_name}/resources')
            if data.get('type') == 'sync':
                return data.get('metadata')
        except Exception as e:
            logger.debug(f"Unable to get resources for pool {pool_name}: {e}")
        return None

    def get_storage_volume(self, pool, volume_type, volume_name):
        """
        Retrieves information about a storage volume.

        Args:
            pool: Storage pool name (e.g., 'default')
            volume_type: Volume type ('container', 'virtual-machine', 'custom', 'image')
            volume_name: Volume name

        Returns:
            dict: Volume information or None
        """
        try:
            data = self._request(
                'GET',
                f'/1.0/storage-pools/{pool}/volumes/{volume_type}/{volume_name}'
            )
            if data.get('type') == 'sync':
                return data.get('metadata')
        except Exception as e:
            logger.debug(f"Volume {volume_type}/{volume_name} not found in {pool}: {e}")
        return None

    def get_storage_volume_state(self, pool, volume_type, volume_name):
        """
        Retrieves the state/usage information for a storage volume.

        Args:
            pool: Storage pool name
            volume_type: Volume type ('container', 'virtual-machine', 'custom')
            volume_name: Volume name

        Returns:
            dict: Volume state with usage info
        """
        try:
            data = self._request(
                'GET',
                f'/1.0/storage-pools/{pool}/volumes/{volume_type}/{volume_name}/state'
            )
            if data.get('type') == 'sync':
                return data.get('metadata')
        except Exception as e:
            logger.debug(f"Unable to get state for volume {volume_type}/{volume_name} in {pool}: {e}")
        return None

    def get_storage_volumes(self, pool, recursion=1):
        """
        Retrieves all volumes in a storage pool.

        Args:
            pool: Storage pool name
            recursion: Detail level (0=URLs, 1=full details)

        Returns:
            list: List of volumes
        """
        try:
            data = self._request('GET', f'/1.0/storage-pools/{pool}/volumes?recursion={recursion}')
            if data.get('type') == 'sync':
                return data.get('metadata', [])
        except Exception as e:
            logger.debug(f"Unable to get volumes for pool {pool}: {e}")
        return []