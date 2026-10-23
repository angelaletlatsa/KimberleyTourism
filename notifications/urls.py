from django.urls import path
from . import views

app_name = 'notifications'

urlpatterns = [
    path('', views.my_notifications, name='my_notifications'),
    path('read/<int:notification_id>/', views.mark_read, name='mark_read'),
    path('read-all/', views.mark_all_read, name='mark_all_read'),
    path('unread-count/', views.unread_count, name='unread_count'),
]