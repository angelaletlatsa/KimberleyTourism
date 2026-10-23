from django.urls import path
from . import views

app_name = 'itineraries'

urlpatterns = [
  path('', views.view_itinerary, name='view'),
    path('add/<int:experience_id>/', views.add_item, name='add_item'),
    path('remove/<int:item_id>/', views.remove_item, name='remove'),
    path('delete/<int:itinerary_id>/', views.delete_itinerary, name='delete'),
    
]