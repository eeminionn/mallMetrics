from django.contrib.auth import views as auth_views
from django.urls import path

from . import views


urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("login/", auth_views.LoginView.as_view(template_name="analytics/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("malls/", views.mall_board, name="mall_board"),
    path("malls/<int:pk>/", views.mall_detail, name="mall_detail"),
    path("malls/<int:pk>/delete/", views.delete_mall, name="delete_mall"),
    path("analyses/", views.analysis_list, name="analysis_list"),
    path("malls/create/", views.create_mall, name="create_mall"),
    path("analyses/new/", views.video_upload, name="video_upload"),
    path("analyses/<uuid:pk>/move-mall/", views.move_analysis_to_mall, name="move_analysis_to_mall"),
    path("analyses/<uuid:pk>/rename/", views.rename_analysis, name="rename_analysis"),
    path("analyses/<uuid:pk>/unassign/", views.unassign_analysis, name="unassign_analysis"),
    path("analyses/<uuid:pk>/zones/", views.zone_editor, name="zone_editor"),
    path("analyses/<uuid:pk>/status/", views.analysis_status, name="analysis_status"),
    path("analyses/<uuid:pk>/start/", views.start_analysis, name="start_analysis"),
    path("analyses/<uuid:pk>/cancel/", views.cancel_analysis, name="cancel_analysis"),
    path("analyses/<uuid:pk>/delete/", views.delete_analysis, name="delete_analysis"),
    path("analyses/<uuid:pk>/progress/", views.analysis_progress, name="analysis_progress"),
    path("analyses/<uuid:pk>/results/", views.analysis_results, name="analysis_results"),
    path("reports/", views.reports, name="reports"),
    path("reports/<uuid:pk>/", views.reports, name="reports_for_analysis"),
    path("reports/analysis/<uuid:pk>/download/", views.download_analysis_report, name="download_analysis_report"),
    path("reports/mall/<int:pk>/download/", views.download_mall_report, name="download_mall_report"),
]
