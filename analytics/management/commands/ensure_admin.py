from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand


ROLE_GROUPS = ["Analista", "Supervisor", "Ejecutivo", "Administrador", "Auditor"]


class Command(BaseCommand):
    help = "Create the local demo admin user if it does not exist."

    def handle(self, *args, **options):
        for role in ROLE_GROUPS:
            Group.objects.get_or_create(name=role)

        user_model = get_user_model()
        user, created = user_model.objects.get_or_create(
            username="admin",
            defaults={"is_staff": True, "is_superuser": True},
        )
        user.is_staff = True
        user.is_superuser = True
        user.set_password("admin")
        user.save()

        status = "created" if created else "updated"
        self.stdout.write(self.style.SUCCESS(f"Demo admin user {status}: admin / admin"))
        self.stdout.write(self.style.SUCCESS("Enterprise role groups ready: " + ", ".join(ROLE_GROUPS)))
