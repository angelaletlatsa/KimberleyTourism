from django.urls import path
from . import views

app_name = 'tourist'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('experiences-gallery/', views.experiences_gallery, name='experiences_gallery'),
    path('plan-my-trip/', views.plan_my_trip, name='plan_my_trip'),
    
    # Saved Experiences
    path('saved/', views.saved_experiences, name='saved_experiences'),
    path('save/<int:experience_id>/', views.save_experience, name='save_experience'),
    path('unsave/<int:experience_id>/', views.unsave_experience, name='unsave_experience'),
    path('toggle-save/<int:experience_id>/', views.toggle_save_experience, name='toggle_save_experience'),
    
    # Tour Guides
    path('guides/', views.tour_guides, name='tour_guides'),
    path('guides/<int:guide_id>/', views.guide_profile, name='guide_profile'),
    
    # 🔥 NEW: Book Guide Directly
    path('book-guide/<int:guide_id>/', views.book_guide_directly, name='book_guide_directly'),
    
    # Itinerary Actions
    path('add-to-itinerary/<int:experience_id>/', views.add_to_itinerary, name='add_to_itinerary'),
    path('remove-from-itinerary/<int:item_id>/', views.remove_from_itinerary, name='remove_from_itinerary'),
]