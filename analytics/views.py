import json
import re
import threading

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, JsonResponse
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from config import ZONE_STYLES

from .analysis_engine import run_analysis_job
from .forms import MallForm, VideoUploadForm
from .models import AnalysisAuditLog, AnalysisRun, InsightNote, Mall, ZoneVersion
from .services import (
    build_analysis_zip_bytes,
    build_executive_pdf_bytes,
    build_executive_pptx_bytes,
    build_mall_zip_bytes,
    build_mall_executive_pdf_bytes,
    build_mall_executive_pptx_bytes,
    dashboard_context,
    prepare_video_metadata,
    reports_context,
    slug_token,
)


def audit_event(request, action, analysis=None, mall=None, **metadata):
    AnalysisAuditLog.objects.create(
        action=action,
        analysis=analysis,
        mall=mall,
        actor=request.user if getattr(request, "user", None) and request.user.is_authenticated else None,
        metadata={key: value for key, value in metadata.items() if value not in (None, "")},
    )


def user_role_label(user):
    if not user or not user.is_authenticated:
        return "Invitado"
    if user.is_superuser:
        return "Administrador"
    group = user.groups.order_by("name").first()
    if group:
        return group.name
    return "Analista"


def filtered_analyses_from_request(request, base=None):
    analyses = (base if base is not None else AnalysisRun.objects.select_related("mall_group")).all()
    filters = {
        "mall": request.GET.get("mall", "").strip(),
        "category": request.GET.get("category", "").strip(),
        "area": request.GET.get("area", "").strip(),
        "zone": request.GET.get("zone", "").strip(),
        "status": request.GET.get("status", "").strip(),
        "date_from": request.GET.get("date_from", "").strip(),
        "date_to": request.GET.get("date_to", "").strip(),
    }
    if filters["mall"]:
        analyses = analyses.filter(mall_group__name=filters["mall"])
    if filters["category"]:
        analyses = analyses.filter(category=filters["category"])
    if filters["area"]:
        analyses = analyses.filter(area=filters["area"])
    if filters["zone"]:
        zone_query = filters["zone"].casefold()
        matching_ids = []
        for analysis in analyses.only("id", "zones"):
            zone_blob = " ".join(
                " ".join(str(zone.get(key, "")) for key in ("id", "name", "type"))
                for zone in (analysis.zones or [])
                if isinstance(zone, dict)
            ).casefold()
            if zone_query in zone_blob:
                matching_ids.append(analysis.pk)
        analyses = analyses.filter(pk__in=matching_ids)
    if filters["status"]:
        analyses = analyses.filter(status=filters["status"])
    if filters["date_from"]:
        analyses = analyses.filter(created_at__date__gte=filters["date_from"])
    if filters["date_to"]:
        analyses = analyses.filter(created_at__date__lte=filters["date_to"])
    return analyses, filters


def filter_options_context():
    zone_options = set()
    for zones in AnalysisRun.objects.values_list("zones", flat=True):
        for zone in zones or []:
            if isinstance(zone, dict):
                label = (zone.get("name") or zone.get("id") or zone.get("type") or "").strip()
                if label:
                    zone_options.add(label)
    return {
        "mall_options": Mall.objects.values_list("name", flat=True),
        "category_options": AnalysisRun.objects.exclude(category="").order_by("category").values_list("category", flat=True).distinct(),
        "area_options": AnalysisRun.objects.exclude(area="").order_by("area").values_list("area", flat=True).distinct(),
        "zone_options": sorted(zone_options),
        "status_options": AnalysisRun.Status.choices,
    }


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


def normalize_zone_type(raw_type):
    zone_type = re.sub(r"[^0-9a-zA-Z_]+", "_", str(raw_type or "zona").strip().lower()).strip("_")
    return zone_type or "zona"


def zone_type_label(zone_type):
    if zone_type in ZONE_STYLES:
        return ZONE_STYLES[zone_type]["label"]
    return zone_type.replace("_", " ").upper()


def normalize_zones(raw_zones, frame_width, frame_height):
    zones = []
    counters = {}
    for raw in raw_zones:
        zone_type = normalize_zone_type(raw.get("type", "zona"))

        counters[zone_type] = counters.get(zone_type, 0) + 1
        zone_id = str(raw.get("id") or f"{zone_type}_{counters[zone_type]}")
        type_label = str(raw.get("type_label") or zone_type_label(zone_type)).strip().upper()
        name = str(raw.get("name") or "").strip()
        if not name:
            name = f"{type_label} {counters[zone_type]}"

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
            "type_label": type_label,
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
    all_establecimientos = list(Mall.objects.all())
    analyses_by_mall = {establecimiento.id: [] for establecimiento in all_establecimientos}

    for analysis in analyses:
        if analysis.mall_group_id and analysis.mall_group_id in analyses_by_mall:
            analyses_by_mall[analysis.mall_group_id].append(analysis)

    for establecimiento in sorted(all_establecimientos, key=lambda mall: len(analyses_by_mall[mall.id]), reverse=True):
        columns.append({
            "id": str(establecimiento.id),
            "name": establecimiento.name,
            "accent_color": establecimiento.accent_color,
            "notes": establecimiento.notes,
            "count": len(analyses_by_mall[establecimiento.id]),
            "items": analyses_by_mall[establecimiento.id],
        })

    return columns


@login_required
def dashboard(request):
    analyses, selected_filters = filtered_analyses_from_request(request)
    context = dashboard_context(overview_analyses=analyses)
    context.update(filter_options_context())
    context.update({
        "selected_filters": selected_filters,
        "user_role": user_role_label(request.user),
        "clear_url": reverse("dashboard"),
    })
    return render(request, "analytics/dashboard.html", context)


@login_required
def mall_board(request):
    analyses, selected_filters = filtered_analyses_from_request(request)
    options = filter_options_context()
    return render(request, "analytics/analysis_list.html", {
        "analyses": analyses,
        "board_columns": board_columns(analyses),
        "available_analyses": analyses.filter(mall_group__isnull=True).order_by("-created_at"),
        "selected_filters": selected_filters,
        "mall_form": MallForm(initial={"accent_color": "#2563EB"}),
        "clear_url": reverse("mall_board"),
        **options,
    })


@login_required
def analysis_list(request):
    analyses, selected_filters = filtered_analyses_from_request(request)

    return render(request, "analytics/analysis_runs.html", {
        "analyses": analyses,
        "selected_filters": selected_filters,
        "clear_url": reverse("analysis_list"),
        **filter_options_context(),
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
            audit_event(request, AnalysisAuditLog.Action.UPLOAD, analysis=analysis, mall=analysis.mall_group, video_name=analysis.video.name)
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
        next_version = (analysis.zone_versions.order_by("-version").values_list("version", flat=True).first() or 0) + 1
        ZoneVersion.objects.create(
            analysis=analysis,
            version=next_version,
            zones=zones,
            note="Guardado desde editor de zonas",
            created_by=request.user,
        )
        audit_event(request, AnalysisAuditLog.Action.ZONES_SAVE, analysis=analysis, mall=analysis.mall_group, zones=len(zones), version=next_version)
        return redirect("analysis_status", pk=analysis.pk)

    zone_styles = {
        key: {"label": value["label"], "hex": value["hex"]}
        for key, value in ZONE_STYLES.items()
        if key in {"zona"}
    }
    for zone in analysis.zones or []:
        zone_type = normalize_zone_type(zone.get("type", "zona"))
        if zone_type not in zone_styles:
            zone_styles[zone_type] = {
                "label": str(zone.get("type_label") or zone_type_label(zone_type)).upper(),
                "hex": zone.get("hex") or "#60A5FA",
            }
    return render(request, "analytics/zone_editor.html", {
        "analysis": analysis,
        "zone_styles": json.dumps(zone_styles),
        "zones_json": json.dumps(analysis.zones),
        "frame_url": analysis.first_frame.url if analysis.first_frame else "",
    })


@login_required
def analysis_status(request, pk):
    analysis = get_object_or_404(AnalysisRun, pk=pk)
    return render(request, "analytics/analysis_status.html", {"analysis": analysis})


@login_required
def analysis_results(request, pk):
    analysis = get_object_or_404(AnalysisRun, pk=pk)
    context = dashboard_context(analysis)
    context.update({
        "user_role": user_role_label(request.user),
    })
    return render(request, "analytics/dashboard.html", context)


@login_required
def analysis_presentation(request, pk):
    analysis = get_object_or_404(AnalysisRun, pk=pk)
    return render(request, "analytics/presentation.html", dashboard_context(analysis))


@login_required
@require_POST
def save_insight_note(request, pk):
    analysis = get_object_or_404(AnalysisRun, pk=pk)
    insight_key = request.POST.get("insight_key", "").strip()
    body = request.POST.get("body", "").strip()
    if not insight_key:
        messages.error(request, "No se pudo identificar el insight.")
        return redirect("analysis_results", pk=analysis.pk)

    InsightNote.objects.update_or_create(
        analysis=analysis,
        insight_key=insight_key,
        defaults={"body": body, "created_by": request.user},
    )
    audit_event(request, AnalysisAuditLog.Action.NOTE_SAVE, analysis=analysis, mall=analysis.mall_group, insight_key=insight_key)
    messages.success(request, "Nota guardada junto al insight.")
    return redirect("analysis_results", pk=analysis.pk)


@login_required
@require_POST
def restore_zone_version(request, pk, version_id):
    analysis = get_object_or_404(AnalysisRun, pk=pk)
    version = get_object_or_404(ZoneVersion, pk=version_id, analysis=analysis)
    analysis.zones = version.zones
    analysis.status = AnalysisRun.Status.READY
    analysis.status_message = "Version de zonas restaurada; vuelve a ejecutar para recalcular resultados"
    analysis.save(update_fields=["zones", "status", "status_message", "updated_at"])
    next_version = (analysis.zone_versions.order_by("-version").values_list("version", flat=True).first() or 0) + 1
    ZoneVersion.objects.create(
        analysis=analysis,
        version=next_version,
        zones=version.zones,
        note=f"Restaurada desde v{version.version}",
        created_by=request.user,
    )
    audit_event(request, AnalysisAuditLog.Action.ZONES_SAVE, analysis=analysis, mall=analysis.mall_group, restored_from=version.version, version=next_version)
    messages.success(request, f"Zonas restauradas desde version {version.version}.")
    return redirect("zone_editor", pk=analysis.pk)


@login_required
def reports(request, pk=None):
    analysis = get_object_or_404(AnalysisRun, pk=pk) if pk else None
    return render(request, "analytics/reports.html", reports_context(analysis))


@login_required
def download_analysis_report(request, pk):
    analysis = get_object_or_404(AnalysisRun, pk=pk)
    bundle = build_analysis_zip_bytes(analysis)
    filename = f"pipolmetrics-analysis-{slug_token(analysis.display_name, 'analysis')}.zip"
    audit_event(request, AnalysisAuditLog.Action.REPORT_DOWNLOAD, analysis=analysis, mall=analysis.mall_group, format="zip")
    return FileResponse(bundle, as_attachment=True, filename=filename, content_type="application/zip")


@login_required
def download_mall_report(request, pk):
    mall = get_object_or_404(Mall, pk=pk)
    bundle = build_mall_zip_bytes(mall)
    filename = f"pipolmetrics-establecimiento-{slug_token(mall.name, 'establecimiento')}.zip"
    audit_event(request, AnalysisAuditLog.Action.REPORT_DOWNLOAD, mall=mall, format="zip", scope="establecimiento")
    return FileResponse(bundle, as_attachment=True, filename=filename, content_type="application/zip")


@login_required
def download_mall_executive_pdf(request, pk):
    mall = get_object_or_404(Mall, pk=pk)
    bundle = build_mall_executive_pdf_bytes(mall)
    filename = f"pipolmetrics-ejecutivo-establecimiento-{slug_token(mall.name, 'establecimiento')}.pdf"
    audit_event(request, AnalysisAuditLog.Action.EXECUTIVE_EXPORT, mall=mall, format="pdf", scope="establecimiento")
    return FileResponse(bundle, as_attachment=True, filename=filename, content_type="application/pdf")


@login_required
def download_mall_executive_pptx(request, pk):
    mall = get_object_or_404(Mall, pk=pk)
    bundle = build_mall_executive_pptx_bytes(mall)
    filename = f"pipolmetrics-ejecutivo-establecimiento-{slug_token(mall.name, 'establecimiento')}.pptx"
    audit_event(request, AnalysisAuditLog.Action.EXECUTIVE_EXPORT, mall=mall, format="pptx", scope="establecimiento")
    return FileResponse(bundle, as_attachment=True, filename=filename, content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")


@login_required
def download_executive_pdf(request, pk):
    analysis = get_object_or_404(AnalysisRun, pk=pk)
    bundle = build_executive_pdf_bytes(analysis)
    filename = f"pipolmetrics-ejecutivo-{slug_token(analysis.display_name, 'analysis')}.pdf"
    audit_event(request, AnalysisAuditLog.Action.EXECUTIVE_EXPORT, analysis=analysis, mall=analysis.mall_group, format="pdf")
    return FileResponse(bundle, as_attachment=True, filename=filename, content_type="application/pdf")


@login_required
def download_executive_pptx(request, pk):
    analysis = get_object_or_404(AnalysisRun, pk=pk)
    bundle = build_executive_pptx_bytes(analysis)
    filename = f"pipolmetrics-ejecutivo-{slug_token(analysis.display_name, 'analysis')}.pptx"
    audit_event(request, AnalysisAuditLog.Action.EXECUTIVE_EXPORT, analysis=analysis, mall=analysis.mall_group, format="pptx")
    return FileResponse(bundle, as_attachment=True, filename=filename, content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")


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
            mall_group.accent_color = form.cleaned_data["accent_color"]
            mall_group.notes = form.cleaned_data["notes"]
            mall_group.save(update_fields=["accent_color", "notes", "updated_at"])
            audit_event(request, AnalysisAuditLog.Action.MALL_CHANGE, mall=mall_group, operation="create")
        if created:
            messages.success(request, f"Establecimiento creado: {mall_group.name}")
        else:
            messages.error(request, f"El establecimiento {mall_group.name} ya existe.")
    else:
        messages.error(request, "No se pudo crear el establecimiento.")
    return redirect("mall_board")


@login_required
def mall_detail(request, pk):
    mall = get_object_or_404(Mall, pk=pk)
    if request.method == "POST":
        form = MallForm(request.POST, instance=mall)
        if form.is_valid():
            form.save()
            Mall.objects.filter(pk=mall.pk).update(updated_at=timezone.now())
            AnalysisRun.objects.filter(mall_group=mall).update(mall=mall.name)
            audit_event(request, AnalysisAuditLog.Action.MALL_CHANGE, mall=mall, operation="update")
            messages.success(request, f"Establecimiento actualizado: {mall.name}")
            return redirect("mall_board")
    else:
        form = MallForm(instance=mall)

    analyses = mall.analyses.all()
    return render(request, "analytics/mall_detail.html", {
        "mall": mall,
        "form": form,
        "analyses": analyses,
    })


@login_required
@require_POST
def move_analysis_to_mall(request, pk):
    analysis = get_object_or_404(AnalysisRun, pk=pk)
    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"ok": False, "error": "JSON invalido."}, status=400)
    else:
        payload = request.POST

    mall_id = str(payload.get("mall_id", "")).strip()
    mall_group = None
    if mall_id:
        mall_group = get_object_or_404(Mall, pk=mall_id)

    analysis.mall_group = mall_group
    analysis.mall = mall_group.name if mall_group else ""
    analysis.save(update_fields=["mall_group", "mall", "updated_at"])
    audit_event(request, AnalysisAuditLog.Action.MOVE, analysis=analysis, mall=mall_group, target_mall=mall_group.name if mall_group else "")
    response = JsonResponse({
        "ok": True,
        "analysis_id": str(analysis.pk),
        "mall_id": str(mall_group.pk) if mall_group else "",
        "mall_name": mall_group.name if mall_group else "",
    })
    if request.content_type == "application/json":
        return response
    messages.success(request, f"Analisis asignado a {mall_group.name if mall_group else 'sin establecimiento'}: {analysis.display_name}")
    return redirect(request.POST.get("next") or "mall_board")


@login_required
@require_POST
def rename_analysis(request, pk):
    analysis = get_object_or_404(AnalysisRun, pk=pk)
    next_name = request.POST.get("name", "").strip()
    if not next_name:
        messages.error(request, "El nombre del analisis no puede estar vacio.")
        return redirect(request.POST.get("next") or "mall_board")

    analysis.name = next_name
    analysis.save(update_fields=["name", "updated_at"])
    audit_event(request, AnalysisAuditLog.Action.RENAME, analysis=analysis, mall=analysis.mall_group, name=next_name)
    messages.success(request, f"Analisis actualizado: {analysis.display_name}")
    return redirect(request.POST.get("next") or "mall_board")


@login_required
@require_POST
def unassign_analysis(request, pk):
    analysis = get_object_or_404(AnalysisRun, pk=pk)
    analysis.mall_group = None
    analysis.mall = ""
    analysis.save(update_fields=["mall_group", "mall", "updated_at"])
    audit_event(request, AnalysisAuditLog.Action.UNASSIGN, analysis=analysis)
    messages.success(request, f"Analisis desasignado: {analysis.display_name}")
    return redirect(request.POST.get("next") or "mall_board")


@login_required
@require_POST
def delete_mall(request, pk):
    establecimiento = get_object_or_404(Mall, pk=pk)
    linked_analyses = AnalysisRun.objects.filter(mall_group=establecimiento)
    linked_analyses.update(mall_group=None, mall="", updated_at=timezone.now())
    mall_name = establecimiento.name
    audit_event(request, AnalysisAuditLog.Action.MALL_CHANGE, mall=establecimiento, operation="delete", linked_analyses=linked_analyses.count())
    establecimiento.delete()
    messages.success(request, f"Establecimiento eliminado: {mall_name}. Sus analisis quedaron sin establecimiento asignado.")
    return redirect("mall_board")


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
    audit_event(request, AnalysisAuditLog.Action.RUN_START, analysis=analysis, mall=analysis.mall_group)

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
        audit_event(request, AnalysisAuditLog.Action.RUN_CANCEL, analysis=analysis, mall=analysis.mall_group)
    return redirect("analysis_status", pk=analysis.pk)


@login_required
@require_POST
def delete_analysis(request, pk):
    analysis = get_object_or_404(AnalysisRun, pk=pk)
    if analysis.status == AnalysisRun.Status.RUNNING:
        messages.error(request, "Cancela el analisis antes de eliminar el analisis.")
        return redirect("analysis_list")

    name = analysis.display_name
    audit_event(request, AnalysisAuditLog.Action.DELETE, analysis=analysis, mall=analysis.mall_group, name=name)
    analysis.delete_artifacts()
    analysis.delete()
    messages.success(request, f"Analisis eliminado: {name}")
    return redirect("analysis_list")
