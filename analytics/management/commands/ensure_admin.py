from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create the local demo admin user if it does not exist."

    def handle(self, *args, **options):
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
