"""
GraphQL type definitions for the Incus Sync plugin.

Defines the GraphQL object type for IncusHost, which exposes
all model fields through NetBox's GraphQL API at /graphql/.

NetBoxObjectType automatically provides:
    - Custom fields
    - Tags
    - Created / last_updated timestamps

FK fields (default_cluster, default_site) must be explicitly
typed with Annotated + strawberry.lazy to resolve correctly.
"""

from typing import Annotated, Optional

import strawberry
import strawberry_django
from netbox.graphql.types import NetBoxObjectType
from .. import models


@strawberry_django.type(models.IncusHost, fields='__all__')
class IncusHostType(NetBoxObjectType):
    """
    GraphQL type for IncusHost.

    Example query:
        {
          incus_host_list {
            name
            connection_type
            enabled
            verify_ssl
            default_cluster { name }
            default_site { name }
          }
        }
    """

    # Explicit FK type annotations required by Strawberry
    default_cluster: Optional[
        Annotated["ClusterType", strawberry.lazy("virtualization.graphql.types")]
    ]
    default_site: Optional[
        Annotated["SiteType", strawberry.lazy("dcim.graphql.types")]
    ]