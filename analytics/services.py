import csv
import json
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile

from .models import AnalysisRun


REPORT_FILES = {
    "summary": "analytics_summary.csv",
    "zones": "reporte_zonas.csv",
    "zone_metrics": "zone_metrics.csv",
    "stores": "store_metrics.csv",
    "time_bins": "time_bins.csv",
    "stairs": "stair_metrics.csv",
    "events": "zone_events.csv",
    "people": "person_tracks.csv",
    "dwell": "dwell_times.csv",
}


def report_path(filename, analysis=None):
    if analysis is not None and analysis.output_dir:
        return Path(analysis.output_dir) / filename
    if analysis is not None:
        return analysis.output_path / filename
    return Path(settings.MALLMETRICS_REPORT_DIR) / filename


def read_csv_dicts(filename, analysis=None):
    path = report_path(filename, analysis)
    if not path.exists():
        return []

    for encoding in ("utf-8", "latin-1"):
        try:
            with path.open("r", encoding=encoding, newline="") as file:
                return list(csv.DictReader(file))
        except UnicodeDecodeError:
            continue
    return []


def safe_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def format_number(value):
    number = safe_float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.1f}"


def prepare_video_metadata(analysis):
    try:
        import cv2
    except ImportError as error:
        analysis.status = AnalysisRun.Status.FAILED
        analysis.error_message = "Falta instalar opencv-python para leer el primer frame del video."
        analysis.status_message = "Dependencia faltante"
        analysis.save(update_fields=["status", "error_message", "status_message", "updated_at"])
        raise RuntimeError(analysis.error_message) from error

    video_path = Path(analysis.video.path)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        analysis.status = AnalysisRun.Status.FAILED
        analysis.error_message = "No se pudo abrir el video cargado."
        analysis.status_message = "Video no legible"
        analysis.save(update_fields=["status", "error_message", "status_message", "updated_at"])
        raise RuntimeError(analysis.error_message)

    ok, frame = cap.read()
    if not ok:
        cap.release()
        analysis.status = AnalysisRun.Status.FAILED
        analysis.error_message = "No se pudo leer el primer frame del video."
        analysis.status_message = "Video sin frames"
        analysis.save(update_fields=["status", "error_message", "status_message", "updated_at"])
        raise RuntimeError(analysis.error_message)

    frame_height, frame_width = frame.shape[:2]
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()

    success, encoded = cv2.imencode(".jpg", frame)
    if success:
        analysis.first_frame.save(
            f"{analysis.id}-frame.jpg",
            ContentFile(encoded.tobytes()),
            save=False,
        )

    analysis.frame_width = frame_width
    analysis.frame_height = frame_height
    analysis.fps = float(fps)
    analysis.total_frames = total_frames
    analysis.status = AnalysisRun.Status.DRAFT
    analysis.status_message = "Define zonas para iniciar el analisis"
    analysis.save(update_fields=[
        "first_frame",
        "frame_width",
        "frame_height",
        "fps",
        "total_frames",
        "status",
        "status_message",
        "updated_at",
    ])


def build_summary(zone_rows):
    total_zone_entries = sum(safe_int(row.get("entry_count")) for row in zone_rows)
    total_store_entries = sum(
        safe_int(row.get("entry_count"))
        for row in zone_rows
        if str(row.get("zone_type", "")).lower() == "puerta"
    )
    return {
        "total_people": "-",
        "total_zone_entries": str(total_zone_entries),
        "total_store_entries": str(total_store_entries),
        "avg_dwell_time": "-",
        "flow_heatmap_points": "0",
    }


def ranking_rows(store_rows, zone_metric_rows, zone_rows):
    rows = []
    for row in store_rows:
        value = safe_int(row.get("exterior_traffic")) or safe_int(row.get("door_crossings"))
        value = value or safe_int(row.get("estimated_entries"))
        rows.append({"label": row.get("store_name") or "Tienda", "value": value})

    if not rows:
        source = zone_metric_rows or zone_rows
        for row in source:
            rows.append({
                "label": row.get("zone_name") or row.get("zone_id") or "Zona",
                "value": safe_int(row.get("entry_count")),
            })

    return sorted(rows, key=lambda row: row["value"], reverse=True)[:8]


def store_flow_rows(store_rows, zone_metric_rows, zone_rows):
    rows = []
    for row in store_rows:
        value = safe_int(row.get("exterior_traffic")) or safe_int(row.get("door_crossings"))
        value = value or safe_int(row.get("estimated_entries"))
        if value > 0:
            rows.append({"label": row.get("store_name") or "Tienda", "value": value})

    if not rows:
        source = zone_metric_rows or zone_rows
        for row in source:
            if str(row.get("zone_type", "")).lower() in {"frente_tienda", "puerta"}:
                value = safe_int(row.get("entry_count"))
                if value > 0:
                    rows.append({"label": row.get("zone_name") or row.get("zone_id") or "Tienda", "value": value})

    return sorted(rows, key=lambda row: row["value"], reverse=True)[:8]


def time_series_rows(time_rows):
    rows = []
    for row in time_rows:
        rows.append({
            "label": row.get("time_label") or row.get("interval") or row.get("time_bin") or "",
            "visible": safe_int(row.get("visible_people_max", row.get("people_count", 0))),
            "events": safe_int(row.get("total_events")),
            "entries": safe_int(row.get("store_entries")),
            "exits": safe_int(row.get("store_exits")),
        })
    return rows


def stair_rows_for_chart(stair_rows):
    return [
        {
            "label": row.get("stair_name") or row.get("zone_name") or row.get("stair_id") or "Escalera",
            "up": safe_int(row.get("up_count", row.get("subidas", 0))),
            "down": safe_int(row.get("down_count", row.get("bajadas", 0))),
        }
        for row in stair_rows
    ]


def latest_relevant_analysis():
    completed = AnalysisRun.objects.filter(status=AnalysisRun.Status.COMPLETED).first()
    if completed:
        return completed
    return AnalysisRun.objects.first()


def dashboard_context(analysis=None):
    if analysis is None:
        analysis = latest_relevant_analysis()

    zone_rows = read_csv_dicts(REPORT_FILES["zones"], analysis)
    zone_metric_rows = read_csv_dicts(REPORT_FILES["zone_metrics"], analysis)
    store_rows = read_csv_dicts(REPORT_FILES["stores"], analysis)
    time_rows = read_csv_dicts(REPORT_FILES["time_bins"], analysis)
    stair_rows = read_csv_dicts(REPORT_FILES["stairs"], analysis)
    summary_rows = read_csv_dicts(REPORT_FILES["summary"], analysis)
    event_rows = read_csv_dicts(REPORT_FILES["events"], analysis)
    people_rows = read_csv_dicts(REPORT_FILES["people"], analysis)

    summary = summary_rows[0] if summary_rows else build_summary(zone_rows)
    heatmap_path = report_path("heatmap_final.png", analysis) if analysis else report_path("heatmap_final.png")

    chart_payload = {
        "ranking": ranking_rows(store_rows, zone_metric_rows, zone_rows),
        "storeFlow": store_flow_rows(store_rows, zone_metric_rows, zone_rows),
        "time": time_series_rows(time_rows),
        "stairs": stair_rows_for_chart(stair_rows),
    }

    return {
        "analysis": analysis,
        "analyses": AnalysisRun.objects.all()[:12],
        "summary": summary,
        "ranking_rows": chart_payload["ranking"],
        "store_flow_rows": chart_payload["storeFlow"],
        "time_chart_rows": chart_payload["time"],
        "stair_chart_rows": chart_payload["stairs"],
        "zone_rows": zone_metric_rows or zone_rows,
        "store_rows": store_rows,
        "time_rows": time_rows,
        "stair_rows": stair_rows,
        "event_rows": event_rows[:80],
        "people_rows": people_rows[:80],
        "has_heatmap": heatmap_path.exists(),
        "heatmap_url": f"{analysis.report_media_prefix}heatmap_final.png" if analysis else settings.MEDIA_URL + "reports/heatmap_final.png",
        "chart_payload": json.dumps(chart_payload),
        "report_files": [
            {"name": label, "filename": filename, "exists": report_path(filename, analysis).exists()}
            for label, filename in REPORT_FILES.items()
        ],
    }
