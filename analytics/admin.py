from django.contrib import admin

from .models import AnalysisRun


@admin.register(AnalysisRun)
class AnalysisRunAdmin(admin.ModelAdmin):
    list_display = ("display_name", "status", "progress", "confirmed_people", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("name", "video")
    readonly_fields = ("id", "created_at", "updated_at", "started_at", "finished_at")
