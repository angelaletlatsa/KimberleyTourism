from django.urls import path
from . import views

app_name = 'guides'

urlpatterns = [
    # ============ MAIN PAGES ============
    path('dashboard/', views.dashboard, name='dashboard'),
    path('profile/', views.profile, name='profile'),
     path('profile/edit/', views.profile_edit, name='profile_edit'),
    path('availability/', views.availability, name='availability'),
    path('assignments/', views.assignments, name='assignments'),
    path('my-tours/', views.my_tours, name='my_tours'),
    path('tour-detail/<int:booking_id>/', views.tour_detail, name='tour_detail'),
    path('schedule/', views.schedule, name='schedule'),
    path('reviews/', views.reviews, name='reviews'),
    
    # ============ AJAX ACTIONS ============
    path('toggle-availability/', views.toggle_availability, name='toggle_availability'),
    path('accept-booking/', views.accept_booking, name='accept_booking'),
    path('decline-booking/', views.decline_booking, name='decline_booking'),
    path('complete-tour/', views.complete_tour, name='complete_tour'),
]