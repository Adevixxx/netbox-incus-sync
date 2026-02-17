"""
Incus API client package.

The client is split into domain-specific modules for maintainability:
- base.py       — Connection setup, HTTP transport, URL management
- server.py     — Server info, connection testing
- instances.py  — Instance CRUD, logs, screenshots
- cluster.py    — Cluster info, members, groups
- storage.py    — Storage pools, volumes, volume state
- network.py    — Managed networks
- profiles.py   — Profiles
- projects.py   — Projects (namespace isolation)
- operations.py — Async operations
"""

from .base import IncusClientBase
from .server import ServerApiMixin
from .instances import InstancesApiMixin
from .cluster import ClusterApiMixin
from .storage import StorageApiMixin
from .network import NetworkApiMixin
from .profiles import ProfilesApiMixin
from .projects import ProjectsApiMixin
from .operations import OperationsApiMixin


class IncusClient(
    ServerApiMixin,
    InstancesApiMixin,
    ClusterApiMixin,
    StorageApiMixin,
    NetworkApiMixin,
    ProfilesApiMixin,
    ProjectsApiMixin,
    OperationsApiMixin,
    IncusClientBase,
):
    """
    Full Incus API client.
    
    Composes all API domain mixins on top of the base transport layer.
    MRO ensures mixin methods can call self._request() and access
    self.base_url / self.session from IncusClientBase.
    """
    pass


__all__ = ['IncusClient']