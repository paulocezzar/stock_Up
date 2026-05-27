"""Create the superuser from env vars and ensure a starter department exists,
so the very first login isn't a dead end. Idempotent."""
import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from stock.models import Department


class Command(BaseCommand):
    help = "Create admin user from env vars + a default department if none exist."

    def handle(self, *args, **opts):
        User = get_user_model()
        u, p = os.environ.get("ADMIN_USER"), os.environ.get("ADMIN_PASS")
        e = os.environ.get("ADMIN_EMAIL", "")
        user = None
        if u and p:
            user = User.objects.filter(username=u).first()
            if user:
                self.stdout.write(f"  superuser '{u}' already exists")
            else:
                user = User.objects.create_superuser(u, e, p)
                self.stdout.write(self.style.SUCCESS(f"  superuser '{u}' created"))
        else:
            self.stdout.write("  ADMIN_USER/ADMIN_PASS not set - skipping superuser")

        if not Department.objects.exists():
            dept = Department.objects.create(name="Bakery")
            if user:
                dept.members.add(user)
            self.stdout.write(self.style.SUCCESS("  created starter department 'Bakery'"))
        else:
            self.stdout.write("  departments already exist - skipping")
