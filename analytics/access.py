from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect


ROLE_ADMIN = "Administrador"
ROLE_ANALYST = "Analista"
ROLE_SUPERVISOR = "Supervisor"
ROLE_EXECUTIVE = "Ejecutivo"
ROLE_AUDITOR = "Auditor"

ROLE_GROUPS = [ROLE_ANALYST, ROLE_SUPERVISOR, ROLE_EXECUTIVE, ROLE_ADMIN, ROLE_AUDITOR]


def user_role(user):
    if not user or not user.is_authenticated:
        return "Invitado"
    if user.is_superuser:
        return ROLE_ADMIN
    group = user.groups.filter(name__in=ROLE_GROUPS).order_by("name").first()
    return group.name if group else ROLE_ANALYST


def has_role(user, *roles):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=roles).exists()


def role_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if has_role(request.user, *roles):
                return view_func(request, *args, **kwargs)
            messages.error(request, "Tu rol no tiene permiso para realizar esta accion.")
            return redirect("dashboard")
        return wrapper
    return decorator


def permission_flags(user):
    role = user_role(user)
    return {
        "active_role": role,
        "can_configure": has_role(user, ROLE_ADMIN),
        "can_admin": has_role(user, ROLE_ADMIN, ROLE_AUDITOR),
        "can_create_analysis": has_role(user, ROLE_ADMIN, ROLE_ANALYST),
        "can_manage_establishments": has_role(user, ROLE_ADMIN, ROLE_SUPERVISOR),
        "can_edit_analysis": has_role(user, ROLE_ADMIN, ROLE_ANALYST, ROLE_SUPERVISOR),
        "can_delete": has_role(user, ROLE_ADMIN),
        "can_view_reports": has_role(user, ROLE_ADMIN, ROLE_ANALYST, ROLE_SUPERVISOR, ROLE_EXECUTIVE, ROLE_AUDITOR),
    }
