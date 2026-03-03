"""
Incus profiles API — list and get profiles.
"""

import logging

logger = logging.getLogger(__name__)


class ProfilesApiMixin:
    """Mixin providing profile-related API methods."""

    def get_profiles(self, recursion=1, project=None):
        """Retrieves the list of Incus profiles with their configuration."""
        try:
            qs = self._build_project_query(f"recursion={recursion}", project)
            data = self._request("GET", f"/1.0/profiles{qs}")
            if data.get("type") == "sync":
                return data.get("metadata", [])
        except Exception as e:
            logger.error("Unable to retrieve profiles: %s", e)
        return []

    def get_profile(self, name, project=None):
        """Retrieves details of a specific profile."""
        try:
            qs = self._build_project_query(project=project)
            data = self._request("GET", f"/1.0/profiles/{name}{qs}")
            if data.get("type") == "sync":
                return data.get("metadata")
        except Exception as e:
            logger.debug("Profile %s not found: %s", name, e)
        return None
