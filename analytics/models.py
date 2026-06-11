import uuid
from pathlib import Path

from django.conf import settings
from django.db import models
from django.utils import timezone


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
