from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Q
from .models import Notification
from .utils import ROLE_NOTIFICATIONS, get_unread_count_for_user


@login_required
def my_notifications(request):
    """View all notifications for the current user (role-filtered)"""
    
    user_role = request.user.profile.role
    allowed_types = ROLE_NOTIFICATIONS.get(user_role, [])
    
    # Filter by role + user
    notifications = Notification.objects.filter(
        recipient=request.user
    ).order_by('-created_at')
    
    # If role has restrictions, filter by type
    if allowed_types:
        notifications = notifications.filter(notification_type__in=allowed_types)
    
    unread_count = get_unread_count_for_user(request.user)
    
    context = {
        'notifications': notifications,
        'unread_count': unread_count,
    }
    
    return render(request, 'list.html', context)


@login_required
def mark_read(request, notification_id):
    """Mark a single notification as read"""
    
    notification = get_object_or_404(
        Notification,
        id=notification_id,
        recipient=request.user
    )
    
    notification.mark_as_read()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    
    return redirect('notifications:my_notifications')


@login_required
def mark_all_read(request):
    """Mark all notifications as read"""
    
    Notification.objects.filter(
        recipient=request.user,
        is_read=False
    ).update(is_read=True, read_at=timezone.now())
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    
    return redirect('notifications:my_notifications')


@login_required
def unread_count(request):
    """Get unread notification count (for AJAX) — role-filtered"""
    
    user_role = request.user.profile.role
    allowed_types = ROLE_NOTIFICATIONS.get(user_role, [])
    
    qs = Notification.objects.filter(
        recipient=request.user,
        is_read=False
    )
    
    if allowed_types:
        qs = qs.filter(notification_type__in=allowed_types)
    
    return JsonResponse({'count': qs.count()})


