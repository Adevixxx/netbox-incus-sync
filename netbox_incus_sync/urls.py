from django.urls import include, path
from utilities.urls import get_model_urls
from . import views

app_name = 'netbox_incus_sync'

urlpatterns = [
    # IncusHost URLs
    path('hosts/', views.IncusHostListView.as_view(), name='incushost_list'),
    path('hosts/add/', views.IncusHostEditView.as_view(), name='incushost_add'),
    path('hosts/edit/', views.IncusHostBulkEditView.as_view(), name='incushost_bulk_edit'),
    path('hosts/import/', views.IncusHostBulkImportView.as_view(), name='incushost_bulk_import'),
    path('hosts/delete/', views.IncusHostBulkDeleteView.as_view(), name='incushost_bulk_delete'),
    path('hosts/<int:pk>/', include(get_model_urls('netbox_incus_sync', 'incushost'))),
    
    # Synchronization
    path('sync/', views.IncusSyncView.as_view(), name='sync'),
    path('sync/logs/', views.IncusSyncLogsView.as_view(), name='sync_logs'),
    path('sync/host/<int:pk>/', views.IncusSyncHostView.as_view(), name='sync_host'),
    path('sync/hosts/', views.IncusSyncHostView.as_view(), name='sync_hosts_bulk'),
    
    # VM Screenshot
    path('vm/<int:pk>/screenshot/', views.IncusVMScreenshotView.as_view(), name='vm_screenshot'),
    
    # Connection utilities
    path('hosts/<int:pk>/test-connection/', views.IncusHostTestConnectionView.as_view(), name='incushost_test_connection'),
    path('hosts/<int:pk>/test-all-urls/', views.IncusHostTestAllUrlsView.as_view(), name='incushost_test_all_urls'),
    path('hosts/<int:pk>/clear-cache/', views.IncusHostClearCacheView.as_view(), name='incushost_clear_cache'),
]