"""
Incus storage API — pools, volumes, volume state.
"""

import logging

logger = logging.getLogger(__name__)


class StorageApiMixin:
    """Mixin providing storage-related API methods."""

    def get_storage_pools(self, project=None):
        """Retrieves the list of storage pools."""
        qs = self._build_project_query("recursion=1", project)
        data = self._request("GET", f"/1.0/storage-pools{qs}")
        if data.get("type") == "sync":
            return data.get("metadata", [])
        return []

    def get_storage_pool_info(self, pool_name, project=None):
        """
        Retrieves information about a specific storage pool.

        Args:
            pool_name: Storage pool name
            project: Incus project name

        Returns:
            dict: Pool information including driver type, or None
        """
        try:
            qs = self._build_project_query(project=project)
            data = self._request("GET", f"/1.0/storage-pools/{pool_name}{qs}")
            if data.get("type") == "sync":
                return data.get("metadata")
        except Exception as e:
            logger.debug("Pool %s not found: %s", pool_name, e)
        return None

    def get_storage_pool_resources(self, pool_name, project=None):
        """
        Retrieves resource usage information for a storage pool.

        Args:
            pool_name: Storage pool name
            project: Incus project name

        Returns:
            dict: Pool resources (space used, total, inodes, etc.)
        """
        try:
            qs = self._build_project_query(project=project)
            data = self._request("GET", f"/1.0/storage-pools/{pool_name}/resources{qs}")
            if data.get("type") == "sync":
                return data.get("metadata")
        except Exception as e:
            logger.debug("Unable to get resources for pool %s: %s", pool_name, e)
        return None

    def get_storage_volume(self, pool, volume_type, volume_name, project=None):
        """
        Retrieves information about a storage volume.

        Args:
            pool: Storage pool name (e.g., 'default')
            volume_type: Volume type ('container', 'virtual-machine', 'custom', 'image')
            volume_name: Volume name
            project: Incus project name

        Returns:
            dict: Volume information or None
        """
        try:
            qs = self._build_project_query(project=project)
            data = self._request(
                "GET",
                f"/1.0/storage-pools/{pool}/volumes/{volume_type}/{volume_name}{qs}",
            )
            if data.get("type") == "sync":
                return data.get("metadata")
        except Exception as e:
            logger.debug("Volume %s/%s not found in %s: %s", volume_type, volume_name, pool, e)
        return None

    def get_storage_volume_state(self, pool, volume_type, volume_name, project=None):
        """
        Retrieves the state/usage information for a storage volume.

        Args:
            pool: Storage pool name
            volume_type: Volume type ('container', 'virtual-machine', 'custom')
            volume_name: Volume name
            project: Incus project name

        Returns:
            dict: Volume state with usage info
        """
        try:
            qs = self._build_project_query(project=project)
            data = self._request(
                "GET",
                f"/1.0/storage-pools/{pool}/volumes/{volume_type}/{volume_name}/state{qs}",
            )
            if data.get("type") == "sync":
                return data.get("metadata")
        except Exception as e:
            logger.debug(
                "Unable to get state for volume %s/%s in %s: %s", volume_type, volume_name, pool, e
            )
        return None

    def get_storage_volumes(self, pool, recursion=1, project=None):
        """
        Retrieves all volumes in a storage pool.

        Args:
            pool: Storage pool name
            recursion: Detail level (0=URLs, 1=full details)
            project: Incus project name

        Returns:
            list: List of volumes
        """
        try:
            qs = self._build_project_query(f"recursion={recursion}", project)
            data = self._request("GET", f"/1.0/storage-pools/{pool}/volumes{qs}")
            if data.get("type") == "sync":
                return data.get("metadata", [])
        except Exception as e:
            logger.debug("Unable to get volumes for pool %s: %s", pool, e)
        return []
