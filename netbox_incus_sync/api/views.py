from netbox.api.viewsets import NetBoxModelViewSet
from ..models import IncusHost
from .serializers import IncusHostSerializer


class IncusHostViewSet(NetBoxModelViewSet):
    queryset = IncusHost.objects.all()
    serializer_class = IncusHostSerializer