from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone
from django.core import signing
from django.urls import reverse
import logging
from urllib.parse import urljoin

logger = logging.getLogger(__name__)


def send_email_verification(user):
    """Send a time-limited, signed email ownership confirmation link."""
    token = signing.dumps(user.pk, salt='accounts.email_verification')
    verification_path = reverse('accounts:verify_email', kwargs={'token': token})
    verification_url = urljoin(
        f"{settings.SITE_URL.rstrip('/')}/",
        verification_path.lstrip('/'),
    )
    context = {
        'user_name': user.first_name or user.get_full_name() or user.username,
        'verification_url': verification_url,
        'verification_expiry_hours': settings.EMAIL_VERIFICATION_MAX_AGE // 3600,
        'current_year': timezone.now().year,
    }
    text_content = (
        f"Hello {context['user_name']},\n\n"
        "Please confirm your email address for Explore Kimberley by opening this link:\n"
        f"{verification_url}\n\n"
        f"This link expires in {context['verification_expiry_hours']} hours. "
        "If you did not create this account, you can ignore this email."
    )
    html_content = render_to_string(
        'accounts/emails/email_verification.html',
        context,
    )
    message = EmailMultiAlternatives(
        subject='Confirm your Explore Kimberley email address',
        body=text_content,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    message.attach_alternative(html_content, 'text/html')
    message.send(fail_silently=False)


def send_welcome_email(user):
    """Send a professional welcome email to a newly registered user."""
    try:
        role_urls = {
            'tourist': '/tourist/dashboard/',
            'guide': '/guides/dashboard/',
            'provider': '/providers/dashboard/',
            'admin': '/admin_dashboard/',
        }
        dashboard_path = role_urls.get(user.profile.role, '/')
        dashboard_url = urljoin(
            f"{settings.SITE_URL.rstrip('/')}/",
            dashboard_path.lstrip('/'),
        )

        role_labels = {
            'tourist': 'Tourist',
            'guide': 'Tour Guide',
            'provider': 'Tourism Provider',
            'admin': 'Administrator',
        }

        context = {
            'user_name': user.first_name or user.get_full_name() or user.username,
            'user_email': user.email,
            'role': user.profile.role,
            'role_label': role_labels.get(user.profile.role, user.profile.role.title()),
            'dashboard_url': dashboard_url,
            'current_year': timezone.now().year,
            'support_email': 'explore.kimberleytours@gmail.com',
        }

        html_content = render_to_string('accounts/emails/welcome_email.html', context)

        text_content = f"""Welcome to Explore Kimberley, {context['user_name']}!

Thank you for joining us. You've registered as a {context['role_label']}.

Visit your dashboard to get started:
{dashboard_url}

If you have any questions, just reply to this email or contact us at {context['support_email']}.

- The Explore Kimberley Team
        """.strip()

        msg = EmailMultiAlternatives(
            subject=f"Welcome to Explore Kimberley, {context['user_name']}!",
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
            reply_to=[context['support_email']],
        )
        msg.attach_alternative(html_content, "text/html")
        msg.send(fail_silently=True)

        logger.info(f"Welcome email sent to {user.email} (role: {user.profile.role})")
    except Exception as e:
        logger.error(f"Failed to send welcome email to {user.email}: {e}")


def send_suspension_email(user, reason):
    """Send suspension notification email to a user."""
    try:
        role_labels = {
            'tourist': 'Tourist',
            'guide': 'Tour Guide',
            'provider': 'Tourism Provider',
            'admin': 'Administrator',
        }

        context = {
            'user_name': user.first_name or user.get_full_name() or user.username,
            'role_label': role_labels.get(user.profile.role, user.profile.role.title()),
            'reason': reason,
            'current_year': timezone.now().year,
            'support_email': 'explore.kimberleytours@gmail.com',
        }

        html_content = render_to_string('accounts/emails/suspension_email.html', context)

        text_content = f"""Hello {context['user_name']},

Your Explore Kimberley account has been suspended.

Reason: {reason}

If you believe this was a mistake, please contact us at {context['support_email']} to appeal.

- The Explore Kimberley Team
        """.strip()

        msg = EmailMultiAlternatives(
            subject='Your Explore Kimberley Account Has Been Suspended',
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
            reply_to=[context['support_email']],
        )
        msg.attach_alternative(html_content, "text/html")
        msg.send(fail_silently=True)

        logger.info(f"Suspension email sent to {user.email}")
    except Exception as e:
        logger.error(f"Failed to send suspension email to {user.email}: {e}")


def send_tour_completed_email(booking):
    """Send a 'tour completed - please leave a review' email to the tourist."""
    try:
        recipient = booking.visitor.profile.user
        if not recipient or not recipient.email:
            return

        guide_name = booking.guide.full_name if booking.guide else None
        experience_name = booking.experience.name if booking.experience else None

        if guide_name and experience_name:
            subject_line = f'{guide_name} - {experience_name}'
        elif guide_name:
            subject_line = guide_name
        elif experience_name:
            subject_line = experience_name
        else:
            subject_line = 'your tour'

        context = {
            'tourist_name': recipient.first_name or recipient.get_full_name() or recipient.username,
            'guide_name': guide_name,
            'experience_name': experience_name,
            'booking': booking,
            'tour_date': booking.booking_date,
            'subject_line': subject_line,
            'review_url': f'{settings.SITE_URL}/reviews/create/{booking.id}/',
            'bookings_url': f'{settings.SITE_URL}/bookings/my/',
            'current_year': timezone.now().year,
            'support_email': 'explore.kimberleytours@gmail.com',
        }

        html_content = render_to_string('accounts/emails/tour_completed_email.html', context)

        text_content = f"""Hi {context['tourist_name']},

Great news - your tour with {subject_line} on {booking.booking_date.strftime('%d %b %Y')} is now marked as complete.

We hope you had a wonderful experience.

Would you take a minute to leave a review? It helps other travellers discover the best of Kimberley, and it supports your guide.

Leave a review: {context['review_url']}

Thanks for exploring Kimberley with us.

- The Explore Kimberley Team
        """.strip()

        msg = EmailMultiAlternatives(
            subject=f'How was your tour with {subject_line}?',
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient.email],
            reply_to=[context['support_email']],
        )
        msg.attach_alternative(html_content, "text/html")
        msg.send(fail_silently=True)

        logger.info(f"Tour completed email sent to {recipient.email} for booking #{booking.id}")
    except Exception as e:
        logger.error(f"Failed to send tour completed email for booking #{booking.id}: {e}")


def send_admin_invite_email(invite):
    """
    FR-A01: Admin Account Provisioning
    Traceability: UC-A01 Invite Administrator

    Send the admin invite email containing the unique one-time link.
    """
    accept_url = f"{settings.SITE_URL.rstrip('/')}/accounts/accept-admin-invite/{invite.token}/"

    inviter = invite.invited_by
    owner_email = settings.OWNER_EMAIL_HOST_USER.strip()
    if not owner_email or not settings.OWNER_EMAIL_HOST_PASSWORD:
        raise RuntimeError(
            'Owner invitation email is not configured. Set '
            'OWNER_EMAIL_HOST_USER and OWNER_EMAIL_HOST_PASSWORD.'
        )
    if not inviter or inviter.email.strip().lower() != owner_email.lower():
        raise RuntimeError(
            'The Owner invitation sender must match the inviting Owner account.'
        )

    connection = None
    if settings.EMAIL_BACKEND == 'django.core.mail.backends.smtp.EmailBackend':
        connection = get_connection(
            settings.EMAIL_BACKEND,
            host=settings.OWNER_EMAIL_HOST,
            port=settings.OWNER_EMAIL_PORT,
            username=owner_email,
            password=settings.OWNER_EMAIL_HOST_PASSWORD,
            use_tls=settings.OWNER_EMAIL_USE_TLS,
            fail_silently=False,
        )
    else:
        connection = get_connection(fail_silently=False)

    inviter_name = (
        inviter.get_full_name() or inviter.first_name or inviter.username
        if inviter else 'The Explore Kimberley Team'
    )

    context = {
        'invite': invite,
        'invitee_email': invite.email,
        'inviter_name': inviter_name,
        'accept_url': accept_url,
        'expires_at': invite.expires_at,
        'expires_days': invite.INVITE_VALID_DAYS,
        'personal_message': invite.message or '',
        'current_year': timezone.now().year,
        'support_email': 'explore.kimberleytours@gmail.com',
    }

    html_content = render_to_string('accounts/emails/admin_invite.html', context)

    text_content = f"""Hello,

{inviter_name} has invited you to join Explore Kimberley as an administrator.

{('Personal message: ' + invite.message) if invite.message else ''}

Accept your invitation and set your password here:
{accept_url}

This link expires on {invite.expires_at.strftime('%d %b %Y')} ({invite.INVITE_VALID_DAYS} days from invite).

If you were not expecting this invitation, you can safely ignore this email.

- The Explore Kimberley Team
    """.strip()

    msg = EmailMultiAlternatives(
        subject='You have been invited to Explore Kimberley as an Administrator',
        body=text_content,
        from_email=f'Explore Kimberley <{owner_email}>',
        to=[invite.email],
        reply_to=[owner_email],
        connection=connection,
    )
    msg.attach_alternative(html_content, "text/html")
    sent_count = msg.send(fail_silently=False)
    if sent_count != 1:
        raise RuntimeError(f"Invitation email was not sent to {invite.email}.")

    logger.info("Admin invite email sent to %s (invite #%s)", invite.email, invite.id)