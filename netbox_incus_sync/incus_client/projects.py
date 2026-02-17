"""
Incus projects API — list and get projects.
"""

import logging

logger = logging.getLogger(__name__)


class ProjectsApiMixin:
    """Mixin providing project-related API methods."""

    def get_projects(self, recursion=1):
        """
        Retrieves the list of Incus projects with their configuration.

        Args:
            recursion: Detail level (0=URLs, 1=full details)

        Returns:
            list: List of project dicts with name, description, config, etc.
        """
        try:
            data = self._request('GET', f'/1.0/projects?recursion={recursion}')
            if data.get('type') == 'sync':
                return data.get('metadata', [])
        except Exception as e:
            logger.error(f"Unable to retrieve projects: {e}")
        return []

    def get_project(self, name):
        """
        Retrieves details of a specific project.

        Args:
            name: Project name

        Returns:
            dict: Project details including config (features.*), or None
        """
        try:
            data = self._request('GET', f'/1.0/projects/{name}')
            if data.get('type') == 'sync':
                return data.get('metadata')
        except Exception as e:
            logger.debug(f"Project {name} not found: {e}")
        return None