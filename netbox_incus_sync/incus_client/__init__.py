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
- operations.py — Async operations

The IncusClient class composes all mixins and is the single entry point
used by the rest of the plugin. Import paths are unchanged:

    from .incus_client import IncusClient   # still works
"""

from .base import IncusClientBase
from .server import ServerApiMixin
from .instances import InstancesApiMixin
from .cluster import ClusterApiMixin
from .storage import StorageApiMixin
from .network import NetworkApiMixin
from .profiles import ProfilesApiMixin
from .operations import OperationsApiMixin


class IncusClient(
    ServerApiMixin,
    InstancesApiMixin,
    ClusterApiMixin,
    StorageApiMixin,
    NetworkApiMixin,
    ProfilesApiMixin,
    OperationsApiMixin,
    IncusClientBase,
):
    """
    Full Incus API client.
    
    Composes all API domain mixins on top of the base transport layer.
    MRO ensures mixin methods can call self._request() and access
    self.base_url / self.session from IncusClientBase.
    
    Usage::
    
        from netbox_incus_sync.incus_client import IncusClient
        
        client = IncusClient(host=my_host)
        instances = client.get_instances(recursion=2)
        cluster = client.get_cluster()
    """
    pass


__all__ = ['IncusClient']