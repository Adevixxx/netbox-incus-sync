"""
Incus operations API — list and get async operations.
"""

import logging

logger = logging.getLogger(__name__)


class OperationsApiMixin:
    """Mixin providing operations-related API methods."""

    def get_operations(self, recursion=1):
        """
        Retrieves the list of operations (action history).

        Args:
            recursion: Detail level (0=IDs, 1=full details)

        Returns:
            list: List of operations
        """
        try:
            data = self._request("GET", f"/1.0/operations?recursion={recursion}")
            if data.get("type") == "sync":
                metadata = data.get("metadata", {})

                all_operations = []

                if isinstance(metadata, dict):
                    for status, ops in metadata.items():
                        if isinstance(ops, list):
                            all_operations.extend(ops)
                elif isinstance(metadata, list):
                    all_operations = metadata

                return all_operations
        except Exception as e:
            logger.debug(f"Unable to retrieve operations: {e}")
        return []

    def get_operation(self, operation_id):
        """
        Retrieves details of a specific operation.

        Args:
            operation_id: Operation UUID

        Returns:
            dict: Operation details or None
        """
        try:
            data = self._request("GET", f"/1.0/operations/{operation_id}")
            if data.get("type") == "sync":
                return data.get("metadata")
        except Exception as e:
            logger.debug(f"Operation {operation_id} not found: {e}")
        return None
