from django.urls import path
from . import views

app_name = 'experiences'

urlpatterns = [
    path('', views.experience_list, name='list'),
    path('<int:experience_id>/', views.experience_detail, name='detail'),
    path('create/', views.experience_create, name='create'),
    path('my/', views.my_experiences, name='my'),
    path('approve/<int:experience_id>/', views.approve_experience, name='approve'),
]