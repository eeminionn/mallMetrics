import json
import threading

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from config import ZONE_STYLES

from .analysis_engine import run_analysis_job
from .forms import VideoUploadForm
from .models import AnalysisRun
from .services import dashboard_context, prepare_video_metadata


def normalize_zones(raw_zones, frame_width, frame_height):
    zones = []
    counters = {}
    for raw in raw_zones:
        zone_type = str(raw.get("type", "zona")).strip()
        if zone_type not in ZONE_STYLES:
            zone_type = "zona"

        counters[zone_type] = counters.get(zone_type, 0) + 1
        zone_id = str(raw.get("id") or f"{zone_type}_{counters[zone_type]}")
        name = str(raw.get("name") or "").strip()
        if not name:
            name = f"{ZONE_STYLES[zone_type]['label']} {counters[zone_type]}"

        x1 = int(max(0, min(frame_width - 1, float(raw.get("x1", 0)))))
        y1 = int(max(0, min(frame_height - 1, float(raw.get("y1", 0)))))
        x2 = int(max(0, min(frame_width - 1, float(raw.get("x2", 0)))))
        y2 = int(max(0, min(frame_height - 1, float(raw.get("y2", 0)))))
        x1, x2 = sorted([x1, x2])
        y1, y2 = sorted([y1, y2])
        if abs(x2 - x1) < 10 or abs(y2 - y1) < 10:
            continue

        zones.append({
            "id": zone_id,
            "name": name,
            "type": zone_type,
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
        })
    return zones


@login_required
def dashboard(request):
    return render(request, "analytics/dashboard.html", dashboard_context())


@login_required
def analysis_list(request):
    return render(request, "analytics/analysis_list.html", {"analyses": AnalysisRun.objects.all()})


@login_required
def video_upload(request):
    if request.method == "POST":
        form = VideoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            analysis = form.save(commit=False)
            analysis.created_by = request.user
            analysis.status_message = "Leyendo video"
            analysis.save()
            try:
                prepare_video_metadata(analysis)
            except RuntimeError as error:
                messages.error(request, str(error))
                return redirect("analysis_list")
            return redirect("zone_editor", pk=analysis.pk)
    else:
        form = VideoUploadForm()

    return render(request, "analytics/video_upload.html", {"form": form})


@login_required
def zone_editor(request, pk):
    analysis = get_object_or_404(AnalysisRun, pk=pk)
    if request.method == "POST":
        try:
            raw_zones = json.loads(request.POST.get("zones", "[]"))
        except json.JSONDecodeError:
            messages.error(request, "No se pudieron leer las zonas dibujadas.")
            return redirect("zone_editor", pk=analysis.pk)

        zones = normalize_zones(raw_zones, analysis.frame_width, analysis.frame_height)
        if not zones:
            messages.error(request, "Dibuja al menos una zona valida antes de continuar.")
            return redirect("zone_editor", pk=analysis.pk)

        analysis.zones = zones
        analysis.status = AnalysisRun.Status.READY
        analysis.progress = 0
        analysis.status_message = "Listo para ejecutar analisis"
        analysis.error_message = ""
        analysis.save(update_fields=["zones", "status", "progress", "status_message", "error_message", "updated_at"])
        return redirect("analysis_status", pk=analysis.pk)

    zone_styles = {
        key: {"label": value["label"], "hex": value["hex"]}
        for key, value in ZONE_STYLES.items()
        if key in {"puerta", "frente_tienda", "escalera", "salida", "zona"}
    }
    return render(request, "analytics/zone_editor.html", {
        "analysis": analysis,
        "zone_styles": json.dumps(zone_styles),
        "zones_json": json.dumps(analysis.zones),
    })


@login_required
def analysis_status(request, pk):
    analysis = get_object_or_404(AnalysisRun, pk=pk)
    return render(request, "analytics/analysis_status.html", {"analysis": analysis})


@login_required
def analysis_results(request, pk):
    analysis = get_object_or_404(AnalysisRun, pk=pk)
    return render(request, "analytics/dashboard.html", dashboard_context(analysis))


@login_required
def reports(request, pk=None):
    analysis = get_object_or_404(AnalysisRun, pk=pk) if pk else None
    return render(request, "analytics/reports.html", dashboard_context(analysis))


@login_required
def analysis_progress(request, pk):
    analysis = get_object_or_404(AnalysisRun, pk=pk)
    preview_path = analysis.output_path / "preview_frame.jpg"
    preview_url = ""
    if preview_path.exists():
        preview_url = f"{analysis.report_media_prefix}preview_frame.jpg?v={int(analysis.updated_at.timestamp())}"
    return JsonResponse({
        "id": str(analysis.id),
        "status": analysis.status,
        "progress": analysis.progress,
        "processed_frames": analysis.processed_frames,
        "total_frames": analysis.total_frames,
        "confirmed_people": analysis.confirmed_people,
        "status_message": analysis.status_message,
        "error_message": analysis.error_message,
        "preview_url": preview_url,
        "results_url": reverse("analysis_results", kwargs={"pk": analysis.pk}),
    })


@login_required
@require_POST
def start_analysis(request, pk):
    analysis = get_object_or_404(AnalysisRun, pk=pk)
    if analysis.status == AnalysisRun.Status.RUNNING:
        return redirect("analysis_status", pk=analysis.pk)
    if not analysis.zones:
        messages.error(request, "Configura zonas antes de iniciar el analisis.")
        return redirect("zone_editor", pk=analysis.pk)

    analysis.status = AnalysisRun.Status.RUNNING
    analysis.progress = 0
    analysis.processed_frames = 0
    analysis.confirmed_people = 0
    analysis.status_message = "En cola de ejecucion"
    analysis.error_message = ""
    analysis.started_at = timezone.now()
    analysis.finished_at = None
    analysis.output_dir = str(analysis.output_path)
    analysis.save(update_fields=[
        "status",
        "progress",
        "processed_frames",
        "confirmed_people",
        "status_message",
        "error_message",
        "started_at",
        "finished_at",
        "output_dir",
        "updated_at",
    ])

    thread = threading.Thread(target=run_analysis_job, args=(analysis.pk,), daemon=True)
    thread.start()
    return redirect("analysis_status", pk=analysis.pk)


@login_required
@require_POST
def cancel_analysis(request, pk):
    analysis = get_object_or_404(AnalysisRun, pk=pk)
    if analysis.status == AnalysisRun.Status.RUNNING:
        analysis.status = AnalysisRun.Status.CANCELED
        analysis.status_message = "Cancelacion solicitada"
        analysis.save(update_fields=["status", "status_message", "updated_at"])
    return redirect("analysis_status", pk=analysis.pk)
