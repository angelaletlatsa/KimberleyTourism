from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
import secrets


class Profile(models.Model):
    ROLE_CHOICES = [
        ('tourist', 'Tourist'),
        ('guide', 'Tour Guide'),
        ('provider', 'Tourism Provider'),
        ('admin', 'Administrator'),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='profile'
    )

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='tourist'
    )

    # Additional profile fields
    phone = models.CharField(max_length=20, blank=True, null=True)
    profile_picture = models.ImageField(upload_to='profiles/', blank=True, null=True)
    bio = models.TextField(blank=True, null=True)

    # For guides
    is_verified = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=True)
    email_verified_at = models.DateTimeField(blank=True, null=True)
    email_verification_sent_at = models.DateTimeField(blank=True, null=True)
    verification_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending Verification'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('suspended', 'Suspended'),
        ],
        default='pending'
    )

    # ============ SUSPENSION FIELDS ============
    is_suspended = models.BooleanField(
        default=False,
        help_text="Has this user been suspended by an admin?"
    )
    suspension_reason = models.TextField(
        blank=True,
        help_text="Reason for suspension"
    )
    suspended_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the user was suspended"
    )
    suspended_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='suspended_users',
        help_text="Which admin suspended this user"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=['tourist', 'guide', 'provider', 'admin']),
                name='profile_role_valid',
            ),
            models.CheckConstraint(
                condition=models.Q(
                    verification_status__in=['pending', 'approved', 'rejected', 'suspended']
                ),
                name='profile_verification_valid',
            ),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.role}"

    def get_dashboard_url(self):
        """Return the appropriate dashboard URL based on role"""
        role_urls = {
            'tourist': '/accounts/tourist/',
            'guide': '/accounts/guide/',
            'provider': '/accounts/provider/',
            'admin': '/accounts/admin/',
        }
        return role_urls.get(self.role, '/accounts/tourist/')

    @property
    def is_active(self):
        """User is considered active if their Django user is active AND not suspended"""
        return self.user.is_active and not self.is_suspended

    @property
    def status_label(self):
        """Human-readable status for display"""
        if self.is_suspended:
            return 'Suspended'
        elif not self.user.is_active:
            return 'Inactive'
        return 'Active'

    @property
    def status_class(self):
        """CSS class for status display"""
        if self.is_suspended:
            return 'suspended'
        elif not self.user.is_active:
            return 'inactive'
        return 'active'


class AdminInvite(models.Model):
    """
    FR-A01: Admin Account Provisioning
    Traceability: UC-A01 Invite Administrator

    A one-time invitation from an existing Administrator (Owner) to a
    prospective staff member. The invite creates an account with role='admin'
    when the invitee follows the link and sets a password.

    Public registration NEVER creates admin accounts. This is the only
    path (besides the initial createsuperuser at deployment).
    """

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('revoked', 'Revoked'),
        ('expired', 'Expired'),
    ]

    INVITE_VALID_DAYS = 7

    # Who is being invited
    email = models.EmailField(db_index=True)

    # Optional personal message from the inviter
    message = models.TextField(blank=True, help_text="Optional note shown in the invite email")

    # The one-time token (64 hex chars). Never guessable.
    token = models.CharField(max_length=64, unique=True, db_index=True)

    # Who sent the invite (nulled out if the inviter is deleted — audit history survives)
    invited_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='sent_admin_invites',
    )

    # Who accepted (nulled out if the invitee is deleted — audit history survives)
    accepted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='accepted_admin_invites',
    )

    # Lifecycle
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Admin Invitation"
        verbose_name_plural = "Admin Invitations"
        indexes = [
            models.Index(fields=['email', 'status']),
            models.Index(fields=['expires_at']),
            models.Index(fields=['status', 'created_at']),
        ]
        # Hard DB rule: only ONE pending invite per email at a time.
        # Prevents duplicate invites / accidental double-clicks.
        constraints = [
            models.UniqueConstraint(
                fields=['email'],
                condition=models.Q(status='pending'),
                name='unique_pending_admin_invite_per_email',
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=['pending', 'accepted', 'revoked', 'expired']),
                name='admininvite_status_valid',
            ),
        ]

    def __str__(self):
        return f"Invite for {self.email} ({self.status})"

    # ============ HELPERS ============

    def is_valid(self):
        """True only if the invite is pending and not expired."""
        return (
            self.status == 'pending'
            and self.expires_at > timezone.now()
        )

    def save(self, *args, **kwargs):
        """Auto-generate token and expiry on first save."""
        if not self.token:
            self.token = secrets.token_hex(32)
        if not self.expires_at:
            self.expires_at = timezone.now() + timezone.timedelta(days=self.INVITE_VALID_DAYS)
        super().save(*args, **kwargs)

    def mark_accepted(self, user):
        """Mark this invite as accepted by the given user."""
        self.status = 'accepted'
        self.accepted_by = user
        self.accepted_at = timezone.now()
        self.save(update_fields=['status', 'accepted_by', 'accepted_at'])

    def mark_revoked(self):
        """Revoke a pending invite."""
        self.status = 'revoked'
        self.revoked_at = timezone.now()
        self.save(update_fields=['status', 'revoked_at'])

    def mark_expired(self):
        """Mark a pending invite as expired (lazy — called on access)."""
        self.status = 'expired'
        self.save(update_fields=['status'])