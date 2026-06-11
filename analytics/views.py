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
from .forms import MallForm, VideoUploadForm
from .models import AnalysisRun, Mall
from .services import dashboard_context, prepare_video_metadata


def clamp_point(point, frame_width, frame_height):
    return {
        "x": int(max(0, min(frame_width - 1, float(point.get("x", 0))))),
        "y": int(max(0, min(frame_height - 1, float(point.get("y", 0))))),
    }


def rectangle_points(raw, frame_width, frame_height):
    x1 = int(max(0, min(frame_width - 1, float(raw.get("x1", 0)))))
    y1 = int(max(0, min(frame_height - 1, float(raw.get("y1", 0)))))
    x2 = int(max(0, min(frame_width - 1, float(raw.get("x2", 0)))))
    y2 = int(max(0, min(frame_height - 1, float(raw.get("y2", 0)))))
    left, right = sorted([x1, x2])
    top, bottom = sorted([y1, y2])
    return [
        {"x": left, "y": top},
        {"x": right, "y": top},
        {"x": right, "y": bottom},
        {"x": left, "y": bottom},
    ]


def polygon_area(points):
    area = 0
    for index, point in enumerate(points):
        next_point = points[(index + 1) % len(points)]
        area += point["x"] * next_point["y"] - next_point["x"] * point["y"]
    return abs(area) / 2


def zone_bounds(points):
    xs = [point["x"] for point in points]
    ys = [point["y"] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


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

        raw_points = raw.get("points")
        if isinstance(raw_points, list) and len(raw_points) >= 4:
            points = [clamp_point(point, frame_width, frame_height) for point in raw_points[:4]]
        else:
            points = rectangle_points(raw, frame_width, frame_height)

        x1, y1, x2, y2 = zone_bounds(points)
        if abs(x2 - x1) < 10 or abs(y2 - y1) < 10:
            continue
        if polygon_area(points) < 80:
            continue

        zones.append({
            "id": zone_id,
            "name": name,
            "type": zone_type,
            "points": points,
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
        })
    return zones


def resolve_mall_group(name):
    normalized = str(name or "").strip()
    if not normalized:
        return None
    mall_group, _ = Mall.objects.get_or_create(name=normalized)
    return mall_group


def board_columns(analyses):
    columns = []
    all_malls = list(Mall.objects.all())
    analyses_by_mall = {mall.id: [] for mall in all_malls}
    unassigned = []

    for analysis in analyses:
        if analysis.mall_group_id and analysis.mall_group_id in analyses_by_mall:
            analyses_by_mall[analysis.mall_group_id].append(analysis)
        else:
            unassigned.append(analysis)

    for mall in all_malls:
        columns.append({
            "id": str(mall.id),
            "name": mall.name,
            "count": len(analyses_by_mall[mall.id]),
            "items": analyses_by_mall[mall.id],
        })

    columns.append({
        "id": "",
        "name": "Sin mall asignado",
        "count": len(unassigned),
        "items": unassigned,
    })
    return columns


@login_required
def dashboard(request):
    return render(request, "analytics/dashboard.html", dashboard_context())


@login_required
def analysis_list(request):
    analyses = AnalysisRun.objects.all()
    selected_category = request.GET.get("category", "").strip()
    if selected_category:
        analyses = analyses.filter(category=selected_category)

    category_options = AnalysisRun.objects.exclude(category="").order_by("category").values_list("category", flat=True).distinct()
    return render(request, "analytics/analysis_list.html", {
        "analyses": analyses,
        "board_columns": board_columns(analyses),
        "category_options": category_options,
        "selected_category": selected_category,
        "mall_form": MallForm(),
    })


@login_required
def video_upload(request):
    if request.method == "POST":
        form = VideoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            analysis = form.save(commit=False)
            analysis.created_by = request.user
            analysis.mall_group = resolve_mall_group(form.cleaned_data.get("mall"))
            analysis.mall = analysis.mall_group.name if analysis.mall_group else ""
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

    return render(request, "analytics/video_upload.html", {
        "form": form,
        "mall_options": Mall.objects.values_list("name", flat=True),
    })


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
    processed_seconds = int(analysis.processed_frames / analysis.fps) if analysis.fps else 0
    total_seconds = int(analysis.total_frames / analysis.fps) if analysis.fps else 0
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
        "processed_time": format_hms(processed_seconds),
        "duration_time": format_hms(total_seconds),
        "results_url": reverse("analysis_results", kwargs={"pk": analysis.pk}),
    })


def format_hms(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    remaining = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{remaining:02d}"


@login_required
@require_POST
def create_mall(request):
    form = MallForm(request.POST)
    if form.is_valid():
        mall_group, created = Mall.objects.get_or_create(name=form.cleaned_data["name"].strip())
        if created:
            messages.success(request, f"Mall creado: {mall_group.name}")
        else:
            messages.error(request, f"El mall {mall_group.name} ya existe.")
    else:
        messages.error(request, "No se pudo crear el mall.")
    return redirect("analysis_list")


@login_required
@require_POST
def move_analysis_to_mall(request, pk):
    analysis = get_object_or_404(AnalysisRun, pk=pk)
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "JSON invalido."}, status=400)

    mall_id = str(payload.get("mall_id", "")).strip()
    mall_group = None
    if mall_id:
        mall_group = get_object_or_404(Mall, pk=mall_id)

    analysis.mall_group = mall_group
    analysis.mall = mall_group.name if mall_group else ""
    analysis.save(update_fields=["mall_group", "mall", "updated_at"])
    return JsonResponse({
        "ok": True,
        "analysis_id": str(analysis.pk),
        "mall_id": str(mall_group.pk) if mall_group else "",
        "mall_name": mall_group.name if mall_group else "",
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


@login_required
@require_POST
def delete_analysis(request, pk):
    analysis = get_object_or_404(AnalysisRun, pk=pk)
    if analysis.status == AnalysisRun.Status.RUNNING:
        messages.error(request, "Cancela el analisis antes de eliminar el estudio.")
        return redirect("analysis_list")

    name = analysis.display_name
    analysis.delete_artifacts()
    analysis.delete()
    messages.success(request, f"Estudio eliminado: {name}")
    return redirect("analysis_list")
