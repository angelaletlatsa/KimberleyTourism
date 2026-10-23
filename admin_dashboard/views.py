from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Avg, Q, Sum
from django.db.models.functions import TruncDate
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from datetime import timedelta

from .models import AdminAction
from accounts.models import Profile
from tourist.models import TouristProfile
from provider.models import ProviderProfile
from guides.models import GuideProfile
from experiences.models import Experience, Category
from bookings.models import Booking
from reviews.models import Review
from notifications.models import Notification
from notifications.utils import create_notification, get_unread_count_for_user
from accounts.utils import send_suspension_email
from django.contrib.auth.models import User
from accounts.models import AdminInvite
import logging

logger = logging.getLogger(__name__)

# ============ DECORATOR ============
def admin_required(view_func):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts:login')
        if request.user.profile.role != 'admin':
            messages.error(request, 'You do not have permission to access the admin dashboard.')
            return redirect('tourist:dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper


# ============ SIDEBAR COUNTS HELPER ============
def get_sidebar_counts():
    """Get counts for sidebar badges — used by every admin page"""
    return {
        'total_users': Profile.objects.count(),
        'pending_providers_count': ProviderProfile.objects.filter(verification_status='pending').count(),
        'pending_guides_count': GuideProfile.objects.filter(verification_status='pending').count(),
        'pending_experiences_count': Experience.objects.filter(status__in=['submitted', 'under_review']).count(),
        'pending_reviews_count': Review.objects.filter(moderation_status='pending').count(),
        'total_bookings': Booking.objects.count(),
        'pending_assignments_count': Booking.objects.filter(
            status='pending', admin_approved=False
        ).count(),
    }


def log_admin_action(request, action_type, entity_type, entity_id, entity_name='', description='', metadata=None):
    """Log an admin action for audit purposes"""
    AdminAction.objects.create(
        admin=request.user,
        action_type=action_type,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_name=entity_name,
        description=description,
        metadata=metadata or {},
        ip_address=request.META.get('REMOTE_ADDR'),
    )


# ============ DASHBOARD ============

@login_required
@admin_required
def dashboard(request):
    """Admin Dashboard - Analytics-focused overview"""
    now = timezone.now()
    today = now.date()

    total_users = Profile.objects.count()
    total_tourists = Profile.objects.filter(role='tourist').count()
    total_providers = Profile.objects.filter(role='provider').count()
    total_guides = Profile.objects.filter(role='guide').count()

    total_bookings = Booking.objects.count()
    pending_bookings = Booking.objects.filter(status='pending').count()
    confirmed_bookings = Booking.objects.filter(status='confirmed').count()
    completed_bookings = Booking.objects.filter(status='completed').count()
    cancelled_bookings = Booking.objects.filter(status='cancelled').count()
    rejected_bookings = Booking.objects.filter(status='rejected').count()

    approved_reviews = Review.objects.filter(moderation_status='approved').count()
    avg_rating = Review.objects.filter(
        moderation_status='approved'
    ).aggregate(Avg('rating'))['rating__avg'] or 0

    active_experiences = Experience.objects.filter(status='published', is_available=True).count()

    pending_providers_count = ProviderProfile.objects.filter(verification_status='pending').count()
    pending_guides_count = GuideProfile.objects.filter(verification_status='pending').count()
    pending_experiences_count = Experience.objects.filter(status__in=['submitted', 'under_review']).count()
    pending_reviews_count = Review.objects.filter(moderation_status='pending').count()
    pending_actions = pending_providers_count + pending_guides_count + pending_experiences_count + pending_reviews_count

    new_users_today = Profile.objects.filter(created_at__date=today).count()
    new_bookings_today = Booking.objects.filter(created_at__date=today).count()
    new_reviews_today = Review.objects.filter(created_at__date=today).count()

    recent_users = Profile.objects.select_related('user').order_by('-created_at')[:5]
    recent_experiences = Experience.objects.select_related(
        'provider', 'provider__profile', 'provider__profile__user'
    ).order_by('-created_at')[:5]
    recent_bookings_list = Booking.objects.select_related(
        'visitor', 'visitor__profile', 'visitor__profile__user',
        'guide', 'guide__profile', 'guide__profile__user'
    ).order_by('-created_at')[:5]
    recent_reviews_list = Review.objects.select_related(
        'visitor', 'visitor__profile', 'visitor__profile__user',
        'experience', 'guide'
    ).order_by('-created_at')[:5]

    activities = []

    # --- Recent users ---
    for u in recent_users:
        role_label = u.role.title() if u.role else 'User'
        display_name = (
            u.user.get_full_name() or u.user.username
            if u.user else 'Unknown'
        )
        activities.append({
            'type': 'user', 'icon': 'fa-user-plus', 'icon_class': 'user',
            'title': f'New {role_label} registered',
            'description': display_name,
            'created_at': u.created_at,
        })

    # --- Recent experiences (guard against missing provider) ---
    for exp in recent_experiences:
        provider_name = exp.provider.business_name if exp.provider else 'Unknown Provider'
        activities.append({
            'type': 'experience', 'icon': 'fa-suitcase', 'icon_class': 'experience',
            'title': 'New experience created',
            'description': f'{exp.name} by {provider_name}',
            'created_at': exp.created_at,
        })

    # --- Recent bookings (guard against missing guide or visitor) ---
    for b in recent_bookings_list:
        guide_name = b.guide.full_name if b.guide else 'No Guide'
        tourist_name = (
            b.visitor.user.get_full_name() or b.visitor.user.username
            if b.visitor and b.visitor.user else 'Unknown'
        )
        activities.append({
            'type': 'booking', 'icon': 'fa-calendar-check', 'icon_class': 'booking',
            'title': 'New booking',
            'description': f'{tourist_name} → {guide_name}',
            'created_at': b.created_at,
        })

    # --- Recent reviews (guard against missing experience — guide-only reviews) ---
    for r in recent_reviews_list:
        if r.experience:
            subject = r.experience.name
        elif r.guide:
            subject = r.guide.full_name
        else:
            subject = 'Unknown'

        activities.append({
            'type': 'review', 'icon': 'fa-star', 'icon_class': 'review',
            'title': 'New review submitted',
            'description': f'{r.rating}★ for {subject}',
            'created_at': r.created_at,
        })

    activities.sort(key=lambda x: x['created_at'], reverse=True)
    recent_activities = activities[:10]

    recent_experiences_table = Experience.objects.select_related(
        'provider', 'provider__profile', 'provider__profile__user', 'category'
    ).order_by('-created_at')[:5]

    top_provider = ProviderProfile.objects.annotate(
        booking_count=Count('experiences__bookings')
    ).order_by('-booking_count', '-average_rating').first()

    top_guide = GuideProfile.objects.annotate(
        booking_count=Count('bookings')
    ).order_by('-booking_count', '-average_rating').first()

    top_experience = Experience.objects.annotate(
        booking_count=Count('bookings')
    ).order_by('-booking_count', '-average_rating').first()

    has_top_performers = (
        (top_provider and top_provider.booking_count > 0) or
        (top_guide and top_guide.booking_count > 0) or
        (top_experience and top_experience.booking_count > 0)
    )

    today_dt = timezone.now().date()
    start_7 = today_dt - timedelta(days=6)
    date_range_7 = [start_7 + timedelta(days=i) for i in range(7)]

    users_7 = Profile.objects.filter(
        created_at__date__gte=start_7
    ).annotate(day=TruncDate('created_at')).values('day').annotate(count=Count('id'))
    users_7_dict = {item['day']: item['count'] for item in users_7}
    sparkline_users = [users_7_dict.get(d, 0) for d in date_range_7]

    bookings_7 = Booking.objects.filter(
        created_at__date__gte=start_7
    ).annotate(day=TruncDate('created_at')).values('day').annotate(count=Count('id'))
    bookings_7_dict = {item['day']: item['count'] for item in bookings_7}
    sparkline_bookings = [bookings_7_dict.get(d, 0) for d in date_range_7]

    reviews_7 = Review.objects.filter(
        created_at__date__gte=start_7
    ).annotate(day=TruncDate('created_at')).values('day').annotate(count=Count('id'))
    reviews_7_dict = {item['day']: item['count'] for item in reviews_7}
    sparkline_reviews = [reviews_7_dict.get(d, 0) for d in date_range_7]

    start_30 = today_dt - timedelta(days=29)
    date_range_30 = [start_30 + timedelta(days=i) for i in range(30)]

    users_30 = Profile.objects.filter(
        created_at__date__gte=start_30
    ).annotate(day=TruncDate('created_at')).values('day').annotate(count=Count('id'))
    users_30_dict = {item['day']: item['count'] for item in users_30}

    bookings_30 = Booking.objects.filter(
        created_at__date__gte=start_30
    ).annotate(day=TruncDate('created_at')).values('day').annotate(count=Count('id'))
    bookings_30_dict = {item['day']: item['count'] for item in bookings_30}

    reviews_30 = Review.objects.filter(
        created_at__date__gte=start_30
    ).annotate(day=TruncDate('created_at')).values('day').annotate(count=Count('id'))
    reviews_30_dict = {item['day']: item['count'] for item in reviews_30}

    daily_labels = [d.strftime('%b %d') for d in date_range_30]
    daily_users = [users_30_dict.get(d, 0) for d in date_range_30]
    daily_bookings = [bookings_30_dict.get(d, 0) for d in date_range_30]
    daily_reviews = [reviews_30_dict.get(d, 0) for d in date_range_30]

    sidebar_counts = get_sidebar_counts()

    context = {
        'user': request.user,
        'profile': request.user.profile,
        'now': now,
        'unread_count': get_unread_count_for_user(request.user),

        'total_users': total_users,
        'total_tourists': total_tourists,
        'total_providers': total_providers,
        'total_guides': total_guides,
        'total_bookings': total_bookings,
        'avg_rating': avg_rating,
        'pending_actions': pending_actions,
        'approved_reviews_count': approved_reviews,
        'completed_bookings': completed_bookings,
        'cancelled_bookings': cancelled_bookings,
        'active_experiences': active_experiences,

        'new_users_today': new_users_today,
        'new_bookings_today': new_bookings_today,
        'new_reviews_today': new_reviews_today,

        'sparkline_users': sparkline_users,
        'sparkline_bookings': sparkline_bookings,
        'sparkline_reviews': sparkline_reviews,

        'daily_labels': daily_labels,
        'daily_users': daily_users,
        'daily_bookings': daily_bookings,
        'daily_reviews': daily_reviews,

        'weekly_labels': daily_labels,
        'weekly_users': daily_users,
        'weekly_bookings': daily_bookings,
        'weekly_reviews': daily_reviews,

        'monthly_labels': daily_labels,
        'monthly_users': daily_users,
        'monthly_bookings': daily_bookings,
        'monthly_reviews': daily_reviews,

        'recent_activities': recent_activities,
        'recent_experiences_table': recent_experiences_table,

        'top_provider': top_provider,
        'top_guide': top_guide,
        'top_experience': top_experience,
        'has_top_performers': has_top_performers,

        'bookings_by_status': {
            'pending': pending_bookings,
            'confirmed': confirmed_bookings,
            'completed': completed_bookings,
            'cancelled': cancelled_bookings,
            'rejected': rejected_bookings,
        },

        **sidebar_counts,
    }

    return render(request, 'admin_dashboard/dashboard.html', context)


# ============ ALL USERS ============

@login_required
@admin_required
def all_users(request):
    """All Users - Overview + Moderation"""

    role_filter = request.GET.get('role', 'all')
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', 'all')

    users_qs = Profile.objects.select_related('user').order_by('-created_at')

    if role_filter != 'all':
        users_qs = users_qs.filter(role=role_filter)

    if status_filter == 'active':
        users_qs = users_qs.filter(is_suspended=False, user__is_active=True)
    elif status_filter == 'suspended':
        users_qs = users_qs.filter(is_suspended=True)
    elif status_filter == 'inactive':
        users_qs = users_qs.filter(user__is_active=False)

    if search_query:
        users_qs = users_qs.filter(
            Q(user__first_name__icontains=search_query) |
            Q(user__last_name__icontains=search_query) |
            Q(user__username__icontains=search_query) |
            Q(user__email__icontains=search_query)
        )

    all_profiles = Profile.objects.all()
    counts = {
        'all': all_profiles.count(),
        'tourist': all_profiles.filter(role='tourist').count(),
        'provider': all_profiles.filter(role='provider').count(),
        'guide': all_profiles.filter(role='guide').count(),
        'admin': all_profiles.filter(role='admin').count(),
    }

    paginator = Paginator(users_qs, 20)
    users = paginator.get_page(request.GET.get('page'))

    context = {
        'user': request.user,
        'profile': request.user.profile,
        'users': users,
        'counts': counts,
        'current_role': role_filter,
        'current_status': status_filter,
        'search': search_query,
        'now': timezone.now(),
        'unread_count': get_unread_count_for_user(request.user),
        **get_sidebar_counts(),
    }

    return render(request, 'admin_dashboard/users.html', context)


@login_required
@admin_required
def user_detail(request, user_id):
    """View a single user's details"""

    user_obj = get_object_or_404(Profile.objects.select_related('user'), id=user_id)

    stats = {}
    activity = []

    if user_obj.role == 'tourist':
        try:
            tourist = user_obj.tourist_profile
            bookings = Booking.objects.filter(visitor=tourist).order_by('-created_at')
            reviews = Review.objects.filter(visitor=tourist).order_by('-created_at')
            stats = {
                'Total Bookings': bookings.count(),
                'Completed Tours': bookings.filter(status='completed').count(),
                'Total Reviews': reviews.count(),
            }
            for b in bookings[:5]:
                activity.append({
                    'icon': 'fa-calendar-check', 'icon_class': 'booking',
                    'title': 'Booking',
                    'description': f'On {b.booking_date.strftime("%d %b %Y")}',
                    'created_at': b.created_at,
                })
            for r in reviews[:5]:
                subject = r.experience.name if r.experience else (r.guide.full_name if r.guide else 'Unknown')
                activity.append({
                    'icon': 'fa-star', 'icon_class': 'review',
                    'title': f'Review ({r.rating}★)',
                    'description': subject,
                    'created_at': r.created_at,
                })
        except Exception:
            pass

    elif user_obj.role == 'provider':
        try:
            provider = user_obj.provider_profile
            experiences = Experience.objects.filter(provider=provider)
            stats = {
                'Total Experiences': experiences.count(),
                'Published': experiences.filter(status='published').count(),
                'Verification': provider.get_verification_status_display(),
            }
            for exp in experiences.order_by('-created_at')[:5]:
                activity.append({
                    'icon': 'fa-suitcase', 'icon_class': 'experience',
                    'title': 'Experience created',
                    'description': exp.name,
                    'created_at': exp.created_at,
                })
        except Exception:
            pass

    elif user_obj.role == 'guide':
        try:
            guide = user_obj.guide_profile
            bookings = Booking.objects.filter(guide=guide).order_by('-created_at')
            stats = {
                'Total Bookings': bookings.count(),
                'Completed Tours': bookings.filter(status='completed').count(),
                'Verification': guide.get_verification_status_display(),
                'Rating': f"{guide.average_rating:.1f} ★",
            }
            for b in bookings[:5]:
                activity.append({
                    'icon': 'fa-calendar-check', 'icon_class': 'booking',
                    'title': 'Booking received',
                    'description': f'On {b.booking_date.strftime("%d %b %Y")}',
                    'created_at': b.created_at,
                })
        except Exception:
            pass

    elif user_obj.role == 'admin':
        try:
            admin_actions = AdminAction.objects.filter(
                admin=user_obj.user
            ).order_by('-created_at')
            stats = {
                'Total Actions': admin_actions.count(),
                'Providers Verified': admin_actions.filter(action_type='approve_provider').count(),
                'Guides Verified': admin_actions.filter(action_type='approve_guide').count(),
                'Experiences Approved': admin_actions.filter(action_type='approve_experience').count(),
            }
            for action in admin_actions[:5]:
                activity.append({
                    'icon': 'fa-shield-alt', 'icon_class': 'experience',
                    'title': action.get_action_type_display(),
                    'description': action.entity_name or action.entity_type,
                    'created_at': action.created_at,
                })
        except Exception:
            pass

    activity.sort(key=lambda x: x['created_at'], reverse=True)

    sidebar_counts = get_sidebar_counts()

    context = {
        'user': request.user,
        'profile': request.user.profile,
        'user_obj': user_obj,
        'stats': stats,
        'activity': activity[:10],
        'now': timezone.now(),
        'unread_count': get_unread_count_for_user(request.user),
        **sidebar_counts,
    }

    return render(request, 'admin_dashboard/user_detail.html', context)


# ============ PROVIDERS ============

@login_required
@admin_required
def providers(request):
    """Provider review and moderation list."""
    status_filter = request.GET.get('status', 'all')
    search_query = request.GET.get('search', '').strip()

    qs = ProviderProfile.objects.select_related('profile', 'profile__user').order_by('-created_at')

    if status_filter == 'suspended':
        qs = qs.filter(Q(verification_status='suspended') | Q(is_suspended=True))
    elif status_filter != 'all':
        qs = qs.filter(verification_status=status_filter)

    if search_query:
        qs = qs.filter(
            Q(business_name__icontains=search_query) |
            Q(profile__user__first_name__icontains=search_query) |
            Q(profile__user__last_name__icontains=search_query) |
            Q(profile__user__username__icontains=search_query) |
            Q(profile__user__email__icontains=search_query) |
            Q(contact_email__icontains=search_query)
        )

    counts = {
        'all': ProviderProfile.objects.count(),
        'pending': ProviderProfile.objects.filter(verification_status='pending').count(),
        'approved': ProviderProfile.objects.filter(verification_status='approved').count(),
        'rejected': ProviderProfile.objects.filter(verification_status='rejected').count(),
        'suspended': ProviderProfile.objects.filter(Q(verification_status='suspended') | Q(is_suspended=True)).count(),
    }

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'user': request.user,
        'profile': request.user.profile,
        'providers': page_obj,
        'counts': counts,
        'current_status': status_filter,
        'search': search_query,
        'now': timezone.now(),
        'unread_count': get_unread_count_for_user(request.user),
        **get_sidebar_counts(),
    }
    return render(request, 'admin_dashboard/providers.html', context)


@login_required
@admin_required
def provider_detail(request, provider_id):
    """Provider detail view — full business info + history"""
    provider = get_object_or_404(
        ProviderProfile.objects.select_related('profile', 'profile__user'),
        id=provider_id
    )

    experiences = Experience.objects.filter(provider=provider).order_by('-created_at')
    recent_actions = AdminAction.objects.filter(
        entity_type='ProviderProfile',
        entity_id=provider.id
    ).order_by('-created_at')[:10]

    sidebar_counts = get_sidebar_counts()

    context = {
        'user': request.user,
        'profile': request.user.profile,
        'provider': provider,
        'experiences': experiences,
        'recent_actions': recent_actions,
        'now': timezone.now(),
        'unread_count': get_unread_count_for_user(request.user),
        **sidebar_counts,
    }

    return render(request, 'admin_dashboard/provider_detail.html', context)


@login_required
@admin_required
@require_POST
def provider_action(request, provider_id, action):
    """Handle provider approve / reject / suspend / restore via AJAX"""

    provider = get_object_or_404(ProviderProfile, id=provider_id)
    reason = request.POST.get('reason', '').strip()

    try:
        if action == 'approve':
            provider.verification_status = 'approved'
            provider.verified_at = timezone.now()
            provider.verified_by = request.user
            provider.save()

            log_admin_action(
                request,
                action_type='approve_provider',
                entity_type='ProviderProfile',
                entity_id=provider.id,
                entity_name=provider.business_name,
                description='Approved provider',
            )

            try:
                create_notification(
                    recipient=provider.profile.user,
                    notification_type='provider_approved',
                    title='Business Approved',
                    message=f'Your business "{provider.business_name}" has been approved.',
                    entity_type='ProviderProfile',
                    entity_id=provider.id,
                )
            except Exception:
                pass

            return JsonResponse({'success': True, 'message': f'{provider.business_name} approved.'})

        elif action == 'reject':
            if not reason:
                return JsonResponse({'success': False, 'error': 'Rejection reason is required.'}, status=400)

            provider.verification_status = 'rejected'
            provider.verification_notes = reason
            provider.save()

            log_admin_action(
                request,
                action_type='reject_provider',
                entity_type='ProviderProfile',
                entity_id=provider.id,
                entity_name=provider.business_name,
                description=f'Rejected. Reason: {reason}',
            )

            try:
                create_notification(
                    recipient=provider.profile.user,
                    notification_type='provider_rejected',
                    title='Business Application Rejected',
                    message=f'Your business "{provider.business_name}" was rejected. Reason: {reason}',
                    entity_type='ProviderProfile',
                    entity_id=provider.id,
                )
            except Exception:
                pass

            return JsonResponse({'success': True, 'message': f'{provider.business_name} rejected.'})

        elif action == 'suspend':
            if not reason:
                return JsonResponse({'success': False, 'error': 'Suspension reason is required.'}, status=400)

            provider.verification_status = 'suspended'
            provider.is_suspended = True
            provider.suspension_reason = reason
            provider.suspended_at = timezone.now()
            provider.suspended_by = request.user
            provider.save()

            Experience.objects.filter(provider=provider).update(
                status='suspended',
                is_available=False
            )

            log_admin_action(
                request,
                action_type='suspend_provider',
                entity_type='ProviderProfile',
                entity_id=provider.id,
                entity_name=provider.business_name,
                description=f'Suspended. Reason: {reason}',
            )

            try:
                create_notification(
                    recipient=provider.profile.user,
                    notification_type='provider_suspended',
                    title='Business Suspended',
                    message=f'Your business "{provider.business_name}" has been suspended. Reason: {reason}',
                    entity_type='ProviderProfile',
                    entity_id=provider.id,
                )
            except Exception:
                pass

            return JsonResponse({'success': True, 'message': f'{provider.business_name} suspended.'})

        elif action == 'restore':
            provider.verification_status = 'pending'
            provider.is_suspended = False
            provider.suspension_reason = ''
            provider.suspended_at = None
            provider.suspended_by = None
            provider.save()

            log_admin_action(
                request,
                action_type='approve_provider',
                entity_type='ProviderProfile',
                entity_id=provider.id,
                entity_name=provider.business_name,
                description='Restored to pending',
            )

            try:
                create_notification(
                    recipient=provider.profile.user,
                    notification_type='provider_restored',
                    title='Business Profile Restored',
                    message=f'Your business "{provider.business_name}" has been restored and is pending review.',
                    entity_type='ProviderProfile',
                    entity_id=provider.id,
                )
            except Exception:
                pass

            return JsonResponse({'success': True, 'message': f'{provider.business_name} restored to pending.'})

        else:
            return JsonResponse({'success': False, 'error': 'Invalid action.'}, status=400)

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ============ GUIDES ============

@login_required
@admin_required
def guides(request):
    """Guide verification and moderation list."""
    status_filter = request.GET.get('status', 'all')
    search_query = request.GET.get('search', '').strip()

    qs = GuideProfile.objects.select_related('profile', 'profile__user').order_by('-created_at')

    if status_filter == 'suspended':
        qs = qs.filter(Q(verification_status='suspended') | Q(is_suspended=True))
    elif status_filter != 'all':
        qs = qs.filter(verification_status=status_filter)

    if search_query:
        qs = qs.filter(
            Q(profile__user__first_name__icontains=search_query) |
            Q(profile__user__last_name__icontains=search_query) |
            Q(profile__user__username__icontains=search_query) |
            Q(profile__user__email__icontains=search_query) |
            Q(biography__icontains=search_query)
        )

    counts = {
        'all': GuideProfile.objects.count(),
        'pending': GuideProfile.objects.filter(verification_status='pending').count(),
        'approved': GuideProfile.objects.filter(verification_status='approved').count(),
        'rejected': GuideProfile.objects.filter(verification_status='rejected').count(),
        'suspended': GuideProfile.objects.filter(Q(verification_status='suspended') | Q(is_suspended=True)).count(),
    }

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'user': request.user,
        'profile': request.user.profile,
        'guides': page_obj,
        'counts': counts,
        'current_status': status_filter,
        'search': search_query,
        'now': timezone.now(),
        'unread_count': get_unread_count_for_user(request.user),
        **get_sidebar_counts(),
    }
    return render(request, 'admin_dashboard/guides.html', context)


@login_required
@admin_required
def guide_detail(request, guide_id):
    """Guide detail view — full profile info + tours + reviews + history"""
    guide = get_object_or_404(
        GuideProfile.objects.select_related('profile', 'profile__user'),
        id=guide_id
    )

    bookings = Booking.objects.filter(
        guide=guide
    ).select_related(
        'visitor', 'visitor__profile', 'visitor__profile__user', 'experience'
    ).order_by('-created_at')[:10]

    reviews = Review.objects.filter(
        guide=guide,
        review_type='guide',
        moderation_status='approved'
    ).select_related(
        'visitor', 'visitor__profile', 'visitor__profile__user', 'experience'
    ).order_by('-created_at')[:5]

    recent_actions = AdminAction.objects.filter(
        entity_type='GuideProfile',
        entity_id=guide.id
    ).order_by('-created_at')[:10]

    total_bookings = Booking.objects.filter(guide=guide).count()
    completed_tours = Booking.objects.filter(guide=guide, status='completed').count()
    total_reviews = Review.objects.filter(
        guide=guide,
        review_type='guide',
        moderation_status='approved'
    ).count()

    sidebar_counts = get_sidebar_counts()

    context = {
        'user': request.user,
        'profile': request.user.profile,
        'guide': guide,
        'bookings': bookings,
        'reviews': reviews,
        'recent_actions': recent_actions,
        'total_bookings': total_bookings,
        'completed_tours': completed_tours,
        'total_reviews': total_reviews,
        'now': timezone.now(),
        'unread_count': get_unread_count_for_user(request.user),
        **sidebar_counts,
    }

    return render(request, 'admin_dashboard/guide_detail.html', context)


@login_required
@admin_required
@require_POST
def guide_action(request, guide_id, action):
    """Handle guide approve / reject / suspend / restore via AJAX"""

    guide = get_object_or_404(GuideProfile, id=guide_id)
    reason = request.POST.get('reason', '').strip()

    try:
        if action == 'approve':
            guide.verification_status = 'approved'
            guide.verified_at = timezone.now()
            guide.verified_by = request.user
            guide.save()

            log_admin_action(
                request,
                action_type='approve_guide',
                entity_type='GuideProfile',
                entity_id=guide.id,
                entity_name=guide.full_name,
                description='Approved guide',
            )

            try:
                create_notification(
                    recipient=guide.profile.user,
                    notification_type='guide_approved',
                    title='You Are Now Verified',
                    message='Your guide profile has been verified. You can now accept bookings.',
                    entity_type='GuideProfile',
                    entity_id=guide.id,
                )
            except Exception:
                pass

            return JsonResponse({'success': True, 'message': f'{guide.full_name} approved.'})

        elif action == 'reject':
            if not reason:
                return JsonResponse({'success': False, 'error': 'Rejection reason is required.'}, status=400)

            guide.verification_status = 'rejected'
            guide.verification_notes = reason
            guide.save()

            log_admin_action(
                request,
                action_type='reject_guide',
                entity_type='GuideProfile',
                entity_id=guide.id,
                entity_name=guide.full_name,
                description=f'Rejected. Reason: {reason}',
            )

            try:
                create_notification(
                    recipient=guide.profile.user,
                    notification_type='guide_rejected',
                    title='Profile Verification Rejected',
                    message=f'Your guide profile was rejected. Reason: {reason}',
                    entity_type='GuideProfile',
                    entity_id=guide.id,
                )
            except Exception:
                pass

            return JsonResponse({'success': True, 'message': f'{guide.full_name} rejected.'})

        elif action == 'suspend':
            if not reason:
                return JsonResponse({'success': False, 'error': 'Suspension reason is required.'}, status=400)

            guide.verification_status = 'suspended'
            guide.is_suspended = True
            guide.is_available = False
            guide.suspension_reason = reason
            guide.suspended_at = timezone.now()
            guide.suspended_by = request.user
            guide.save()

            log_admin_action(
                request,
                action_type='suspend_guide',
                entity_type='GuideProfile',
                entity_id=guide.id,
                entity_name=guide.full_name,
                description=f'Suspended. Reason: {reason}',
            )

            try:
                create_notification(
                    recipient=guide.profile.user,
                    notification_type='guide_suspended',
                    title='Account Suspended',
                    message=f'Your guide account has been suspended. Reason: {reason}',
                    entity_type='GuideProfile',
                    entity_id=guide.id,
                )
            except Exception:
                pass

            return JsonResponse({'success': True, 'message': f'{guide.full_name} suspended.'})

        elif action == 'restore':
            guide.verification_status = 'pending'
            guide.is_suspended = False
            guide.suspension_reason = ''
            guide.suspended_at = None
            guide.suspended_by = None
            guide.save()

            log_admin_action(
                request,
                action_type='approve_guide',
                entity_type='GuideProfile',
                entity_id=guide.id,
                entity_name=guide.full_name,
                description='Restored to pending',
            )

            return JsonResponse({'success': True, 'message': f'{guide.full_name} restored to pending.'})

        else:
            return JsonResponse({'success': False, 'error': 'Invalid action.'}, status=400)

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ============ EXPERIENCES ============

@login_required
@admin_required
def experiences(request):
    """Experience moderation list."""
    status_filter = request.GET.get('status', 'all')
    search_query = request.GET.get('search', '').strip()

    qs = Experience.objects.select_related(
        'provider', 'provider__profile', 'provider__profile__user', 'category'
    ).order_by('-created_at')

    if status_filter != 'all':
        qs = qs.filter(status=status_filter)

    if search_query:
        qs = qs.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(provider__business_name__icontains=search_query) |
            Q(category__name__icontains=search_query)
        )

    counts = {
        'all': Experience.objects.count(),
        'submitted': Experience.objects.filter(status='submitted').count(),
        'under_review': Experience.objects.filter(status='under_review').count(),
        'approved': Experience.objects.filter(status='approved').count(),
        'published': Experience.objects.filter(status='published').count(),
        'suspended': Experience.objects.filter(status='suspended').count(),
        'archived': Experience.objects.filter(status='archived').count(),
    }

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'user': request.user,
        'profile': request.user.profile,
        'experiences': page_obj,
        'counts': counts,
        'current_status': status_filter,
        'search': search_query,
        'now': timezone.now(),
        'unread_count': get_unread_count_for_user(request.user),
        **get_sidebar_counts(),
    }
    return render(request, 'admin_dashboard/experiences.html', context)


# ============ REVIEWS ============

@login_required
@admin_required
def reviews(request):
    """Review moderation list."""
    status_filter = request.GET.get('status', 'all')
    search_query = request.GET.get('search', '').strip()

    qs = Review.objects.select_related(
        'visitor', 'visitor__profile', 'visitor__profile__user',
        'experience', 'guide'
    ).order_by('-created_at')

    if status_filter != 'all':
        qs = qs.filter(moderation_status=status_filter)

    if search_query:
        qs = qs.filter(
            Q(title__icontains=search_query) |
            Q(comment__icontains=search_query) |
            Q(experience__name__icontains=search_query) |
            Q(visitor__profile__user__first_name__icontains=search_query) |
            Q(visitor__profile__user__last_name__icontains=search_query) |
            Q(visitor__profile__user__username__icontains=search_query)
        )

    counts = {
        'all': Review.objects.count(),
        'pending': Review.objects.filter(moderation_status='pending').count(),
        'approved': Review.objects.filter(moderation_status='approved').count(),
        'rejected': Review.objects.filter(moderation_status='rejected').count(),
        'reported': Review.objects.filter(moderation_status='reported').count(),
        'removed': Review.objects.filter(moderation_status='removed').count(),
    }

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'user': request.user,
        'profile': request.user.profile,
        'reviews': page_obj,
        'counts': counts,
        'current_status': status_filter,
        'search': search_query,
        'now': timezone.now(),
        'unread_count': get_unread_count_for_user(request.user),
        **get_sidebar_counts(),
    }
    return render(request, 'admin_dashboard/reviews.html', context)


# ============ BOOKINGS ============

@login_required
@admin_required
def bookings(request):
    """Booking overview list."""
    status_filter = request.GET.get('status', 'all')
    search_query = request.GET.get('search', '').strip()

    qs = Booking.objects.select_related(
        'visitor', 'visitor__profile', 'visitor__profile__user',
        'guide', 'guide__profile', 'guide__profile__user',
        'experience'
    ).order_by('-created_at')

    if status_filter != 'all':
        qs = qs.filter(status=status_filter)

    if search_query:
        qs = qs.filter(
            Q(experience__name__icontains=search_query) |
            Q(visitor__profile__user__first_name__icontains=search_query) |
            Q(visitor__profile__user__last_name__icontains=search_query) |
            Q(visitor__profile__user__username__icontains=search_query) |
            Q(guide__profile__user__first_name__icontains=search_query) |
            Q(guide__profile__user__last_name__icontains=search_query)
        )

    counts = {
        'all': Booking.objects.count(),
        'pending': Booking.objects.filter(status='pending').count(),
        'confirmed': Booking.objects.filter(status='confirmed').count(),
        'completed': Booking.objects.filter(status='completed').count(),
        'cancelled': Booking.objects.filter(status='cancelled').count(),
        'rejected': Booking.objects.filter(status='rejected').count(),
        'no_show': Booking.objects.filter(status='no_show').count(),
    }

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'user': request.user,
        'profile': request.user.profile,
        'bookings': page_obj,
        'counts': counts,
        'current_status': status_filter,
        'search': search_query,
        'now': timezone.now(),
        'unread_count': get_unread_count_for_user(request.user),
        **get_sidebar_counts(),
    }
    return render(request, 'admin_dashboard/bookings.html', context)


# ============ PENDING ASSIGNMENTS (CLASH-AWARE) ============

@login_required
@admin_required
def pending_assignments(request):
    """
    FR-06.1: Admin Confirms Guide Assignments
    Traceability: UC-06.1 Confirm Assignment
    """
    sort_mode = request.GET.get('sort', 'rating')
    if sort_mode not in ('rating', 'name', 'specialization'):
        sort_mode = 'rating'

    show_param = request.GET.get('show', '5')
    show_all = (show_param == 'all')
    try:
        show_limit = int(show_param) if not show_all else 0
    except (ValueError, TypeError):
        show_limit = 5

    qs = Booking.objects.filter(
        status='pending',
        admin_approved=False
    ).select_related(
        'visitor', 'visitor__profile', 'visitor__profile__user',
        'guide', 'guide__profile', 'guide__profile__user',
        'experience'
    ).order_by('booking_date', 'booking_time')

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    all_guides = GuideProfile.objects.filter(
        verification_status='approved',
        is_active=True,
        is_suspended=False,
    ).select_related('profile', 'profile__user')

    bookings_with_info = []
    for booking in page_obj:
        preferred_clash = None
        if booking.guide:
            preferred_clash = booking.check_clash(
                booking.guide,
                booking.booking_date,
                booking.booking_time,
            )

        alternatives = []
        for g in all_guides:
            if booking.guide and g.id == booking.guide.id:
                continue
            clash = booking.check_clash(g, booking.booking_date, booking.booking_time)
            alternatives.append({
                'guide': g,
                'clash': clash,
            })

        if sort_mode == 'name':
            alternatives.sort(key=lambda x: x['guide'].full_name.lower())
        elif sort_mode == 'specialization':
            alternatives.sort(
                key=lambda x: (
                    -len(x['guide'].specializations or []),
                    -float(x['guide'].average_rating or 0),
                    x['guide'].full_name.lower(),
                )
            )
        else:
            alternatives.sort(
                key=lambda x: (
                    -float(x['guide'].average_rating or 0),
                    -x['guide'].total_tours_given,
                    x['guide'].full_name.lower(),
                )
            )

        if not show_all and show_limit > 0:
            alternatives_display = alternatives[:show_limit]
        else:
            alternatives_display = alternatives

        bookings_with_info.append({
            'booking': booking,
            'preferred_clash': preferred_clash,
            'alternatives': alternatives_display,
            'alternatives_total': len(alternatives),
        })

    sidebar_counts = get_sidebar_counts()

    context = {
        'user': request.user,
        'profile': request.user.profile,
        'bookings_with_info': bookings_with_info,
        'page_obj': page_obj,
        'total_pending': qs.count(),
        'current_sort': sort_mode,
        'current_show': show_param,
        'show_all': show_all,
        'now': timezone.now(),
        'unread_count': get_unread_count_for_user(request.user),
        **sidebar_counts,
    }
    return render(request, 'admin_dashboard/pending_assignments.html', context)


@login_required
@admin_required
@require_POST
def approve_assignment(request, booking_id):
    """Admin confirms the guide assignment for a booking."""
    wants_json = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    booking = get_object_or_404(
        Booking.objects.select_related(
            'guide', 'visitor', 'visitor__profile', 'experience'
        ),
        id=booking_id
    )

    if not booking.can_admin_approve:
        error = f'Booking is not awaiting approval (status: {booking.status})'
        if not wants_json:
            messages.error(request, error)
            return redirect('admin_dashboard:pending_assignments')
        return JsonResponse({'success': False, 'error': error}, status=400)

    guide_id = request.POST.get('guide_id')
    if guide_id:
        alternative = get_object_or_404(
            GuideProfile.objects.select_related('profile', 'profile__user'),
            id=guide_id,
            verification_status='approved',
            is_active=True,
            is_suspended=False,
        )

        clash = booking.check_clash(
            alternative,
            booking.booking_date,
            booking.booking_time,
        )
        if clash['severity'] == 'blocker':
            error = f'Cannot assign {alternative.full_name}: {clash["reason"]}'
            if not wants_json:
                messages.error(request, error)
                return redirect('admin_dashboard:pending_assignments')
            return JsonResponse({'success': False, 'error': error}, status=400)

        booking.guide = alternative
        booking.save(update_fields=['guide', 'updated_at'])

    try:
        booking.admin_approve(admin_user=request.user)

        log_admin_action(
            request,
            action_type='other',
            entity_type='Booking',
            entity_id=booking.id,
            entity_name=f'Booking #{booking.id}',
            description=f'Confirmed guide assignment to {booking.guide.full_name if booking.guide else "N/A"}',
        )

        success_message = (
            f'Assignment confirmed. '
            f'{booking.guide.full_name if booking.guide else "Guide"} has been notified.'
        )

        if not wants_json:
            messages.success(request, success_message)
            return redirect('admin_dashboard:pending_assignments')

        return JsonResponse({'success': True, 'message': success_message})

    except Exception as e:
        if not wants_json:
            messages.error(request, f'Could not confirm the assignment: {e}')
            return redirect('admin_dashboard:pending_assignments')
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@admin_required
def booking_detail(request, booking_id):
    """Booking detail view — read-only + admin override actions"""
    booking = get_object_or_404(
        Booking.objects.select_related(
            'visitor', 'visitor__profile', 'visitor__profile__user',
            'guide', 'guide__profile', 'guide__profile__user',
            'experience', 'cancelled_by'
        ),
        id=booking_id
    )

    sidebar_counts = get_sidebar_counts()

    context = {
        'user': request.user,
        'profile': request.user.profile,
        'booking': booking,
        'now': timezone.now(),
        'unread_count': get_unread_count_for_user(request.user),
        **sidebar_counts,
    }

    return render(request, 'admin_dashboard/booking_detail.html', context)


@login_required
@admin_required
@require_POST
def booking_action(request, booking_id, action):
    """Handle admin overrides: cancel booking / mark no-show"""
    booking = get_object_or_404(Booking, id=booking_id)
    reason = request.POST.get('reason', '').strip()

    try:
        if action == 'cancel':
            if not reason:
                return JsonResponse({'success': False, 'error': 'Cancellation reason is required.'}, status=400)

            if booking.status not in ['pending', 'confirmed']:
                return JsonResponse({'success': False, 'error': f'Cannot cancel a booking with status: {booking.status}'}, status=400)

            booking.status = 'cancelled'
            booking.cancellation_reason = reason
            booking.cancelled_at = timezone.now()
            booking.cancelled_by = request.user
            booking.save()

            log_admin_action(
                request,
                action_type='other',
                entity_type='Booking',
                entity_id=booking.id,
                entity_name=f'Booking #{booking.id}',
                description=f'Admin cancelled booking. Reason: {reason}',
            )

            try:
                create_notification(
                    recipient=booking.visitor.profile.user,
                    notification_type='booking_cancelled',
                    title='Booking Cancelled by Admin',
                    message=f'Your booking #{booking.id} has been cancelled by an admin. Reason: {reason}',
                    entity_type='Booking',
                    entity_id=booking.id,
                )
            except Exception:
                pass

            if booking.guide:
                try:
                    create_notification(
                        recipient=booking.guide.profile.user,
                        notification_type='booking_cancelled',
                        title='Booking Cancelled by Admin',
                        message=f'Booking #{booking.id} has been cancelled by an admin. Reason: {reason}',
                        entity_type='Booking',
                        entity_id=booking.id,
                    )
                except Exception:
                    pass

            return JsonResponse({'success': True, 'message': f'Booking #{booking.id} cancelled.'})

        elif action == 'no_show':
            if not reason:
                return JsonResponse({'success': False, 'error': 'Notes are required.'}, status=400)

            if booking.status != 'confirmed':
                return JsonResponse({'success': False, 'error': f'Can only mark confirmed bookings as no-show. Current status: {booking.status}'}, status=400)

            booking.status = 'no_show'
            booking.save()

            log_admin_action(
                request,
                action_type='other',
                entity_type='Booking',
                entity_id=booking.id,
                entity_name=f'Booking #{booking.id}',
                description=f'Marked as no-show. Notes: {reason}',
            )

            try:
                create_notification(
                    recipient=booking.visitor.profile.user,
                    notification_type='booking_no_show',
                    title='Booking Marked as No-Show',
                    message=f'Booking #{booking.id} has been marked as no-show by an admin.',
                    entity_type='Booking',
                    entity_id=booking.id,
                )
            except Exception:
                pass

            if booking.guide:
                try:
                    create_notification(
                        recipient=booking.guide.profile.user,
                        notification_type='booking_no_show',
                        title='Booking Marked as No-Show',
                        message=f'Booking #{booking.id} has been marked as no-show by an admin.',
                        entity_type='Booking',
                        entity_id=booking.id,
                    )
                except Exception:
                    pass

            return JsonResponse({'success': True, 'message': f'Booking #{booking.id} marked as no-show.'})

        else:
            return JsonResponse({'success': False, 'error': 'Invalid action.'}, status=400)

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ============ ANALYTICS ============

@login_required
@admin_required
def analytics(request):
    """Admin analytics overview — platform insights and trends"""
    from django.db.models.functions import TruncMonth
    from datetime import timedelta

    now = timezone.now()
    this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    total_users = Profile.objects.count()
    total_bookings = Booking.objects.count()
    total_reviews = Review.objects.count()
    approved_reviews = Review.objects.filter(moderation_status='approved').count()
    avg_rating = Review.objects.filter(
        moderation_status='approved'
    ).aggregate(Avg('rating'))['rating__avg'] or 0

    new_users_this_month = Profile.objects.filter(created_at__gte=this_month_start).count()
    new_bookings_this_month = Booking.objects.filter(created_at__gte=this_month_start).count()
    new_reviews_this_month = Review.objects.filter(created_at__gte=this_month_start).count()

    twelve_months_ago = (this_month_start - timedelta(days=365)).replace(day=1)

    users_by_month = Profile.objects.filter(
        created_at__gte=twelve_months_ago
    ).annotate(
        month=TruncMonth('created_at')
    ).values('month').annotate(count=Count('id')).order_by('month')

    month_labels = []
    month_users = []

    current = twelve_months_ago
    for i in range(13):
        label = current.strftime('%b %Y')
        count = next((u['count'] for u in users_by_month if u['month'].date() == current.date()), 0)
        month_labels.append(label)
        month_users.append(count)
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    bookings_by_status = {
        'pending': Booking.objects.filter(status='pending').count(),
        'confirmed': Booking.objects.filter(status='confirmed').count(),
        'completed': Booking.objects.filter(status='completed').count(),
        'cancelled': Booking.objects.filter(status='cancelled').count(),
        'rejected': Booking.objects.filter(status='rejected').count(),
    }

    top_experiences = Experience.objects.annotate(
        booking_count=Count('bookings')
    ).filter(booking_count__gt=0).order_by('-booking_count')[:5]

    top_guides = GuideProfile.objects.annotate(
        booking_count=Count('bookings')
    ).filter(booking_count__gt=0).order_by('-booking_count', '-average_rating')[:5]

    categories_qs = Category.objects.annotate(
        booking_count=Count('experiences__bookings')
    ).filter(booking_count__gt=0).order_by('-booking_count')

    category_labels = [c.name for c in categories_qs]
    category_counts = [c.booking_count for c in categories_qs]

    sidebar_counts = get_sidebar_counts()

    context = {
        'user': request.user,
        'profile': request.user.profile,
        'now': now,
        'unread_count': get_unread_count_for_user(request.user),

        'total_users': total_users,
        'total_bookings': total_bookings,
        'total_reviews': total_reviews,
        'approved_reviews': approved_reviews,
        'avg_rating': avg_rating,
        'new_users_this_month': new_users_this_month,
        'new_bookings_this_month': new_bookings_this_month,
        'new_reviews_this_month': new_reviews_this_month,

        'month_labels': month_labels,
        'month_users': month_users,
        'bookings_by_status': bookings_by_status,

        'top_experiences': top_experiences,
        'top_guides': top_guides,

        'category_labels': category_labels,
        'category_counts': category_counts,

        **sidebar_counts,
    }
    return render(request, 'admin_dashboard/analytics.html', context)


# ============ AUDIT LOGS ============

@login_required
@admin_required
def audit_logs(request):
    """Audit log history — filterable, searchable timeline of all admin actions"""
    from datetime import timedelta

    current_type = request.GET.get('type', 'all')
    search_query = request.GET.get('search', '').strip()

    ENTITY_TYPE_MAP = {
        'provider': 'ProviderProfile',
        'guide': 'GuideProfile',
        'experience': 'Experience',
        'review': 'Review',
        'user': ('Profile', 'User'),
        'booking': 'Booking',
    }

    qs = AdminAction.objects.select_related('admin').order_by('-created_at')

    if current_type != 'all':
        mapped_type = ENTITY_TYPE_MAP.get(current_type, current_type)
        if isinstance(mapped_type, tuple):
            qs = qs.filter(entity_type__in=mapped_type)
        else:
            qs = qs.filter(entity_type__iexact=mapped_type)

    if search_query:
        qs = qs.filter(
            Q(admin__first_name__icontains=search_query) |
            Q(admin__last_name__icontains=search_query) |
            Q(admin__username__icontains=search_query) |
            Q(entity_name__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    paginator = Paginator(qs, 30)
    page_obj = paginator.get_page(request.GET.get('page'))

    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)

    total_actions = AdminAction.objects.count()
    actions_today = AdminAction.objects.filter(created_at__gte=today_start).count()
    actions_this_week = AdminAction.objects.filter(created_at__gte=week_start).count()
    unique_admins = AdminAction.objects.exclude(admin=None).values('admin').distinct().count()

    sidebar_counts = get_sidebar_counts()

    context = {
        'user': request.user,
        'profile': request.user.profile,
        'logs': page_obj,
        'current_type': current_type,
        'search': search_query,
        'total_actions': total_actions,
        'actions_today': actions_today,
        'actions_this_week': actions_this_week,
        'unique_admins': unique_admins,
        'now': now,
        'unread_count': get_unread_count_for_user(request.user),
        **sidebar_counts,
    }
    return render(request, 'admin_dashboard/audit_logs.html', context)


# ============ EXPERIENCE ACTIONS ============

@login_required
@admin_required
def experience_detail(request, experience_id):
    """Experience detail view — full info + provider + bookings + reviews + history"""
    experience = get_object_or_404(
        Experience.objects.select_related(
            'provider', 'provider__profile', 'provider__profile__user',
            'category', 'guide', 'guide__profile', 'guide__profile__user'
        ),
        id=experience_id
    )

    bookings = Booking.objects.filter(
        experience=experience
    ).select_related(
        'visitor', 'visitor__profile', 'visitor__profile__user',
        'guide', 'guide__profile', 'guide__profile__user'
    ).order_by('-created_at')[:10]

    reviews = Review.objects.filter(
        experience=experience,
        review_type='experience',
        moderation_status='approved'
    ).select_related(
        'visitor', 'visitor__profile', 'visitor__profile__user'
    ).order_by('-created_at')[:5]

    recent_actions = AdminAction.objects.filter(
        entity_type='Experience',
        entity_id=experience.id
    ).order_by('-created_at')[:10]

    total_bookings = Booking.objects.filter(experience=experience).count()
    completed_bookings = Booking.objects.filter(experience=experience, status='completed').count()
    total_reviews = Review.objects.filter(
        experience=experience,
        review_type='experience',
        moderation_status='approved'
    ).count()

    sidebar_counts = get_sidebar_counts()

    context = {
        'user': request.user,
        'profile': request.user.profile,
        'experience': experience,
        'bookings': bookings,
        'reviews': reviews,
        'recent_actions': recent_actions,
        'total_bookings': total_bookings,
        'completed_bookings': completed_bookings,
        'total_reviews': total_reviews,
        'now': timezone.now(),
        'unread_count': get_unread_count_for_user(request.user),
        **sidebar_counts,
    }

    return render(request, 'admin_dashboard/experience_detail.html', context)


@login_required
@admin_required
@require_POST
def experience_action(request, experience_id, action):
    """Handle experience approve / reject / suspend / restore via AJAX"""
    experience = get_object_or_404(Experience, id=experience_id)
    reason = request.POST.get('reason', '').strip()

    try:
        if action == 'approve':
            experience.status = 'published'
            experience.approved_at = timezone.now()
            experience.approved_by = request.user
            experience.is_available = True
            experience.save()

            log_admin_action(
                request,
                action_type='approve_experience',
                entity_type='Experience',
                entity_id=experience.id,
                entity_name=experience.name,
                description='Approved & published experience',
            )

            try:
                create_notification(
                    recipient=experience.provider.profile.user,
                    notification_type='experience_approved',
                    title='Experience Approved',
                    message=f'Your experience "{experience.name}" has been approved and is now live on the Discover page.',
                    entity_type='Experience',
                    entity_id=experience.id,
                )
            except Exception:
                pass

            return JsonResponse({'success': True, 'message': f'{experience.name} approved & published.'})

        elif action == 'reject':
            if not reason:
                return JsonResponse({'success': False, 'error': 'Rejection reason is required.'}, status=400)

            experience.status = 'rejected'
            experience.rejection_reason = reason
            experience.save()

            log_admin_action(
                request,
                action_type='reject_experience',
                entity_type='Experience',
                entity_id=experience.id,
                entity_name=experience.name,
                description=f'Rejected. Reason: {reason}',
            )

            try:
                create_notification(
                    recipient=experience.provider.profile.user,
                    notification_type='experience_rejected',
                    title='Experience Rejected',
                    message=f'Your experience "{experience.name}" was rejected. Reason: {reason}',
                    entity_type='Experience',
                    entity_id=experience.id,
                )
            except Exception:
                pass

            return JsonResponse({'success': True, 'message': f'{experience.name} rejected.'})

        elif action == 'suspend':
            if not reason:
                return JsonResponse({'success': False, 'error': 'Suspension reason is required.'}, status=400)

            experience.status = 'suspended'
            experience.is_available = False
            experience.suspension_reason = reason
            experience.suspended_at = timezone.now()
            experience.suspended_by = request.user
            experience.save()

            log_admin_action(
                request,
                action_type='suspend_experience',
                entity_type='Experience',
                entity_id=experience.id,
                entity_name=experience.name,
                description=f'Suspended. Reason: {reason}',
            )

            try:
                create_notification(
                    recipient=experience.provider.profile.user,
                    notification_type='experience_suspended',
                    title='Experience Suspended',
                    message=f'Your experience "{experience.name}" has been suspended. Reason: {reason}',
                    entity_type='Experience',
                    entity_id=experience.id,
                )
            except Exception:
                pass

            return JsonResponse({'success': True, 'message': f'{experience.name} suspended.'})

        elif action == 'restore':
            experience.status = 'under_review'
            experience.suspension_reason = ''
            experience.suspended_at = None
            experience.suspended_by = None
            experience.is_available = False
            experience.save()

            log_admin_action(
                request,
                action_type='approve_experience',
                entity_type='Experience',
                entity_id=experience.id,
                entity_name=experience.name,
                description='Restored to review queue',
            )

            return JsonResponse({'success': True, 'message': f'{experience.name} restored to review queue.'})

        else:
            return JsonResponse({'success': False, 'error': 'Invalid action.'}, status=400)

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@admin_required
@require_POST
def action_approve_experience(request, experience_id):
    experience = get_object_or_404(Experience, id=experience_id)
    experience.status = 'published'
    experience.approved_at = timezone.now()
    experience.approved_by = request.user
    experience.save()
    log_admin_action(request, 'approve_experience', 'Experience', experience.id, experience.name, 'Experience approved by admin')
    return JsonResponse({'success': True, 'message': f'{experience.name} was approved.'})


@login_required
@admin_required
@require_POST
def action_reject_experience(request, experience_id):
    experience = get_object_or_404(Experience, id=experience_id)
    reason = request.POST.get('reason', 'No reason provided').strip() or 'No reason provided'
    experience.status = 'rejected'
    experience.rejection_reason = reason
    experience.save()
    log_admin_action(request, 'reject_experience', 'Experience', experience.id, experience.name, f'Experience rejected. Reason: {reason}')
    return JsonResponse({'success': True, 'message': f'{experience.name} was rejected.'})
@login_required
@admin_required
@require_POST
def review_action(request, review_id, action):
    """
    Handle review moderation via AJAX.

    Actions:
      - approve   : mark as approved + recalculate + notify
      - reject    : soft hide with a reason (current default moderation)
      - remove    : policy-violation removal (escalation from rejected)
      - flag_user : escalate the author without changing review status
    """
    review = get_object_or_404(Review, id=review_id)
    reason = request.POST.get('reason', '').strip()

    try:
        if action == 'approve':
            review.moderate(
                moderator=request.user,
                status='approved',
                notes='Approved by admin'
            )

            log_admin_action(
                request,
                action_type='approve_review',
                entity_type='Review',
                entity_id=review.id,
                entity_name=review.subject_name,
                description='Review approved by admin',
            )

            try:
                create_notification(
                    recipient=review.visitor.profile.user,
                    notification_type='review_approved',
                    title='Your review was approved',
                    message=f'Your review for "{review.subject_name}" is now live and visible to everyone.',
                    entity_type='Review',
                    entity_id=review.id,
                )
            except Exception:
                pass

            if review.guide:
                try:
                    create_notification(
                        recipient=review.guide.profile.user,
                        notification_type='review_received',
                        title='New Approved Review',
                        message=f'A new {review.rating}-star review for you is now public.',
                        entity_type='Review',
                        entity_id=review.id,
                    )
                except Exception:
                    pass

            if review.experience and review.experience.provider:
                try:
                    create_notification(
                        recipient=review.experience.provider.profile.user,
                        notification_type='review_received',
                        title='New Approved Review',
                        message=f'A new {review.rating}-star review for "{review.experience.name}" is now public.',
                        entity_type='Review',
                        entity_id=review.id,
                    )
                except Exception:
                    pass

            return JsonResponse({'success': True, 'message': 'Review approved.'})

        elif action == 'reject':
            if not reason:
                return JsonResponse({'success': False, 'error': 'Rejection reason is required.'}, status=400)

            review.moderate(
                moderator=request.user,
                status='rejected',
                notes=reason
            )

            log_admin_action(
                request,
                action_type='reject_review',
                entity_type='Review',
                entity_id=review.id,
                entity_name=review.subject_name,
                description=f'Review rejected. Reason: {reason}',
            )

            try:
                create_notification(
                    recipient=review.visitor.profile.user,
                    notification_type='review_rejected',
                    title='Your review was not published',
                    message=f'Your review for "{review.subject_name}" was not published. Reason: {reason}',
                    entity_type='Review',
                    entity_id=review.id,
                )
            except Exception:
                pass

            # Auto-flag: if this user now has 3+ rejected/removed reviews
            _maybe_auto_flag_reviewer(request, review)

            return JsonResponse({'success': True, 'message': 'Review rejected.'})

        elif action == 'remove':
            if not reason:
                return JsonResponse({'success': False, 'error': 'Removal reason is required.'}, status=400)

            review.moderate(
                moderator=request.user,
                status='removed',
                notes=reason
            )

            log_admin_action(
                request,
                action_type='remove_review',
                entity_type='Review',
                entity_id=review.id,
                entity_name=review.subject_name,
                description=f'Review removed for policy violation. Reason: {reason}',
            )

            try:
                create_notification(
                    recipient=review.visitor.profile.user,
                    notification_type='review_removed',
                    title='Your review was removed',
                    message=(
                        f'Your review for "{review.subject_name}" was removed for a policy violation. '
                        f'Reason: {reason}'
                    ),
                    entity_type='Review',
                    entity_id=review.id,
                )
            except Exception:
                pass

            # Auto-flag: removed reviews are more serious than rejected
            _maybe_auto_flag_reviewer(request, review, is_removal=True)

            return JsonResponse({'success': True, 'message': 'Review removed.'})

        elif action == 'flag_user':
            if not reason:
                return JsonResponse({'success': False, 'error': 'Please provide a reason for flagging this user.'}, status=400)

            log_admin_action(
                request,
                action_type='flag_user',
                entity_type='Profile',
                entity_id=review.visitor.profile.id,
                entity_name=review.reviewer_name,
                description=f'User flagged from review #{review.id}. Reason: {reason}',
            )

            return JsonResponse({'success': True, 'message': f'{review.reviewer_name} flagged.'})

        else:
            return JsonResponse({'success': False, 'error': 'Invalid action.'}, status=400)

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def _maybe_auto_flag_reviewer(request, review, is_removal=False):
    """
    If a reviewer has >= 3 rejected or removed reviews, log an auto-flag
    AdminAction so other admins see the pattern.

    Called automatically after reject/remove actions. Never fails loudly —
    a logging failure should not break the moderation flow.
    """
    try:
        visitor_profile = review.visitor.profile
        bad_count = Review.objects.filter(
            visitor=review.visitor,
            moderation_status__in=['rejected', 'removed'],
        ).count()

        threshold = 3
        if bad_count < threshold:
            return

        # Avoid duplicate auto-flags for the same user today
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        already_flagged = AdminAction.objects.filter(
            entity_type='Profile',
            entity_id=visitor_profile.id,
            action_type='flag_user',
            created_at__gte=today_start,
        ).exists()
        if already_flagged:
            return

        severity = 'removal' if is_removal else 'rejection'
        AdminAction.objects.create(
            admin=request.user,
            action_type='flag_user',
            entity_type='Profile',
            entity_id=visitor_profile.id,
            entity_name=review.reviewer_name,
            description=(
                f'Auto-flag: reviewer has {bad_count} rejected/removed reviews '
                f'(last action: {severity}).'
            ),
            ip_address=request.META.get('REMOTE_ADDR'),
        )
    except Exception:
        pass
# ============ SUSPEND / UNSUSPEND USERS ============

@login_required
@admin_required
@require_POST
def suspend_user(request, user_id):
    """Suspend a user with reason"""
    user_obj = get_object_or_404(Profile, id=user_id)

    if user_obj.role == 'admin':
        messages.error(request, 'Administrators cannot be suspended.')
        return redirect('admin_dashboard:user_detail', user_id=user_id)

    reason = request.POST.get('reason', '').strip()
    custom_reason = request.POST.get('custom_reason', '').strip()

    if not reason:
        messages.error(request, 'A suspension reason is required.')
        return redirect('admin_dashboard:user_detail', user_id=user_id)

    if reason == 'other':
        if not custom_reason:
            messages.error(request, 'Please provide a custom reason.')
            return redirect('admin_dashboard:user_detail', user_id=user_id)
        reason = custom_reason

    user_obj.is_suspended = True
    user_obj.suspension_reason = reason
    user_obj.suspended_at = timezone.now()
    user_obj.suspended_by = request.user
    user_obj.save()

    user_obj.user.is_active = False
    user_obj.user.save()

    log_admin_action(
        request,
        action_type='suspend_user',
        entity_type='Profile',
        entity_id=user_obj.id,
        entity_name=user_obj.user.get_full_name() or user_obj.user.username,
        description=f'Suspended. Reason: {reason}',
    )

    try:
        create_notification(
            recipient=user_obj.user,
            notification_type='account_suspended',
            title='Account Suspended',
            message=f'Your account has been suspended. Reason: {reason}',
            entity_type='Profile',
            entity_id=user_obj.id,
        )
    except Exception:
        pass

    try:
        send_suspension_email(user_obj.user, reason)
    except Exception:
        pass

    messages.success(request, f'{user_obj.user.get_full_name() or user_obj.user.username} has been suspended.')
    return redirect('admin_dashboard:user_detail', user_id=user_id)


@login_required
@admin_required
@require_POST
def unsuspend_user(request, user_id):
    """Restore a suspended user"""
    user_obj = get_object_or_404(Profile, id=user_id)

    if not user_obj.is_suspended:
        messages.info(request, 'This user is not suspended.')
        return redirect('admin_dashboard:user_detail', user_id=user_id)

    user_obj.is_suspended = False
    user_obj.suspension_reason = ''
    user_obj.suspended_at = None
    user_obj.suspended_by = None
    user_obj.save()

    user_obj.user.is_active = True
    user_obj.user.save()

    log_admin_action(
        request,
        action_type='activate_user',
        entity_type='Profile',
        entity_id=user_obj.id,
        entity_name=user_obj.user.get_full_name() or user_obj.user.username,
        description='Suspension lifted',
    )

    try:
        create_notification(
            recipient=user_obj.user,
            notification_type='account_restored',
            title='Account Restored',
            message='Your account has been restored. Welcome back!',
            entity_type='Profile',
            entity_id=user_obj.id,
        )
    except Exception:
        pass

    messages.success(request, f'{user_obj.user.get_full_name() or user_obj.user.username} has been restored.')

    return redirect('admin_dashboard:user_detail', user_id=user_id)
# ============================================================
# ADMIN MANAGEMENT (Owner / superuser only)
# FR-A01: Admin Account Provisioning
# ============================================================

def _owner_required(view_func):
    """
    Stricter than @admin_required — requires the user to be a
    Django superuser (the Owner account). Only the Owner can
    manage other admin accounts.
    """
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts:login')
        if not request.user.is_superuser:
            messages.error(
                request,
                'Only the platform Owner can manage administrator accounts.'
            )
            return redirect('admin_dashboard:dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper


@login_required
@admin_required
@_owner_required
def admin_management(request):
    """
    Owner-only page: list current admins + pending invites.
    """
    admins = (
        Profile.objects
        .filter(role='admin')
        .select_related('user')
        .order_by('-created_at')
    )

    pending_invites = (
        AdminInvite.objects
        .filter(status='pending')
        .select_related('invited_by')
        .order_by('-created_at')
    )

    # Auto-expire stale invites so the list stays honest
    now = timezone.now()
    for inv in pending_invites:
        if inv.expires_at <= now:
            inv.mark_expired()

    # Re-query after expiry sweep
    pending_invites = (
        AdminInvite.objects
        .filter(status='pending')
        .select_related('invited_by')
        .order_by('-created_at')
    )

    recent_history = (
        AdminInvite.objects
        .exclude(status='pending')
        .select_related('invited_by', 'accepted_by')
        .order_by('-created_at')[:20]
    )

    context = {
        'user': request.user,
        'profile': request.user.profile,
        'admins': admins,
        'pending_invites': pending_invites,
        'recent_history': recent_history,
        'total_admins': admins.count(),
        'total_pending': pending_invites.count(),
        'now': now,
        'unread_count': get_unread_count_for_user(request.user),
        **get_sidebar_counts(),
    }
    return render(request, 'admin_dashboard/admins.html', context)


@login_required
@admin_required
@_owner_required
@require_POST
def invite_admin(request):
    """
    Owner sends an admin invitation.

    Rules:
      - Email must be valid and not already an existing user
      - No pending invite may already exist for that email
      - Creates an AdminInvite row and sends the email
      - Logged to AdminAction
    """
    from django.core.validators import validate_email
    from django.core.exceptions import ValidationError

    email = (request.POST.get('email') or '').strip().lower()
    message = (request.POST.get('message') or '').strip()

    # Validate email
    if not email:
        messages.error(request, 'An email address is required.')
        return redirect('admin_dashboard:admin_management')

    try:
        validate_email(email)
    except ValidationError:
        messages.error(request, 'Please enter a valid email address.')
        return redirect('admin_dashboard:admin_management')

    # Already a user?
    if User.objects.filter(username=email).exists():
        messages.error(
            request,
            f'An account already exists for {email}. '
            f'If they should become an admin, use "Promote to Administrator" from their user page instead.'
        )
        return redirect('admin_dashboard:admin_management')

    # Already a pending invite?
    if AdminInvite.objects.filter(email=email, status='pending').exists():
        messages.error(request, f'A pending invitation already exists for {email}.')
        return redirect('admin_dashboard:admin_management')

    # Create the invitation and invalidate it if the email cannot be sent.
    invite = AdminInvite.objects.create(
        email=email,
        message=message,
        invited_by=request.user,
    )

    try:
        from accounts.utils import send_admin_invite_email
        send_admin_invite_email(invite)
    except Exception:
        logger.exception("Admin invitation email failed for invite %s", invite.pk)
        invite.mark_revoked()
        log_admin_action(
            request,
            action_type='other',
            entity_type='AdminInvite',
            entity_id=invite.id,
            entity_name=email,
            description=f'Administrator invitation email failed for {email}; invitation was revoked.',
            metadata={'event': 'admin_invite_email_failed'},
        )
        messages.error(
            request,
            f'The invitation email could not be sent to {email}. The invitation was cancelled; check the email configuration and try again.'
        )
        return redirect('admin_dashboard:admin_management')

    log_admin_action(
        request,
        action_type='admin_invite_sent',
        entity_type='AdminInvite',
        entity_id=invite.id,
        entity_name=email,
        description=f'Admin invitation sent to {email}',
    )

    messages.success(request, f'Invitation sent to {email}.')
    return redirect('admin_dashboard:admin_management')


@login_required
@admin_required
@_owner_required
@require_POST
def promote_admin(request, profile_id):
    """Promote an existing active account to an application Administrator."""
    profile = get_object_or_404(
        Profile.objects.select_related('user'),
        id=profile_id,
    )
    target_user = profile.user

    if profile.role == 'admin':
        messages.info(request, 'This user is already an administrator.')
        return redirect('admin_dashboard:user_detail', user_id=profile.id)

    if not target_user.is_active or profile.is_suspended:
        messages.error(
            request,
            'Restore this account before granting administrator access.',
        )
        return redirect('admin_dashboard:user_detail', user_id=profile.id)

    with transaction.atomic():
        profile.role = 'admin'
        profile.save(update_fields=['role'])
        log_admin_action(
            request,
            action_type='other',
            entity_type='Profile',
            entity_id=profile.id,
            entity_name=target_user.get_full_name() or target_user.username,
            description=f'Administrator access granted to {target_user.email}.',
            metadata={'event': 'admin_promoted'},
        )

    messages.success(
        request,
        f'{target_user.get_full_name() or target_user.username} is now an administrator.',
    )
    return redirect('admin_dashboard:user_detail', user_id=profile.id)


@login_required
@admin_required
@_owner_required
@require_POST
def revoke_admin_invite(request, invite_id):
    """Owner cancels a pending invitation."""
    invite = get_object_or_404(AdminInvite, id=invite_id)

    if invite.status != 'pending':
        messages.info(request, 'This invitation is no longer pending.')
        return redirect('admin_dashboard:admin_management')

    invite.mark_revoked()

    log_admin_action(
        request,
        action_type='admin_invite_revoked',
        entity_type='AdminInvite',
        entity_id=invite.id,
        entity_name=invite.email,
        description=f'Admin invitation revoked for {invite.email}',
    )

    messages.success(request, f'Invitation for {invite.email} has been revoked.')
    return redirect('admin_dashboard:admin_management')


@login_required
@admin_required
@_owner_required
@require_POST
def remove_admin(request, profile_id):
    """
    Owner demotes an admin back to a safe role (tourist).
    Cannot demote yourself. Cannot demote the last remaining superuser.
    """
    profile = get_object_or_404(Profile.objects.select_related('user'), id=profile_id)

    if profile.role != 'admin':
        messages.info(request, 'This user is not an administrator.')
        return redirect('admin_dashboard:admin_management')

    if profile.user_id == request.user.id:
        messages.error(request, 'You cannot remove your own administrator access.')
        return redirect('admin_dashboard:admin_management')

    # Refuse to remove the last remaining superuser
    superuser_count = User.objects.filter(is_superuser=True).count()
    if profile.user.is_superuser and superuser_count <= 1:
        messages.error(
            request,
            'This is the last Owner account. Create another superuser before removing this one.'
        )
        return redirect('admin_dashboard:admin_management')

    # Flip the role
    profile.role = 'tourist'
    profile.save(update_fields=['role'])
    TouristProfile.objects.get_or_create(profile=profile)

    # Also strip the Django superuser/staff flag if the target was a superuser
    target_user = profile.user
    if target_user.is_superuser or target_user.is_staff:
        target_user.is_superuser = False
        target_user.is_staff = False
        target_user.save(update_fields=['is_superuser', 'is_staff'])

    log_admin_action(
        request,
        action_type='admin_removed',
        entity_type='Profile',
        entity_id=profile.id,
        entity_name=target_user.get_full_name() or target_user.username,
        description=f'Administrator access removed for {target_user.email}',
    )

    try:
        create_notification(
            recipient=target_user,
            notification_type='security_alert',
            title='Administrator access removed',
            message='Your administrator access to Explore Kimberley has been removed.',
            entity_type='Profile',
            entity_id=profile.id,
        )
    except Exception:
        pass

    messages.success(
        request,
        f'{target_user.get_full_name() or target_user.username} is no longer an administrator.'
    )
    return redirect('admin_dashboard:admin_management')