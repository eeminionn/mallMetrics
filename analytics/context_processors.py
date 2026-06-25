from .access import permission_flags


def access_context(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    return permission_flags(request.user)
