import logging

from django.contrib.auth.forms import PasswordResetForm


logger = logging.getLogger(__name__)


class DiagnosticPasswordResetForm(PasswordResetForm):
    def get_users(self, email):
        users = list(super().get_users(email))
        if users:
            logger.warning(
                'Password reset matched %d eligible account(s); attempting email delivery.',
                len(users),
            )
        else:
            logger.warning(
                'Password reset found no active account with a usable password for the submitted address.'
            )
        yield from users