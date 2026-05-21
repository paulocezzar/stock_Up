"""Create a superuser from ADMIN_USER / ADMIN_PASS / ADMIN_EMAIL env vars.
Idempotent and safe on every deploy. No data is seeded — you add it in the app."""
import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = "Create admin user from env vars if it doesn't exist."

    def handle(self, *args, **opts):
        User = get_user_model()
        u, p = os.environ.get("ADMIN_USER"), os.environ.get("ADMIN_PASS")
        e = os.environ.get("ADMIN_EMAIL", "")
        if not (u and p):
            self.stdout.write("  ADMIN_USER/ADMIN_PASS not set - skipping")
            return
        if User.objects.filter(username=u).exists():
            self.stdout.write(f"  superuser '{u}' already exists")
        else:
            User.objects.create_superuser(u, e, p)
            self.stdout.write(self.style.SUCCESS(f"  superuser '{u}' created"))
