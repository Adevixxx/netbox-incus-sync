from netbox.api.routers import NetBoxRouter
from .views import IncusHostViewSet

router = NetBoxRouter()
router.register('hosts', IncusHostViewSet)

urlpatterns = router.urls