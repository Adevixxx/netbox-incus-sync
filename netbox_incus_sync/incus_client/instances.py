"""
Incus instances API — list, get, state, logs, screenshots.
"""

import logging
import requests

logger = logging.getLogger(__name__)


class InstancesApiMixin:
    """Mixin providing instance-related API methods."""

    def get_instances(self, recursion=1):
        """
        Retrieves the list of instances with their details.

        Args:
            recursion: Detail level (0=names, 1=config, 2=full state)
                       Use recursion=2 to get expanded_config and state

        Returns:
            List of instances
        """
        data = self._request('GET', f'/1.0/instances?recursion={recursion}')

        if data.get('type') != 'sync':
            logger.error(f"Unexpected Incus response type: {data.get('type')}")
            return []

        return data.get('metadata', [])

    def get_instance(self, name):
        """Retrieves details of a specific instance."""
        data = self._request('GET', f'/1.0/instances/{name}')
        if data.get('type') == 'sync':
            return data.get('metadata')
        return None

    def get_instance_state(self, name):
        """Retrieves the state of an instance (CPU, memory, network, etc.)."""
        data = self._request('GET', f'/1.0/instances/{name}/state')
        if data.get('type') == 'sync':
            return data.get('metadata')
        return None

    def get_instance_logs(self, name):
        """
        Retrieves the list of log files for an instance.

        Args:
            name: Instance name

        Returns:
            list: List of log filenames
        """
        try:
            data = self._request('GET', f'/1.0/instances/{name}/logs')
            if data.get('type') == 'sync':
                # Logs are returned as URLs, extract names
                logs = data.get('metadata', [])
                return [log.split('/')[-1] for log in logs]
        except Exception as e:
            logger.debug(f"Unable to retrieve logs for {name}: {e}")
        return []

    def get_instance_log_content(self, name, log_file):
        """
        Retrieves the content of an instance log file.

        Args:
            name: Instance name
            log_file: Log filename (e.g., 'lxc.log')

        Returns:
            str: Log file content
        """
        try:
            url = f"{self.base_url}/1.0/instances/{name}/logs/{log_file}"
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.debug(f"Unable to read log {log_file} for {name}: {e}")
        return None

    # ========== Console / Screenshot API ==========

    def get_instance_screenshot(self, name):
        """
        Captures a VGA console screenshot of a virtual machine.

        Only works for VMs (not containers) that are running.
        Uses the GET /1.0/instances/NAME/console?type=vga endpoint
        which returns a PNG image.

        Requires Incus >= 6.7 (api extension: instance_console_screenshot).

        Args:
            name: Instance name

        Returns:
            bytes: PNG image data, or None if unavailable
        """
        url = f"{self.base_url}/1.0/instances/{name}/console?type=vga"

        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()

            # The endpoint returns raw PNG data
            content_type = response.headers.get('Content-Type', '')
            if 'image' in content_type or response.content[:4] == b'\x89PNG':
                return response.content

            # If we got JSON back, it's probably an error
            logger.warning(f"Screenshot for {name}: unexpected content type {content_type}")
            return None

        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 400:
                logger.debug(f"Screenshot not available for {name} (possibly a container or stopped VM)")
            else:
                logger.warning(f"HTTP error getting screenshot for {name}: {e}")
            return None
        except Exception as e:
            logger.debug(f"Unable to capture screenshot for {name}: {e}")
            return None