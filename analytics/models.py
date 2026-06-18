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
    accent_color = models.CharField(max_length=7, default="#32D583")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class AnalysisRun(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        READY = "ready", "Listo"
        RUNNING = "running", "Analizando"
        COMPLETED = "completed", "Completado"
        FAILED = "failed", "Fallido"
        CANCELED = "canceled", "Cancelado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160, blank=True)
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
