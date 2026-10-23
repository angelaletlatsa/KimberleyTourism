import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Profile


class Command(BaseCommand):
    help = "Create the optional Render demo owner account from environment variables."

    def handle(self, *args, **options):
        username = os.environ.get("DEMO_ADMIN_USERNAME", "").strip()
        email = os.environ.get("DEMO_ADMIN_EMAIL", "").strip()
        password = os.environ.get("DEMO_ADMIN_PASSWORD", "")

        if not any((username, email, password)):
            self.stdout.write("Demo owner credentials are not configured; skipping.")
            return
        if not all((username, email, password)):
            raise CommandError(
                "Set DEMO_ADMIN_USERNAME, DEMO_ADMIN_EMAIL, and DEMO_ADMIN_PASSWORD together."
            )

        user_model = get_user_model()
        with transaction.atomic():
            user = user_model.objects.filter(username=username).first()
            if user is None:
                user = user_model.objects.create_superuser(
                    username=username,
                    email=email,
                    password=password,
                )
                self.stdout.write("Created the demo owner account.")
            elif not user.is_superuser:
                raise CommandError(
                    "The configured demo owner username already belongs to a non-superuser. "
                    "Choose a different DEMO_ADMIN_USERNAME."
                )
            else:
                self.stdout.write("Demo owner account already exists; leaving its password unchanged.")

            Profile.objects.get_or_create(user=user, defaults={"role": "admin"})
