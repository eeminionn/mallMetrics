from django.contrib import admin

from .models import AnalysisAuditLog, AnalysisRun, InsightNote, Mall, ZoneVersion


@admin.register(AnalysisRun)
class AnalysisRunAdmin(admin.ModelAdmin):
    list_display = ("display_name", "status", "progress", "confirmed_people", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("name", "video")
    readonly_fields = ("id", "created_at", "updated_at", "started_at", "finished_at")


@admin.register(Mall)
class MallAdmin(admin.ModelAdmin):
    list_display = ("name", "accent_color", "created_at", "updated_at")
    search_fields = ("name", "notes")


@admin.register(InsightNote)
class InsightNoteAdmin(admin.ModelAdmin):
    list_display = ("analysis", "insight_key", "created_by", "updated_at")
    list_filter = ("insight_key", "updated_at")
    search_fields = ("analysis__name", "body", "insight_key")


@admin.register(ZoneVersion)
class ZoneVersionAdmin(admin.ModelAdmin):
    list_display = ("analysis", "version", "created_by", "created_at")
    list_filter = ("created_at",)
    search_fields = ("analysis__name", "note")
    readonly_fields = ("created_at",)


@admin.register(AnalysisAuditLog)
class AnalysisAuditLogAdmin(admin.ModelAdmin):
    list_display = ("action", "analysis", "mall", "actor", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("analysis__name", "mall__name", "actor__username")
    readonly_fields = ("created_at",)
