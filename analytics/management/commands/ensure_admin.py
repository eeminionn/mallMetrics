from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from analytics.models import AnalysisAuditLog, AnalysisRun, AppConfiguration, InsightNote, Mall, ZoneVersion


ROLE_GROUPS = ["Analista", "Supervisor", "Ejecutivo", "Administrador", "Auditor"]
DEMO_USERS = {
    "analista": "Analista",
    "supervisor": "Supervisor",
    "ejecutivo": "Ejecutivo",
    "auditor": "Auditor",
}


class Command(BaseCommand):
    help = "Create the local demo admin user if it does not exist."

    def handle(self, *args, **options):
        groups = {role: Group.objects.get_or_create(name=role)[0] for role in ROLE_GROUPS}
        self.configure_group_permissions(groups)

        user_model = get_user_model()
        user, created = user_model.objects.get_or_create(
            username="admin",
            defaults={"is_staff": True, "is_superuser": True},
        )
        user.is_staff = True
        user.is_superuser = True
        user.set_password("admin")
        user.save()

        for username, role in DEMO_USERS.items():
            demo_user, _ = user_model.objects.get_or_create(username=username)
            demo_user.is_staff = role in {"Administrador", "Auditor"}
            demo_user.is_superuser = False
            demo_user.set_password(username)
            demo_user.save()
            demo_user.groups.set([groups[role]])

        status = "created" if created else "updated"
        self.stdout.write(self.style.SUCCESS(f"Demo admin user {status}: admin / admin"))
        self.stdout.write(self.style.SUCCESS("Enterprise role groups ready: " + ", ".join(ROLE_GROUPS)))
        self.stdout.write(self.style.SUCCESS("Demo users ready: analista, supervisor, ejecutivo, auditor"))

    def configure_group_permissions(self, groups):
        analytics_models = [AnalysisRun, Mall, InsightNote, ZoneVersion, AnalysisAuditLog, AppConfiguration]
        all_permissions = []
        view_permissions = []
        for model in analytics_models:
            content_type = ContentType.objects.get_for_model(model)
            model_permissions = Permission.objects.filter(content_type=content_type)
            all_permissions.extend(model_permissions)
            view_permissions.extend(model_permissions.filter(codename__startswith="view_"))

        groups["Administrador"].permissions.set(all_permissions)
        groups["Auditor"].permissions.set(view_permissions)
        groups["Analista"].permissions.clear()
        groups["Supervisor"].permissions.clear()
        groups["Ejecutivo"].permissions.clear()
