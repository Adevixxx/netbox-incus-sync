from django.urls import include, path
from utilities.urls import get_model_urls
from . import views

app_name = 'netbox_incus_sync'

urlpatterns = [
    # IncusHost URLs
    path('hosts/', views.IncusHostListView.as_view(), name='incushost_list'),
    path('hosts/add/', views.IncusHostEditView.as_view(), name='incushost_add'),
    path('hosts/<int:pk>/', include(get_model_urls('netbox_incus_sync', 'incushost'))),
    
    # Synchronisation
    path('sync/', views.IncusSyncView.as_view(), name='sync'),
    path('sync/events/', views.IncusSyncEventsView.as_view(), name='sync_events'),
]