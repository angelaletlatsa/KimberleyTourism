from django.urls import path
from . import views

app_name = 'reviews'

urlpatterns = [
    path('create/<int:booking_id>/', views.create_review, name='create'),
    path('my/', views.my_reviews, name='my_reviews'),
    path('experience/<int:experience_id>/', views.experience_reviews, name='experience_reviews'),
]