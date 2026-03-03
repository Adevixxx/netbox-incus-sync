"""
GraphQL schema for the Incus Sync plugin.

Registers IncusHostType so it's queryable at /graphql/.
NetBox auto-discovers this schema via the plugin's graphql package.
"""

import strawberry
import strawberry_django
from .types import IncusHostType


@strawberry.type
class IncusSyncQuery:
    incus_host: IncusHostType = strawberry_django.field()
    incus_host_list: list[IncusHostType] = strawberry_django.field()


schema = [IncusSyncQuery]
