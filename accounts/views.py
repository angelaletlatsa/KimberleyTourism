from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import User
from django.db import transaction
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core import signing
from django.core.validators import validate_email
from django.core.signing import BadSignature, SignatureExpired
from django.utils import timezone
from datetime import timedelta
from django.http import JsonResponse
from django.conf import settings
import logging
from smtplib import SMTPException

from .models import Profile, AdminInvite
from .utils import send_email_verification, send_welcome_email

logger = logging.getLogger(__name__)


def home(request):
    return render(request, 'accounts/home.html')


def register_view(request):
    """
    Public registration.

    SECURITY RULE (FR-A01): Public registration may ONLY create accounts
    with role in ('tourist', 'guide', 'provider'). The 'admin' role is
    rejected on the backend, regardless of what the request body contains.

    Admin accounts are provisioned exclusively through the AdminInvite flow
    managed by the Owner account in the admin dashboard.
    """
    error = None

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')
        account_type = request.POST.get('account_type', 'tourist').strip().lower()
        terms = request.POST.get('terms')
        # ===== HARDENED: only three public roles are allowed =====
        ALLOWED_PUBLIC_ROLES = ['tourist', 'guide', 'provider']

        if not full_name or not email or not password or not confirm_password:
            error = "Please complete all required fields."
        elif not terms:
            error = "Please accept the terms before creating your account."
        elif len(full_name) < 2:
            error = "Please enter your full name."
        else:
            try:
                validate_email(email)
            except ValidationError:
                error = "Please enter a valid email address."

            if not error and password != confirm_password:
                error = "The passwords do not match."
            elif not error:
                try:
                    validate_password(password)
                except ValidationError as exc:
                    error = " ".join(exc.messages)

        if not error:
            if account_type not in ALLOWED_PUBLIC_ROLES:
                # This catches forged POSTs that try to submit 'admin'
                error = "Please select a valid account type."
            elif User.objects.filter(username=email).exists():
                error = "An account with this email already exists. Please log in."
            else:
                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=password,
                    first_name=full_name,
                    is_active=False,
                )
                profile = Profile.objects.create(
                    user=user,
                    role=account_type,
                    email_verified=False,
                    email_verification_sent_at=timezone.now(),
                )

                if account_type == 'provider':
                    from provider.models import ProviderProfile
                    ProviderProfile.objects.create(
                        profile=profile,
                        business_name=full_name,
                        business_description="",
                    )
                elif account_type == 'guide':
                    from guides.models import get_or_create_guide_profile
                    get_or_create_guide_profile(profile)
                elif account_type == 'tourist':
                    from tourist.models import TouristProfile
                    TouristProfile.objects.create(profile=profile)

                delivery_error = False
                try:
                    send_email_verification(user)
                except (SMTPException, OSError):
                    logger.exception("Could not send email verification message.")
                    delivery_error = True

                return render(request, 'accounts/verification_sent.html', {
                    'email': email,
                    'delivery_error': delivery_error,
                })

    return render(request, 'accounts/register.html', {'error': error})


def login_view(request):
    error = None
    verification_required = False

    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')

        if not email or not password:
            error = "Please enter your email address and password."
        else:
            pending_user = User.objects.filter(username=email).select_related('profile').first()
            if (
                pending_user
                and hasattr(pending_user, 'profile')
                and not pending_user.profile.email_verified
            ):
                error = "Please verify your email address before signing in."
                verification_required = True
            else:
                user = authenticate(request, username=email, password=password)

                if user is not None:
                    if hasattr(user, 'profile') and user.profile.is_suspended:
                        return render(request, 'accounts/suspended.html', {
                            'reason': user.profile.suspension_reason,
                            'suspended_at': user.profile.suspended_at,
                        })

                    login(request, user)

                    if hasattr(user, 'profile'):
                        role = user.profile.role

                        if role == 'guide':
                            return redirect('/guides/dashboard/')
                        elif role == 'provider':
                            return redirect('/providers/dashboard/')
                        elif role == 'admin':
                            return redirect('/admin_dashboard/')
                        else:
                            return redirect('/tourist/dashboard/')
                    else:
                        error = "Your account profile could not be found."
                else:
                    try:
                        existing_user = User.objects.select_related('profile').get(username=email)
                        if (
                            hasattr(existing_user, 'profile')
                            and existing_user.profile.is_suspended
                        ):
                            return render(request, 'accounts/suspended.html', {
                                'reason': existing_user.profile.suspension_reason,
                                'suspended_at': existing_user.profile.suspended_at,
                            })
                    except User.DoesNotExist:
                        pass

                    error = "The email or password is incorrect."

    return render(request, 'accounts/login.html', {
        'error': error,
        'verification_required': verification_required,
    })


def verify_email_view(request, token):
    try:
        user_id = signing.loads(
            token,
            salt='accounts.email_verification',
            max_age=settings.EMAIL_VERIFICATION_MAX_AGE,
        )
        user = User.objects.select_related('profile').get(pk=user_id)
        profile = user.profile
    except (BadSignature, SignatureExpired, User.DoesNotExist, ValueError, TypeError, AttributeError):
        return render(request, 'accounts/verify_email.html', {'state': 'invalid'})

    if profile.email_verified:
        return render(request, 'accounts/verify_email.html', {'state': 'already_verified'})

    if request.method == 'POST':
        with transaction.atomic():
            profile.email_verified = True
            profile.email_verified_at = timezone.now()
            profile.save(update_fields=['email_verified', 'email_verified_at'])
            user.is_active = True
            user.save(update_fields=['is_active'])
        send_welcome_email(user)
        return render(request, 'accounts/verify_email.html', {'state': 'verified'})

    return render(request, 'accounts/verify_email.html', {'state': 'confirm'})


def resend_verification_view(request):
    delivery_error = False
    submitted = False

    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        submitted = True
        user = User.objects.filter(username=email).select_related('profile').first()
        if user and hasattr(user, 'profile') and not user.profile.email_verified:
            now = timezone.now()
            last_sent_at = user.profile.email_verification_sent_at
            if last_sent_at is None or now - last_sent_at >= timedelta(minutes=1):
                user.profile.email_verification_sent_at = now
                user.profile.save(update_fields=['email_verification_sent_at'])
                try:
                    send_email_verification(user)
                except (SMTPException, OSError):
                    logger.exception("Could not resend email verification message.")
                    delivery_error = True

    return render(request, 'accounts/resend_verification.html', {
        'submitted': submitted,
        'delivery_error': delivery_error,
        'email': request.POST.get('email', '').strip(),
    })


def lookup_email_view(request):
    """
    AJAX endpoint: Look up a user by email and return their first name + role.
    Only returns minimal info — never leaks passwords or sensitive data.
    """
    email = request.GET.get('email', '').strip().lower()

    if not email:
        return JsonResponse({'found': False})

    try:
        user = User.objects.select_related('profile').get(username=email)
    except User.DoesNotExist:
        return JsonResponse({'found': False})

    profile = getattr(user, 'profile', None)
    if profile is None:
        return JsonResponse({'found': False})

    role_labels = {
        'tourist': 'Tourist',
        'guide': 'Tour Guide',
        'provider': 'Tourism Provider',
        'admin': 'Administrator',
    }

    return JsonResponse({
        'found': True,
        'first_name': user.first_name or 'there',
        'role': profile.role,
        'role_display': role_labels.get(profile.role, profile.role.title()),
        'is_suspended': profile.is_suspended,
    })


def logout_view(request):
    logout(request)
    return redirect('/')


# ============================================================
# ACCEPT ADMIN INVITE
# ============================================================

@transaction.atomic
def accept_admin_invite_view(request, token):
    """
    FR-A01: Admin Account Provisioning
    Traceability: UC-A01 Invite Administrator

    Public page reached by the invite link.
    If the token is valid:
        - GET: shows the "set your password" form
        - POST: creates the admin user with hashed password,
                marks the invite accepted, redirects to login
    """
    invite = get_object_or_404(
        AdminInvite.objects.select_for_update(),
        token=token,
    )

    # Expire lazily if the DB wasn't cleaned up
    if invite.status == 'pending' and invite.expires_at <= timezone.now():
        invite.mark_expired()

    # Guard states
    if invite.status == 'accepted':
        return render(request, 'accounts/accept_admin_invite.html', {
            'invite': invite,
            'state': 'already_accepted',
        })
    if invite.status == 'revoked':
        return render(request, 'accounts/accept_admin_invite.html', {
            'invite': invite,
            'state': 'revoked',
        })
    if invite.status == 'expired':
        return render(request, 'accounts/accept_admin_invite.html', {
            'invite': invite,
            'state': 'expired',
        })

    error = None

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if not full_name or not password or not confirm_password:
            error = "Please complete all fields."
        elif len(full_name) < 2:
            error = "Please enter your full name."
        elif password != confirm_password:
            error = "The passwords do not match."
        else:
            try:
                validate_password(password)
            except ValidationError as e:
                error = " ".join(e.messages)

        if not error:
            # Guard against someone registering this email in the meantime
            if User.objects.filter(username=invite.email).exists():
                error = "An account with this email already exists. Please log in."

        if not error:
            # Create the admin user (password hashed by create_user)
            user = User.objects.create_user(
                username=invite.email,
                email=invite.email,
                password=password,
                first_name=full_name,
            )
            Profile.objects.create(user=user, role='admin')

            invite.mark_accepted(user)

            # Notify the inviter (best-effort)
            if invite.invited_by:
                try:
                    from notifications.utils import create_notification
                    create_notification(
                        recipient=invite.invited_by,
                        notification_type='welcome',
                        title='Admin invitation accepted',
                        message=f'{full_name} accepted your admin invite and joined as an administrator.',
                        link='/admin_dashboard/admins/',
                        entity_type='AdminInvite',
                        entity_id=invite.id,
                    )
                except Exception:
                    pass

            return redirect('/accounts/login/?invited=1')

    context = {
        'invite': invite,
        'state': 'valid',
        'error': error,
    }
    return render(request, 'accounts/accept_admin_invite.html', context)