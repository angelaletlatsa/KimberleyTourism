from django.urls import path
from . import views

app_name = 'provider'

urlpatterns = [
    # Main Pages
    path('dashboard/', views.dashboard, name='dashboard'),
    path('profile/', views.profile, name='profile'),
    path('profile/view/', views.profile_view, name='profile_view'),
    path('profile/edit/', views.profile, name='profile_edit'),
    path('profile/delete/', views.delete_profile, name='delete_profile'),
    path('my-experiences/', views.my_experiences, name='my_experiences'),
    path('create-experience/', views.create_experience, name='create_experience'),
    path('edit-experience/<int:experience_id>/', views.edit_experience, name='edit_experience'),
    path('delete-experience/<int:experience_id>/', views.delete_experience, name='delete_experience'),
    path('bookings/', views.bookings, name='bookings'),
    path('reviews/', views.reviews, name='reviews'),
    path('experience/<int:experience_id>/view/', views.experience_detail, name='experience_detail'),
]