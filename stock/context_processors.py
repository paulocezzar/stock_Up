from .views import user_departments, current_department


def nav(request):
    if not request.user.is_authenticated:
        return {}
    return {
        "departments": user_departments(request.user),
        "current_dept": current_department(request),
    }
