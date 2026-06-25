import re
import uuid
from pathlib import Path
from shutil import rmtree

from django.conf import settings
from django.db import models
from django.utils import timezone


def format_context_label(value):
    text = str(value or "").strip()
    text = re.sub(r"(?<=[^\W\d_])(?=\d)", " ", text, flags=re.UNICODE)
    text = re.sub(r"(?<=\d)(?=[^\W\d_])", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text)


class Mall(models.Model):
    name = models.CharField(max_length=140, unique=True)
    accent_color = models.CharField(max_length=7, default="#2563eb")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class AppConfiguration(models.Model):
    openai_api_key = models.CharField(max_length=255, blank=True)
    openai_model = models.CharField(max_length=80, default="gpt-4o-mini")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuracion"
        verbose_name_plural = "Configuracion"

    def __str__(self):
        return "Configuracion PIPOLMETRICS"

    @classmethod
    def get_solo(cls):
        config, _ = cls.objects.get_or_create(pk=1)
        return config

    @property
    def has_openai_key(self):
        return bool(self.openai_api_key.strip())

    @property
    def masked_openai_key(self):
        key = self.openai_api_key.strip()
        if not key:
            return "Sin configurar"
        return f"{key[:7]}...{key[-4:]}" if len(key) > 12 else "Configurada"


class AnalysisRun(models.Model):
    class AnalysisType(models.TextChoices):
        PEDESTRIAN = "pedestrian", "Establecimiento peatonal"
        PARKING = "parking", "Estacionamiento"

    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        READY = "ready", "Listo"
        RUNNING = "running", "Analizando"
        COMPLETED = "completed", "Completado"
        FAILED = "failed", "Fallido"
        CANCELED = "canceled", "Cancelado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160, blank=True)
    analysis_type = models.CharField(
        max_length=20,
        choices=AnalysisType.choices,
        default=AnalysisType.PEDESTRIAN,
        db_index=True,
    )
    mall_group = models.ForeignKey(
        Mall,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="analyses",
    )
    mall = models.CharField(max_length=140, blank=True, db_index=True)
    category = models.CharField(max_length=140, blank=True, db_index=True)
    area = models.CharField(max_length=140, blank=True)
    video = models.FileField(upload_to="videos/")
    first_frame = models.FileField(upload_to="frames/", blank=True)

    frame_width = models.PositiveIntegerField(default=0)
    frame_height = models.PositiveIntegerField(default=0)
    fps = models.FloatField(default=0)
    total_frames = models.PositiveIntegerField(default=0)

    zones = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    progress = models.PositiveSmallIntegerField(default=0)
    processed_frames = models.PositiveIntegerField(default=0)
    confirmed_people = models.PositiveIntegerField(default=0)
    status_message = models.CharField(max_length=255, blank=True)
    error_message = models.TextField(blank=True)
    output_dir = models.CharField(max_length=255, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="analysis_runs",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        if self.name:
            return self.name
        return Path(self.video.name).name

    @property
    def is_parking(self):
        return self.analysis_type == self.AnalysisType.PARKING

    @property
    def domain_label(self):
        return "Estacionamiento" if self.is_parking else "Establecimiento peatonal"

    @property
    def entity_label_plural(self):
        return "vehiculos" if self.is_parking else "personas"

    @property
    def entity_label_singular(self):
        return "vehiculo" if self.is_parking else "persona"

    @property
    def output_path(self):
        if self.output_dir:
            return Path(self.output_dir)
        return Path(settings.MEDIA_ROOT) / "analysis" / str(self.id)

    @property
    def report_media_prefix(self):
        return f"{settings.MEDIA_URL}analysis/{self.id}/"

    @property
    def results_database_path(self):
        return self.output_path / "analysis_results.sqlite3"

    @property
    def grouping_label(self):
        parts = [self.mall_label, self.category_label, self.area_label]
        return " / ".join(part for part in parts if part) or "Sin clasificar"

    @property
    def mall_name(self):
        if self.mall_group_id:
            return self.mall_group.name
        return self.mall

    @property
    def mall_label(self):
        return format_context_label(self.mall_name)

    @property
    def category_label(self):
        return format_context_label(self.category)

    @property
    def area_label(self):
        return format_context_label(self.area)

    def delete_artifacts(self):
        media_root = Path(settings.MEDIA_ROOT).resolve()
        candidates = [self.video.path if self.video else "", self.first_frame.path if self.first_frame else ""]
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate)
            try:
                if path.exists() and path.resolve().is_relative_to(media_root):
                    path.unlink()
            except OSError:
                pass

        output_path = self.output_path
        try:
            if output_path.exists() and output_path.resolve().is_relative_to(media_root):
                rmtree(output_path, ignore_errors=True)
        except OSError:
            pass

    def mark_running(self):
        self.status = self.Status.RUNNING
        self.progress = 0
        self.status_message = "Preparando analisis"
        self.error_message = ""
        self.started_at = timezone.now()
        self.finished_at = None
        self.output_dir = str(self.output_path)
        self.save(update_fields=[
            "status",
            "progress",
            "status_message",
            "error_message",
            "started_at",
            "finished_at",
            "output_dir",
            "updated_at",
        ])


class InsightNote(models.Model):
    analysis = models.ForeignKey(
        AnalysisRun,
        on_delete=models.CASCADE,
        related_name="insight_notes",
    )
    insight_key = models.CharField(max_length=80, db_index=True)
    body = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="insight_notes",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["insight_key"]
        unique_together = [("analysis", "insight_key")]

    def __str__(self):
        return f"{self.analysis.display_name} / {self.insight_key}"


class ZoneVersion(models.Model):
    analysis = models.ForeignKey(
        AnalysisRun,
        on_delete=models.CASCADE,
        related_name="zone_versions",
    )
    version = models.PositiveIntegerField(default=1)
    zones = models.JSONField(default=list)
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="zone_versions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("analysis", "version")]

    def __str__(self):
        return f"{self.analysis.display_name} v{self.version}"


class AnalysisAuditLog(models.Model):
    class Action(models.TextChoices):
        UPLOAD = "upload", "Carga de video"
        ZONES_SAVE = "zones_save", "Guardado de zonas"
        RUN_START = "run_start", "Inicio de analisis"
        RUN_CANCEL = "run_cancel", "Cancelacion"
        REPORT_DOWNLOAD = "report_download", "Descarga de reporte"
        EXECUTIVE_EXPORT = "executive_export", "Exportacion ejecutiva"
        NOTE_SAVE = "note_save", "Nota de insight"
        MOVE = "move", "Asignacion"
        RENAME = "rename", "Renombrado"
        UNASSIGN = "unassign", "Desasignacion"
        DELETE = "delete", "Eliminacion"
        MALL_CHANGE = "mall_change", "Cambio de establecimiento"

    analysis = models.ForeignKey(
        AnalysisRun,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    mall = models.ForeignKey(
        Mall,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="analysis_audit_logs",
    )
    action = models.CharField(max_length=40, choices=Action.choices)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        subject = self.analysis.display_name if self.analysis_id else self.mall.name if self.mall_id else "Sistema"
        return f"{self.get_action_display()} / {subject}"
