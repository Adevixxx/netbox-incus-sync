from netbox.api.viewsets import NetBoxModelViewSet
from ..models import IncusHost
from ..filtersets import IncusHostFilterSet
from .serializers import IncusHostSerializer


class IncusHostViewSet(NetBoxModelViewSet):
    queryset = IncusHost.objects.all()
    serializer_class = IncusHostSerializer
    filterset_class = IncusHostFilterSet
