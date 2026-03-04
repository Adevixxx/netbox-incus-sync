"""
Incus instances API — list, get, state, logs, screenshots.
"""

import logging
import requests

logger = logging.getLogger(__name__)


class InstancesApiMixin:
    """Mixin providing instance-related API methods."""

    def get_instances(self, recursion=1, project=None):
        """
        Retrieves the list of instances with their details.

        Args:
            recursion: Detail level (0=names, 1=config, 2=full state)
                       Use recursion=2 to get expanded_config and state
            project: Incus project name (None = default project)

        Returns:
            List of instances
        """
        qs = self._build_project_query(f"recursion={recursion}", project)
        data = self._request("GET", f"/1.0/instances{qs}")

        if data.get("type") != "sync":
            logger.error("Unexpected Incus response type: %s", data.get("type"))
            return []

        return data.get("metadata", [])

    def get_instance(self, name, project=None):
        """Retrieves details of a specific instance."""
        qs = self._build_project_query(project=project)
        data = self._request("GET", f"/1.0/instances/{name}{qs}")
        if data.get("type") == "sync":
            return data.get("metadata")
        return None

    def get_instance_state(self, name, project=None):
        """Retrieves the state of an instance (CPU, memory, network, etc.)."""
        qs = self._build_project_query(project=project)
        data = self._request("GET", f"/1.0/instances/{name}/state{qs}")
        if data.get("type") == "sync":
            return data.get("metadata")
        return None

    def get_instance_logs(self, name, project=None):
        """
        Retrieves the list of log files for an instance.

        Args:
            name: Instance name
            project: Incus project name

        Returns:
            list: List of log filenames
        """
        try:
            qs = self._build_project_query(project=project)
            data = self._request("GET", f"/1.0/instances/{name}/logs{qs}")
            if data.get("type") == "sync":
                logs = data.get("metadata", [])
                return [log.split("/")[-1] for log in logs]
        except Exception as e:
            logger.debug("Unable to retrieve logs for %s: %s", name, e)
        return []

    def get_instance_log_content(self, name, log_file, project=None):
        """
        Retrieves the content of an instance log file.

        Args:
            name: Instance name
            log_file: Log filename (e.g., 'lxc.log')
            project: Incus project name

        Returns:
            str: Log file content
        """
        try:
            qs = self._build_project_query(project=project)
            url = f"{self.base_url}/1.0/instances/{name}/logs/{log_file}{qs}"
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.debug("Unable to read log %s for %s: %s", log_file, name, e)
        return None

    # ========== Console / Screenshot API ==========

    def get_instance_screenshot(self, name, project=None):
        """
        Captures a VGA console screenshot of a virtual machine.

        Only works for VMs (not containers) that are running.
        Requires Incus >= 6.7 (api extension: instance_console_screenshot).

        Args:
            name: Instance name
            project: Incus project name

        Returns:
            bytes: PNG image data, or None if unavailable
        """
        qs = self._build_project_query("type=vga", project)
        url = f"{self.base_url}/1.0/instances/{name}/console{qs}"

        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()

            content_type = response.headers.get("Content-Type", "")
            if "image" in content_type or response.content[:4] == b"\x89PNG":
                return response.content

            logger.warning(
                "Screenshot for %s: unexpected content type %s", name, content_type
            )
            return None

        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 400:
                logger.debug(
                    "Screenshot not available for %s (possibly a container or stopped VM)",
                    name,
                )
            else:
                logger.warning("HTTP error getting screenshot for %s: %s", name, e)
            return None
        except Exception as e:
            logger.debug("Unable to capture screenshot for %s: %s", name, e)
            return None
