from django.urls import path
from django.views.generic import RedirectView
from . import views

app_name = 'admin_dashboard'

urlpatterns = [
    # Root redirect
    path('', RedirectView.as_view(url='/admin_dashboard/dashboard/', permanent=False)),

    # Dashboard
    path('dashboard/', views.dashboard, name='dashboard'),

    # All Users
    path('users/', views.all_users, name='all_users'),
    path('users/<int:user_id>/', views.user_detail, name='user_detail'),
    path(
        'users/<int:profile_id>/promote-admin/',
        views.promote_admin,
        name='promote_admin',
    ),
    path('users/<int:user_id>/suspend/', views.suspend_user, name='suspend_user'),
    path('users/<int:user_id>/unsuspend/', views.unsuspend_user, name='unsuspend_user'),

    # Owner-only administrator management
    path('admins/', views.admin_management, name='admin_management'),
    path('admins/invite/', views.invite_admin, name='invite_admin'),
    path(
        'admins/invitations/<int:invite_id>/revoke/',
        views.revoke_admin_invite,
        name='revoke_admin_invite',
    ),
    path(
        'admins/<int:profile_id>/remove/',
        views.remove_admin,
        name='remove_admin',
    ),

    # Providers
    path('providers/', views.providers, name='providers'),
    path('providers/<int:provider_id>/', views.provider_detail, name='provider_detail'),
    path('action/provider/<int:provider_id>/<str:action>/', views.provider_action, name='provider_action'),

    # Guides
    path('guides/', views.guides, name='guides'),
    path('guides/<int:guide_id>/', views.guide_detail, name='guide_detail'),
    path('action/guide/<int:guide_id>/<str:action>/', views.guide_action, name='guide_action'),

    # Experiences
    path('experiences/', views.experiences, name='experiences'),
    path('experiences/<int:experience_id>/', views.experience_detail, name='experience_detail'),
    path('action/experience/<int:experience_id>/<str:action>/', views.experience_action, name='experience_action'),

    # Reviews
    path('reviews/', views.reviews, name='reviews'),
    path('action/review/<int:review_id>/<str:action>/', views.review_action, name='review_action'),

    # Bookings
    path('bookings/', views.bookings, name='bookings'),
    path('bookings/pending-assignments/', views.pending_assignments, name='pending_assignments'),
    path('bookings/<int:booking_id>/', views.booking_detail, name='booking_detail'),

    # Specific booking action FIRST — must be before <str:action>
    path('action/booking/<int:booking_id>/approve-assignment/', views.approve_assignment, name='approve_assignment'),

    # Generic booking action SECOND
    path('action/booking/<int:booking_id>/<str:action>/', views.booking_action, name='booking_action'),

    # Analytics
    path('analytics/', views.analytics, name='analytics'),

    # Audit Logs
    path('audit-logs/', views.audit_logs, name='audit_logs'),
]