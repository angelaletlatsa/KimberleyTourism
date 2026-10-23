from django.urls import path
from . import views

app_name = 'bookings'

urlpatterns = [
    # Booking (for experiences - backward compatibility)
    #path('book/<int:experience_id>/', views.book_experience, name='book'),
    path('confirmation/<int:booking_id>/', views.booking_confirmation, name='confirmation'),
    path('my/', views.my_bookings, name='my_bookings'),
    path('cancel/<int:booking_id>/', views.cancel_booking, name='cancel'),
    path('detail/<int:booking_id>/', views.booking_detail, name='detail'),
     path('mark-complete/<int:booking_id>/', views.mark_tour_complete, name='mark_complete'),
]