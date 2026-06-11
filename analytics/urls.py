from django.contrib.auth import views as auth_views
from django.urls import path

from . import views


urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("login/", auth_views.LoginView.as_view(template_name="analytics/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("analyses/", views.analysis_list, name="analysis_list"),
    path("analyses/new/", views.video_upload, name="video_upload"),
    path("analyses/<uuid:pk>/zones/", views.zone_editor, name="zone_editor"),
    path("analyses/<uuid:pk>/status/", views.analysis_status, name="analysis_status"),
    path("analyses/<uuid:pk>/start/", views.start_analysis, name="start_analysis"),
    path("analyses/<uuid:pk>/cancel/", views.cancel_analysis, name="cancel_analysis"),
    path("analyses/<uuid:pk>/progress/", views.analysis_progress, name="analysis_progress"),
    path("analyses/<uuid:pk>/results/", views.analysis_results, name="analysis_results"),
    path("reports/", views.reports, name="reports"),
    path("reports/<uuid:pk>/", views.reports, name="reports_for_analysis"),
]
