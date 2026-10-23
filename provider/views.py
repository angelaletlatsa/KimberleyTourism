from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Avg, Count, Sum, Q
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.core.exceptions import ValidationError
from decimal import Decimal, InvalidOperation

from .models import ProviderProfile
from experiences.models import Experience, Category
from bookings.models import Booking
from reviews.models import Review
from notifications.models import Notification
from notifications.utils import create_notification, get_unread_count_for_user


# ============ HELPERS ============

def get_listing_type_from_category(category):
    if not category:
        return 'activities'
    name = category.name.lower()
    if 'food' in name or 'dining' in name:
        return 'food_dining'
    elif 'stay' in name or 'place' in name or 'hotel' in name or 'accommodation' in name:
        return 'places_to_stay'
    elif 'attraction' in name:
        return 'attractions'
    else:
        return 'activities'


def save_opening_hours(experience, post_data):
    opening_hours = {}
    for day in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']:
        values = [value for value in post_data.getlist(f'opening_{day}') if value.strip()]
        opening_hours[day] = values[0] if values else ''
    experience.opening_hours = opening_hours


def read_price_fields_from_post(post_data, experience):
    """
    Read the provider's own price range from the form.

    Reads fields by their simple names:
        price_range_min, price_range_max, price_unit

    The template must ensure only ONE section is submitted at a time
    (or use per-category field names). Since our templates use the same
    field name in one active section, this is safe.

    Returns a list of error strings. Writes valid values directly onto
    the experience instance.
    """
    errors = []

    min_raw = (post_data.get('price_range_min') or '').strip()
    max_raw = (post_data.get('price_range_max') or '').strip()
    unit = (post_data.get('price_unit') or '').strip()

    # ---- Parse min ----
    price_min = None
    if min_raw:
        try:
            price_min = Decimal(min_raw)
            if price_min < 0:
                errors.append('Minimum price cannot be negative.')
                price_min = None
            elif price_min > Decimal('10000000'):
                errors.append('Minimum price is unrealistically high (max R10,000,000).')
                price_min = None
        except (InvalidOperation, ValueError):
            errors.append('Minimum price must be a number.')
            price_min = None

    # ---- Parse max ----
    price_max = None
    if max_raw:
        try:
            price_max = Decimal(max_raw)
            if price_max < 0:
                errors.append('Maximum price cannot be negative.')
                price_max = None
            elif price_max > Decimal('10000000'):
                errors.append('Maximum price is unrealistically high (max R10,000,000).')
                price_max = None
        except (InvalidOperation, ValueError):
            errors.append('Maximum price must be a number.')
            price_max = None

    # ---- Cross-check ----
    if price_min is not None and price_max is not None and price_max < price_min:
        errors.append('Maximum price must be greater than or equal to minimum price.')

    # ---- Validate unit ----
    valid_units = {choice[0] for choice in Experience.PRICE_UNIT_CHOICES}
    if unit not in valid_units:
        unit = ''

    # ---- Assign ----
    experience.price_range_min = price_min
    experience.price_range_max = price_max
    experience.price_unit = unit

    return errors


# ============ DASHBOARD ============
@login_required
def dashboard(request):
    if request.user.profile.role != 'provider':
        return redirect('tourist:dashboard')

    try:
        provider = request.user.profile.provider_profile
    except ProviderProfile.DoesNotExist:
        provider = ProviderProfile.objects.create(
            profile=request.user.profile,
            business_name=f"{request.user.first_name}'s Business"
        )
        messages.info(request, 'Welcome! Please complete your business profile.')
        return redirect('provider:profile')

    experiences = Experience.objects.filter(provider=provider)

    total_experiences = experiences.count()
    active_experiences = experiences.filter(status='published', is_available=True).count()
    pending_experiences = experiences.filter(status__in=['draft', 'under_review', 'submitted']).count()
    rejected_experiences = experiences.filter(status='rejected').count()

    bookings = Booking.objects.filter(experience__provider=provider)
    total_bookings = bookings.count()
    confirmed_bookings = bookings.filter(status='confirmed').count()
    completed_bookings = bookings.filter(status='completed').count()
    cancelled_bookings = bookings.filter(status='cancelled').count()

    # Bookings that need provider's attention (pending, awaiting their action)
    has_unanswered = bookings.filter(status='pending').count()

    reviews = Review.objects.filter(
        experience__provider=provider,
        review_type='experience',
        moderation_status='approved'
    )
    avg_rating = reviews.aggregate(Avg('rating'))['rating__avg'] or 0
    total_reviews = reviews.count()

    # ===== RECENT REVIEWS =====
    recent_reviews = Review.objects.filter(
        experience__provider=provider,
        review_type='experience',
        moderation_status='approved'
    ).select_related(
        'experience', 'visitor', 'visitor__profile', 'visitor__profile__user'
    ).order_by('-created_at')[:3]

    # ===== RECENT EXPERIENCES with booking counts =====
    recent_experiences = experiences.select_related('category').annotate(
        booking_count=Count('bookings')
    ).order_by('-created_at')[:5]

    # ===== 14-DAY TREND (heatmap levels 0-4) =====
    from datetime import timedelta
    today = timezone.now().date()
    trend_chart = []
    trend_total = 0
    daily_counts = []
    for i in range(13, -1, -1):
        d = today - timedelta(days=i)
        count = bookings.filter(booking_date=d).exclude(
            status__in=['cancelled', 'rejected']
        ).count()
        trend_total += count
        daily_counts.append((d, count))

    max_count = max([c for _, c in daily_counts] + [1])

    for i, (d, count) in enumerate(daily_counts):
        # Level 0-4 based on relative volume
        if count == 0:
            level = 0
        elif count == max_count:
            level = 4
        else:
            ratio = count / max_count
            if ratio <= 0.25:
                level = 1
            elif ratio <= 0.5:
                level = 2
            elif ratio <= 0.75:
                level = 3
            else:
                level = 4
        is_today = (i == len(daily_counts) - 1)
        trend_chart.append({
            'short': d.strftime('%d'),
            'count': count,
            'level': level,
            'is_today': is_today,
        })

    # ===== PUBLISH RATE =====
    publish_rate = int((active_experiences / total_experiences) * 100) if total_experiences > 0 else 0

    unread_count = get_unread_count_for_user(request.user)
    verification_status_display = dict(ProviderProfile.VERIFICATION_STATUS).get(
        provider.verification_status, 'Pending'
    )

    context = {
        'user': request.user,
        'profile': request.user.profile,
        'provider': provider,
        'now': timezone.now(),
        'unread_count': unread_count,

        'total_experiences': total_experiences,
        'active_experiences': active_experiences,
        'pending_experiences': pending_experiences,
        'rejected_experiences': rejected_experiences,

        'total_bookings': total_bookings,
        'confirmed_bookings': confirmed_bookings,
        'completed_bookings': completed_bookings,
        'cancelled_bookings': cancelled_bookings,
        'has_unanswered': has_unanswered,

        'avg_rating': avg_rating,
        'total_reviews': total_reviews,

        'recent_reviews': recent_reviews,
        'recent_experiences': recent_experiences,

        'trend_chart': trend_chart,
        'trend_total': trend_total,
        'publish_rate': publish_rate,

        'verification_status': provider.verification_status,
        'verification_status_display': verification_status_display,
        'is_verified': provider.is_verified,
        'is_suspended': provider.is_suspended,
    }

    return render(request, 'provider/dashboard.html', context)
# ============ PROFILE ============

@login_required
def profile(request):
    if request.user.profile.role != 'provider':
        return redirect('tourist:dashboard')

    try:
        provider = request.user.profile.provider_profile
    except ProviderProfile.DoesNotExist:
        provider = ProviderProfile.objects.create(
            profile=request.user.profile,
            business_name=f"{request.user.first_name}'s Business"
        )

    if request.method == 'POST':
        action = request.POST.get('action', 'save')

        provider.business_name = request.POST.get('business_name', provider.business_name)
        provider.business_description = request.POST.get('business_description', '')
        provider.business_category = request.POST.get('business_category', '')

        provider.contact_phone = request.POST.get('contact_phone', '')
        provider.contact_email = request.POST.get('contact_email', '')

        social_links = provider.social_links or {}
        social_links['facebook'] = request.POST.get('facebook', '')
        social_links['instagram'] = request.POST.get('instagram', '')
        social_links['twitter'] = request.POST.get('twitter', '')
        social_links['ticktock'] = request.POST.get('ticktock', '')
        provider.social_links = social_links

        provider.address = request.POST.get('address', '')
        provider.city = request.POST.get('city', 'Kimberley')
        provider.province = request.POST.get('province', 'Northern Cape')
        provider.country = request.POST.get('country', 'South Africa')

        provider.save()

        if action == 'submit_verification':
            provider.verification_status = 'pending'
            provider.verification_notes = ''
            provider.save()

            create_notification(
                recipient=request.user,
                notification_type='provider_profile_submitted',
                title='Profile Submitted for Verification',
                message=f'Your business profile "{provider.business_name}" was submitted for verification.',
                link='/providers/profile/view/',
                entity_type='ProviderProfile',
                entity_id=provider.id
            )

            from django.contrib.auth.models import User
            admins = User.objects.filter(profile__role='admin')
            for admin in admins:
                Notification.objects.create(
                    recipient=admin,
                    notification_type='provider_verification',
                    title='Provider Verification Request',
                    message=f'Provider "{provider.business_name}" has submitted their profile for verification.',
                    link=f'/admin_dashboard/providers/{provider.id}/',
                    entity_type='ProviderProfile',
                    entity_id=provider.id
                )

            messages.success(request, 'Your business profile has been submitted for verification. You will be notified once approved.')
            return redirect('provider:profile')

        create_notification(
            recipient=request.user,
            notification_type='provider_profile_updated',
            title='Business Profile Updated',
            message=f'Your business profile "{provider.business_name}" was updated successfully.',
            link='/providers/profile/view/',
            entity_type='ProviderProfile',
            entity_id=provider.id
        )

        messages.success(request, 'Profile updated successfully.')
        return redirect('provider:profile')

    verification_status_display = dict(ProviderProfile.VERIFICATION_STATUS).get(
        provider.verification_status, 'Pending'
    )

    context = {
        'user': request.user,
        'profile': request.user.profile,
        'provider': provider,
        'now': timezone.now(),
        'unread_count': get_unread_count_for_user(request.user),
        'verification_status_display': verification_status_display,
    }

    return render(request, 'provider/profile.html', context)


@login_required
def profile_view(request):
    if request.user.profile.role != 'provider':
        return redirect('tourist:dashboard')

    try:
        provider = request.user.profile.provider_profile
    except ProviderProfile.DoesNotExist:
        provider = ProviderProfile.objects.create(
            profile=request.user.profile,
            business_name=f"{request.user.first_name}'s Business"
        )

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'submit_verification':
            provider.verification_status = 'pending'
            provider.verification_notes = ''
            provider.save()

            create_notification(
                recipient=request.user,
                notification_type='provider_profile_submitted',
                title='Profile Submitted for Verification',
                message=f'Your business profile "{provider.business_name}" was submitted for verification.',
                link='/providers/profile/view/',
                entity_type='ProviderProfile',
                entity_id=provider.id
            )

            from django.contrib.auth.models import User
            admins = User.objects.filter(profile__role='admin')
            for admin in admins:
                Notification.objects.create(
                    recipient=admin,
                    notification_type='provider_verification',
                    title='Provider Verification Request',
                    message=f'Provider "{provider.business_name}" has submitted their profile for verification.',
                    link=f'/admin_dashboard/providers/{provider.id}/',
                    entity_type='ProviderProfile',
                    entity_id=provider.id
                )

            messages.success(request, 'Your business profile has been submitted for verification.')
            return redirect('provider:profile_view')

    context = {
        'user': request.user,
        'profile': request.user.profile,
        'provider': provider,
        'now': timezone.now(),
        'unread_count': get_unread_count_for_user(request.user),
    }

    return render(request, 'provider/profile_view.html', context)


@login_required
@require_POST
def delete_profile(request):
    if request.user.profile.role != 'provider':
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    try:
        provider = request.user.profile.provider_profile
    except ProviderProfile.DoesNotExist:
        messages.error(request, 'Provider profile not found.')
        return redirect('provider:dashboard')

    business_name = provider.business_name
    create_notification(
        recipient=request.user,
        notification_type='provider_profile_deleted',
        title='Business Profile Deleted',
        message=f'Your business profile "{business_name}" was deleted successfully.',
        link='/providers/profile/',
        entity_type='ProviderProfile',
        entity_id=provider.id
    )
    admins = request.user.__class__.objects.filter(profile__role='admin')
    for admin in admins:
        create_notification(
            recipient=admin,
            notification_type='provider_profile_deleted',
            title='Provider Profile Deleted',
            message=f'Provider profile "{business_name}" was deleted by the provider.',
            link='/admin_dashboard/providers/',
            entity_type='ProviderProfile',
            entity_id=provider.id
        )

    provider.delete()
    messages.success(request, 'Your business profile was deleted successfully.')
    return redirect('provider:dashboard')


# ============ EXPERIENCE MANAGEMENT ============
@login_required
def my_experiences(request):
    if request.user.profile.role != 'provider':
        return redirect('tourist:dashboard')

    try:
        provider = request.user.profile.provider_profile
    except ProviderProfile.DoesNotExist:
        messages.error(request, 'Please complete your business profile first.')
        return redirect('provider:profile')

    status_filter = request.GET.get('status', 'all')
    search_query = request.GET.get('q', '').strip()

    experiences = Experience.objects.filter(provider=provider).select_related('category')

    if status_filter != 'all':
        experiences = experiences.filter(status=status_filter)

    if search_query:
        from django.db.models import Q
        experiences = experiences.filter(
            Q(name__icontains=search_query) |
            Q(location__icontains=search_query)
        )

    experiences = experiences.order_by('-created_at')

    counts = {
        'all': Experience.objects.filter(provider=provider).count(),
        'draft': Experience.objects.filter(provider=provider, status='draft').count(),
        'under_review': Experience.objects.filter(provider=provider, status='under_review').count(),
        'published': Experience.objects.filter(provider=provider, status='published').count(),
        'rejected': Experience.objects.filter(provider=provider, status='rejected').count(),
        'suspended': Experience.objects.filter(provider=provider, status='suspended').count(),
    }

    context = {
        'user': request.user,
        'profile': request.user.profile,
        'provider': provider,
        'experiences': experiences,
        'counts': counts,
        'current_status': status_filter,
        'search_query': search_query,
        'now': timezone.now(),
        'unread_count': get_unread_count_for_user(request.user),
    }

    return render(request, 'provider/my_experiences.html', context)


@login_required
def experience_detail(request, experience_id):
    if request.user.profile.role != 'provider':
        return redirect('tourist:dashboard')

    try:
        provider = request.user.profile.provider_profile
    except ProviderProfile.DoesNotExist:
        messages.error(request, 'Please complete your business profile first.')
        return redirect('provider:profile')

    experience = get_object_or_404(
        Experience.objects.select_related('category', 'provider'),
        id=experience_id,
        provider=provider
    )

    base_reviews = Review.objects.filter(
        experience=experience,
        review_type='experience'
    ).select_related(
        'visitor', 'visitor__profile', 'visitor__profile__user', 'booking'
    ).order_by('-created_at')

    approved_reviews = base_reviews.filter(moderation_status='approved')

    avg_rating = approved_reviews.aggregate(Avg('rating'))['rating__avg'] or 0
    total_reviews = approved_reviews.count()
    pending_reviews = base_reviews.filter(moderation_status='pending').count()
    rejected_reviews = base_reviews.filter(moderation_status='rejected').count()

    rating_breakdown = []
    for star in range(5, 0, -1):
        count = approved_reviews.filter(rating=star).count()
        percentage = (count / total_reviews * 100) if total_reviews > 0 else 0
        rating_breakdown.append({
            'star': star,
            'count': count,
            'percentage': percentage,
        })

    context = {
        'user': request.user,
        'profile': request.user.profile,
        'provider': provider,
        'experience': experience,
        'reviews': base_reviews[:10],
        'avg_rating': avg_rating,
        'total_reviews': total_reviews,
        'pending_reviews': pending_reviews,
        'rejected_reviews': rejected_reviews,
        'rating_breakdown': rating_breakdown,
        'now': timezone.now(),
        'unread_count': get_unread_count_for_user(request.user),
    }

    return render(request, 'provider/experience_detail.html', context)


@login_required
def create_experience(request):
    if request.user.profile.role != 'provider':
        return redirect('tourist:dashboard')

    try:
        provider = request.user.profile.provider_profile
    except ProviderProfile.DoesNotExist:
        messages.error(request, 'Please complete your business profile first.')
        return redirect('provider:profile')

    if not provider.is_verified:
        messages.error(request, 'Your business must be verified before you can create experiences.')
        return redirect('provider:profile')

    categories = Category.objects.filter(is_active=True)

    if request.method == 'POST':
        name = request.POST.get('name')
        description = request.POST.get('description')
        category_id = request.POST.get('category')
        location = request.POST.get('location')

        if not name or not description or not category_id:
            messages.error(request, 'Please fill in all required fields.')
            return render(request, 'provider/create_experience.html', {
                'provider': provider,
                'categories': categories,
                'now': timezone.now(),
                'unread_count': get_unread_count_for_user(request.user),
            })

        category = get_object_or_404(Category, id=category_id)
        listing_type = get_listing_type_from_category(category)

        experience = Experience(
            provider=provider,
            name=name,
            description=description,
            category=category,
            listing_type=listing_type,
            location=location or '',
            status='under_review',
            submitted_at=timezone.now(),
            is_available=False,
        )

        price_errors = read_price_fields_from_post(request.POST, experience)
        if price_errors:
            for e in price_errors:
                messages.error(request, e)
            return render(request, 'provider/create_experience.html', {
                'provider': provider,
                'categories': categories,
                'now': timezone.now(),
                'unread_count': get_unread_count_for_user(request.user),
            })

        if listing_type == 'food_dining':
            durations = [value for value in request.POST.getlist('duration_minutes') if value]
            duration = durations[0] if durations else ''
            if duration:
                try:
                    experience.duration_minutes = int(duration)
                except (ValueError, TypeError):
                    pass
            experience.cuisine_type = request.POST.get('cuisine_type', '')
            experience.meal_types = request.POST.get('meal_types', '')
            experience.features = request.POST.get('features', '')
            experience.contact_number = request.POST.get('contact_number', '')
            experience.contact_email = request.POST.get('contact_email', '')
            save_opening_hours(experience, request.POST)

        elif listing_type == 'places_to_stay':
            check_in = request.POST.get('check_in_time')
            check_out = request.POST.get('check_out_time')
            if check_in:
                experience.check_in_time = check_in
            if check_out:
                experience.check_out_time = check_out
            experience.amenities = request.POST.getlist('amenities')
            experience.cancellation_policy = request.POST.get('cancellation_policy', 'free_24h')
            if experience.cancellation_policy == 'custom':
                experience.cancellation_policy_custom = request.POST.get('cancellation_policy_custom', '')

        elif listing_type == 'attractions':
            save_opening_hours(experience, request.POST)
            duration = request.POST.get('duration_minutes')
            if duration:
                try:
                    experience.duration_minutes = int(duration)
                except (ValueError, TypeError):
                    pass

        else:
            try:
                experience.duration_minutes = int(request.POST.get('duration_minutes') or 60)
            except (ValueError, TypeError):
                experience.duration_minutes = 60
            experience.meeting_point = request.POST.get('meeting_point', '')
            experience.what_to_bring = request.POST.get('what_to_bring', '')
            experience.age_requirement = request.POST.get('age_requirement', '')
            experience.difficulty_level = request.POST.get('difficulty_level', '')
            experience.accessibility_info = request.POST.get('accessibility_info', '')
            languages_str = request.POST.get('languages', '')
            if languages_str:
                experience.languages = [lang.strip() for lang in languages_str.split(',') if lang.strip()]
            experience.cancellation_policy = request.POST.get('cancellation_policy', 'free_24h')
            if experience.cancellation_policy == 'custom':
                experience.cancellation_policy_custom = request.POST.get('cancellation_policy_custom', '')

        if request.FILES.get('image'):
            experience.main_image = request.FILES['image']

        experience.save()

        create_notification(
            recipient=request.user,
            notification_type='experience_submitted',
            title='Experience Submitted for Approval',
            message=f'Your experience "{experience.name}" has been submitted and is awaiting admin review.',
            link='/providers/my-experiences/',
            entity_type='Experience',
            entity_id=experience.id
        )

        from django.contrib.auth.models import User
        admins = User.objects.filter(profile__role='admin')
        for admin in admins:
            Notification.objects.create(
                recipient=admin,
                notification_type='experience_submitted',
                title='New Experience Submitted',
                message=f'"{experience.name}" has been submitted for approval by {provider.business_name}.',
                link=f'/admin_dashboard/experiences/{experience.id}/',
                entity_type='Experience',
                entity_id=experience.id
            )

        messages.success(request, f'"{experience.name}" has been submitted for approval! You will be notified once reviewed.')
        return redirect('provider:my_experiences')

    context = {
        'user': request.user,
        'profile': request.user.profile,
        'provider': provider,
        'categories': categories,
        'now': timezone.now(),
        'unread_count': get_unread_count_for_user(request.user),
    }

    return render(request, 'provider/create_experience.html', context)


@login_required
def edit_experience(request, experience_id):
    if request.user.profile.role != 'provider':
        return redirect('tourist:dashboard')

    try:
        provider = request.user.profile.provider_profile
    except ProviderProfile.DoesNotExist:
        messages.error(request, 'Please complete your business profile first.')
        return redirect('provider:profile')

    experience = get_object_or_404(Experience, id=experience_id, provider=provider)
    original_status = experience.status

    categories = Category.objects.filter(is_active=True)

    if request.method == 'POST':
        action = request.POST.get('action', 'save_changes')

        experience.name = request.POST.get('name', experience.name)
        experience.description = request.POST.get('description', experience.description)

        category_id = request.POST.get('category')
        if category_id:
            experience.category = get_object_or_404(Category, id=category_id)

        experience.listing_type = get_listing_type_from_category(experience.category)
        listing_type = experience.listing_type

        experience.location = request.POST.get('location', experience.location)

        price_errors = read_price_fields_from_post(request.POST, experience)
        if price_errors:
            for e in price_errors:
                messages.error(request, e)
            context = {
                'user': request.user,
                'profile': request.user.profile,
                'provider': provider,
                'experience': experience,
                'original_status': original_status,
                'categories': categories,
                'now': timezone.now(),
                'unread_count': get_unread_count_for_user(request.user),
            }
            return render(request, 'provider/edit_experience.html', context)

        if listing_type == 'food_dining':
            durations = [value for value in request.POST.getlist('duration_minutes') if value]
            duration = durations[0] if durations else ''
            if duration:
                try:
                    experience.duration_minutes = int(duration)
                except (ValueError, TypeError):
                    pass
            experience.cuisine_type = request.POST.get('cuisine_type', '')
            experience.meal_types = request.POST.get('meal_types', '')
            experience.features = request.POST.get('features', '')
            experience.contact_number = request.POST.get('contact_number', '')
            experience.contact_email = request.POST.get('contact_email', '')
            save_opening_hours(experience, request.POST)

        elif listing_type == 'places_to_stay':
            check_in = request.POST.get('check_in_time')
            check_out = request.POST.get('check_out_time')
            if check_in:
                experience.check_in_time = check_in
            if check_out:
                experience.check_out_time = check_out
            experience.amenities = request.POST.getlist('amenities')
            experience.cancellation_policy = request.POST.get('cancellation_policy', 'free_24h')
            if experience.cancellation_policy == 'custom':
                experience.cancellation_policy_custom = request.POST.get('cancellation_policy_custom', '')

        elif listing_type == 'attractions':
            save_opening_hours(experience, request.POST)
            duration = request.POST.get('duration_minutes')
            if duration:
                try:
                    experience.duration_minutes = int(duration)
                except (ValueError, TypeError):
                    pass

        else:
            duration = request.POST.get('duration_minutes')
            if duration:
                try:
                    experience.duration_minutes = int(duration)
                except (ValueError, TypeError):
                    pass
            experience.meeting_point = request.POST.get('meeting_point', '')
            experience.what_to_bring = request.POST.get('what_to_bring', '')
            experience.age_requirement = request.POST.get('age_requirement', '')
            experience.difficulty_level = request.POST.get('difficulty_level', '')
            experience.accessibility_info = request.POST.get('accessibility_info', '')
            languages_str = request.POST.get('languages', '')
            if languages_str:
                experience.languages = [lang.strip() for lang in languages_str.split(',') if lang.strip()]
            experience.cancellation_policy = request.POST.get('cancellation_policy', 'free_24h')
            if experience.cancellation_policy == 'custom':
                experience.cancellation_policy_custom = request.POST.get('cancellation_policy_custom', '')

        if request.FILES.get('image'):
            experience.main_image = request.FILES['image']

        experience.save()

        if original_status == 'published':
            experience.status = 'under_review'
            experience.submitted_at = timezone.now()
            experience.is_available = False
            experience.save()

            from django.contrib.auth.models import User
            admins = User.objects.filter(profile__role='admin')
            for admin in admins:
                Notification.objects.create(
                    recipient=admin,
                    notification_type='experience_updated',
                    title='Published Experience Edited',
                    message=f'{provider.business_name} edited published experience "{experience.name}". It has been sent back for approval.',
                    link=f'/admin_dashboard/experiences/{experience.id}/',
                    entity_type='Experience',
                    entity_id=experience.id
                )

            messages.success(request, f'"{experience.name}" was updated. It has been sent to admin for approval — it will be back online once approved.')
            return redirect('provider:experience_detail', experience_id=experience.id)

        if original_status == 'rejected' and action == 'submit_for_approval':
            experience.status = 'under_review'
            experience.submitted_at = timezone.now()
            experience.save()

            from django.contrib.auth.models import User
            admins = User.objects.filter(profile__role='admin')
            for admin in admins:
                Notification.objects.create(
                    recipient=admin,
                    notification_type='experience_updated',
                    title='Experience Resubmitted',
                    message=f'"{experience.name}" has been updated and resubmitted for approval by {provider.business_name}.',
                    link=f'/admin_dashboard/experiences/{experience.id}/',
                    entity_type='Experience',
                    entity_id=experience.id
                )

            messages.success(request, f'"{experience.name}" has been resubmitted for approval!')
            return redirect('provider:my_experiences')

        messages.success(request, f'"{experience.name}" updated successfully.')
        return redirect('provider:experience_detail', experience_id=experience.id)

    context = {
        'user': request.user,
        'profile': request.user.profile,
        'provider': provider,
        'experience': experience,
        'original_status': original_status,
        'categories': categories,
        'now': timezone.now(),
        'unread_count': get_unread_count_for_user(request.user),
    }

    return render(request, 'provider/edit_experience.html', context)


@login_required
@require_POST
def delete_experience(request, experience_id):
    if request.user.profile.role != 'provider':
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    try:
        provider = request.user.profile.provider_profile
    except ProviderProfile.DoesNotExist:
        return JsonResponse({'error': 'Provider not found'}, status=400)

    experience = get_object_or_404(Experience, id=experience_id, provider=provider)

    experience_name = experience.name
    experience.delete()
    create_notification(
        recipient=request.user,
        notification_type='experience_deleted',
        title='Experience Deleted',
        message=f'Your experience "{experience_name}" was deleted successfully.',
        link='/providers/my-experiences/',
        entity_type='Experience',
        entity_id=experience_id
    )
    return JsonResponse({'success': True, 'message': 'Experience deleted successfully'})


# ============ BOOKINGS ============

@login_required
def bookings(request):
    if request.user.profile.role != 'provider':
        return redirect('tourist:dashboard')

    try:
        provider = request.user.profile.provider_profile
    except ProviderProfile.DoesNotExist:
        messages.error(request, 'Please complete your business profile first.')
        return redirect('provider:profile')

    status_filter = request.GET.get('status', 'all')
    bookings = Booking.objects.filter(
        experience__provider=provider
    ).select_related(
        'experience', 'visitor', 'visitor__profile', 'visitor__profile__user'
    ).order_by('-created_at')

    if status_filter != 'all':
        bookings = bookings.filter(status=status_filter)

    counts = {
        'all': Booking.objects.filter(experience__provider=provider).count(),
        'pending': Booking.objects.filter(experience__provider=provider, status='pending').count(),
        'confirmed': Booking.objects.filter(experience__provider=provider, status='confirmed').count(),
        'completed': Booking.objects.filter(experience__provider=provider, status='completed').count(),
        'cancelled': Booking.objects.filter(experience__provider=provider, status='cancelled').count(),
        'rejected': Booking.objects.filter(experience__provider=provider, status='rejected').count(),
    }

    context = {
        'user': request.user,
        'profile': request.user.profile,
        'provider': provider,
        'bookings': bookings,
        'counts': counts,
        'current_status': status_filter,
        'now': timezone.now(),
        'unread_count': get_unread_count_for_user(request.user),
    }

    return render(request, 'provider/bookings.html', context)


# ============ REVIEWS ============
@login_required
def reviews(request):
    """Provider views reviews about their experiences.

    Shows approved + pending reviews. Rejected ones are hidden.
    Stats (avg rating + breakdown) reflect what the provider should see:
    approved + pending, so the numbers match the visible list.
    """
    if request.user.profile.role != 'provider':
        return redirect('tourist:dashboard')

    try:
        provider = request.user.profile.provider_profile
    except ProviderProfile.DoesNotExist:
        messages.error(request, 'Please complete your business profile first.')
        return redirect('provider:profile')

    # All experience reviews about this provider's experiences
    # Show approved + pending. Hide rejected (admin's call).
    reviews_qs = Review.objects.filter(
        experience__provider=provider,
        review_type='experience',
        moderation_status__in=['approved', 'pending'],
    ).select_related(
        'experience', 'visitor', 'visitor__profile', 'visitor__profile__user'
    ).order_by('-created_at')

    total = reviews_qs.count()
    avg_rating = reviews_qs.aggregate(Avg('rating'))['rating__avg'] or 0

    rating_breakdown = []
    for star in range(5, 0, -1):
        count = reviews_qs.filter(rating=star).count()
        percentage = (count / total * 100) if total > 0 else 0
        rating_breakdown.append({
            'star': star,
            'count': count,
            'percentage': percentage,
        })

    experiences_reviewed = reviews_qs.values('experience').distinct().count()

    context = {
        'user': request.user,
        'profile': request.user.profile,
        'provider': provider,
        'reviews': reviews_qs,
        'total': total,
        'avg_rating': avg_rating,
        'rating_breakdown': rating_breakdown,
        'experiences_reviewed': experiences_reviewed,
        'now': timezone.now(),
        'unread_count': get_unread_count_for_user(request.user),
    }

    return render(request, 'provider/reviews.html', context)