import csv
import json
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile

from .models import AnalysisRun, Mall


REPORT_FILES = {
    "database": "analysis_results.sqlite3",
    "heatmap": "heatmap_final.png",
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


def ensure_results_database(analysis):
    if analysis is None:
        return
    database_path = report_path(REPORT_FILES["database"], analysis)
    if database_path.exists():
        return
    if not report_path(REPORT_FILES["summary"], analysis).exists() and not report_path(REPORT_FILES["heatmap"], analysis).exists():
        return

    try:
        import vision_utils

        from .analysis_engine import build_results_database

        zones = [
            vision_utils.normalize_zone_geometry(zone.copy(), analysis.frame_width, analysis.frame_height)
            for zone in analysis.zones
        ]
        build_results_database(analysis.output_path, analysis.pk, analysis.video.path, zones)
    except Exception:
        return


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


def analysis_summary_snapshot(analysis):
    ensure_results_database(analysis)
    summary_rows = read_csv_dicts(REPORT_FILES["summary"], analysis)
    summary = summary_rows[0] if summary_rows else {}
    heatmap_path = report_path(REPORT_FILES["heatmap"], analysis)
    return {
        "analysis": analysis,
        "summary": summary,
        "has_heatmap": heatmap_path.exists(),
        "heatmap_url": f"{analysis.report_media_prefix}{REPORT_FILES['heatmap']}" if heatmap_path.exists() else "",
        "total_people": safe_int(summary.get("total_people")),
        "zone_entries": safe_int(summary.get("total_zone_entries")),
        "store_entries": safe_int(summary.get("total_store_entries")),
        "avg_dwell_seconds": safe_float(summary.get("avg_dwell_time_seconds")),
        "avg_dwell_label": summary.get("avg_dwell_time", "-"),
    }


def mall_overview_cards():
    cards = []
    malls = list(Mall.objects.all())
    for mall in malls:
        analyses = list(mall.analyses.order_by("-created_at"))
        completed = [analysis for analysis in analyses if analysis.status == AnalysisRun.Status.COMPLETED]
        snapshots = [analysis_summary_snapshot(analysis) for analysis in completed[:6]]
        latest_snapshot = snapshots[0] if snapshots else None

        total_people = sum(snapshot["total_people"] for snapshot in snapshots)
        total_zone_entries = sum(snapshot["zone_entries"] for snapshot in snapshots)
        total_store_entries = sum(snapshot["store_entries"] for snapshot in snapshots)
        dwell_values = [snapshot["avg_dwell_seconds"] for snapshot in snapshots if snapshot["avg_dwell_seconds"] > 0]
        avg_dwell_seconds = sum(dwell_values) / len(dwell_values) if dwell_values else 0
        hours = int(avg_dwell_seconds) // 3600
        minutes = (int(avg_dwell_seconds) % 3600) // 60
        seconds = int(avg_dwell_seconds) % 60
        avg_dwell_label = f"{hours:02d}:{minutes:02d}:{seconds:02d}" if dwell_values else "-"

        cards.append({
            "mall": mall,
            "analysis_count": len(analyses),
            "completed_count": len(completed),
            "latest_snapshot": latest_snapshot,
            "recent_snapshots": snapshots[:3],
            "total_people": total_people,
            "total_zone_entries": total_zone_entries,
            "total_store_entries": total_store_entries,
            "avg_dwell_label": avg_dwell_label,
        })
    return cards


def dashboard_context(analysis=None):
    if analysis is None:
        mall_cards = mall_overview_cards()
        return {
            "dashboard_mode": "overview",
            "mall_cards": mall_cards,
            "analysis": None,
        }

    if analysis is None:
        analysis = latest_relevant_analysis()

    ensure_results_database(analysis)

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
        "dashboard_mode": "analysis",
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
            {
                "name": label,
                "filename": filename,
                "exists": report_path(filename, analysis).exists(),
                "url": f"{analysis.report_media_prefix}{filename}" if analysis and report_path(filename, analysis).exists() else "",
            }
            for label, filename in REPORT_FILES.items()
        ],
    }
