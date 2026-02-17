"""
Incus profiles API — list and get profiles.
"""

import logging

logger = logging.getLogger(__name__)


class ProfilesApiMixin:
    """Mixin providing profile-related API methods."""

    def get_profiles(self, recursion=1):
        """Retrieves the list of Incus profiles with their configuration."""
        try:
            data = self._request('GET', f'/1.0/profiles?recursion={recursion}')
            if data.get('type') == 'sync':
                return data.get('metadata', [])
        except Exception as e:
            logger.error(f"Unable to retrieve profiles: {e}")
        return []

    def get_profile(self, name):
        """Retrieves details of a specific profile."""
        try:
            data = self._request('GET', f'/1.0/profiles/{name}')
            if data.get('type') == 'sync':
                return data.get('metadata')
        except Exception as e:
            logger.debug(f"Profile {name} not found: {e}")
        return None