import base64
import csv
import io
import json
import re
import urllib.error
import urllib.request
import zipfile
from datetime import timedelta
from pathlib import Path
from xml.sax.saxutils import escape

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone

from .models import AnalysisAuditLog, AnalysisRun, InsightNote, Mall


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

REPORT_LABELS = {
    "database": "Base de datos",
    "heatmap": "Mapa de calor",
    "summary": "Resumen",
    "zones": "Zonas configuradas",
    "zone_metrics": "Metricas por zona",
    "stores": "Actividad focal",
    "time_bins": "Serie temporal",
    "stairs": "Direccionalidad",
    "events": "Eventos",
    "people": "Tracks de personas",
    "dwell": "Permanencia",
}

METRIC_DICTIONARY = [
    {
        "key": "personas_validadas",
        "name": "Personas validadas",
        "formula": "Tracks persistentes confirmados por el motor de deteccion.",
        "source": "analytics_summary.csv / person_tracks.csv",
        "confidence": "Alta si el video tiene buena resolucion y personas completas.",
    },
    {
        "key": "entradas_zona",
        "name": "Entradas a zonas",
        "formula": "Cruces de centroides hacia poligonos con permanencia minima.",
        "source": "zone_metrics.csv / zone_events.csv",
        "confidence": "Media-alta; depende de calidad del poligono y angulo de camara.",
    },
    {
        "key": "permanencia",
        "name": "Permanencia promedio",
        "formula": "Promedio de tiempo observado dentro de zonas o trayectorias.",
        "source": "zone_metrics.csv / dwell_times.csv",
        "confidence": "Media; mejora con FPS estable y baja oclusion.",
    },
    {
        "key": "indice_friccion",
        "name": "Indice de friccion",
        "formula": "Entradas, permanencia y personas unicas combinadas para detectar cuellos de botella.",
        "source": "zone_metrics.csv",
        "confidence": "Indicador comparativo, no conteo absoluto.",
    },
    {
        "key": "calidad_video",
        "name": "Calidad del video",
        "formula": "Resolucion, FPS, duracion, zonas configuradas y avance de procesamiento.",
        "source": "Metadatos de AnalysisRun",
        "confidence": "Diagnostico tecnico para interpretar confiabilidad.",
    },
]


def slug_token(value, fallback="item"):
    text = re.sub(r"[^0-9a-zA-Z]+", "-", str(value or "").strip()).strip("-").lower()
    return text or fallback


def report_path(filename, analysis=None):
    if analysis is not None and analysis.output_dir:
        return Path(analysis.output_dir) / filename
    if analysis is not None:
        return analysis.output_path / filename
    return Path(getattr(settings, "PEOPLEMETRICS_REPORT_DIR", settings.BASE_DIR)) / filename


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


def format_hms(seconds):
    seconds = max(0, int(safe_float(seconds)))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    remaining = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{remaining:02d}"


def analysis_base_time(analysis):
    if not analysis:
        return None
    return analysis.started_at or analysis.created_at


def analysis_clock_label(analysis, seconds):
    base_time = analysis_base_time(analysis)
    if not base_time:
        return format_hms(seconds)
    start = timezone.localtime(base_time)
    return (start + timedelta(seconds=safe_float(seconds))).strftime("%H:%M:%S")


def compact_clock_label(analysis, seconds):
    base_time = analysis_base_time(analysis)
    if not base_time:
        total_seconds = int(safe_float(seconds))
        return f"{total_seconds // 3600:02d}:{(total_seconds % 3600) // 60:02d}"
    start = timezone.localtime(base_time)
    return (start + timedelta(seconds=safe_float(seconds))).strftime("%H:%M")


def compact_clock_range(analysis, start_seconds, end_seconds):
    start_label = compact_clock_label(analysis, start_seconds)
    end_label = compact_clock_label(analysis, end_seconds)
    return start_label if start_label == end_label else f"{start_label} - {end_label}"


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
    return {
        "total_people": "-",
        "total_zone_entries": str(total_zone_entries),
        "total_focus_activity": str(total_zone_entries),
        "avg_dwell_time": "-",
        "flow_heatmap_points": "0",
    }


def ranking_rows(store_rows, zone_metric_rows, zone_rows):
    rows = []
    source = zone_metric_rows or zone_rows
    for row in source:
        value = safe_int(row.get("entry_count")) or safe_int(row.get("unique_people_count"))
        if value > 0:
            rows.append({
                "label": row.get("zone_name") or row.get("zone_id") or "Zona",
                "value": value,
            })
    if not rows:
        for row in store_rows:
            value = safe_int(row.get("exterior_traffic")) or safe_int(row.get("door_crossings"))
            value = value or safe_int(row.get("estimated_entries"))
            rows.append({"label": row.get("store_name") or "Zona", "value": value})

    return sorted(rows, key=lambda row: row["value"], reverse=True)[:8]


def zone_activity_rows(store_rows, zone_metric_rows, zone_rows):
    rows = []
    source = zone_metric_rows or zone_rows
    for row in source:
        value = safe_int(row.get("entry_count")) or safe_int(row.get("unique_people_count"))
        if value > 0:
            rows.append({"label": row.get("zone_name") or row.get("zone_id") or "Zona", "value": value})
    if not rows:
        for row in store_rows:
            value = safe_int(row.get("exterior_traffic")) or safe_int(row.get("door_crossings"))
            value = value or safe_int(row.get("estimated_entries"))
            if value > 0:
                rows.append({"label": row.get("store_name") or "Zona", "value": value})
    return sorted(rows, key=lambda row: row["value"], reverse=True)[:8]


def spatial_zone_rows(zone_rows, zone_metric_rows):
    metric_by_id = {
        str(row.get("zone_id", "")): row
        for row in zone_metric_rows
    }
    rows = []
    for index, row in enumerate(zone_rows):
        zone_id = str(row.get("zone_id") or row.get("id") or f"zona_{index + 1}")
        metrics = metric_by_id.get(zone_id, row)
        x1 = safe_float(row.get("x1"))
        y1 = safe_float(row.get("y1"))
        x2 = safe_float(row.get("x2"))
        y2 = safe_float(row.get("y2"))
        rows.append({
            "label": row.get("zone_name") or row.get("name") or zone_id,
            "x": round((x1 + x2) / 2, 2),
            "y": round((y1 + y2) / 2, 2),
            "area": max(1, round(abs((x2 - x1) * (y2 - y1)), 2)),
            "entries": safe_int(metrics.get("entry_count")),
            "exits": safe_int(metrics.get("exit_count")),
            "unique": safe_int(metrics.get("unique_people_count")),
            "dwell": safe_float(metrics.get("avg_dwell_time_seconds")),
        })
    return rows


def time_series_rows(time_rows, analysis=None):
    rows = []
    for index, row in enumerate(time_rows):
        start_seconds = safe_float(row.get("start_time_seconds", index * 30))
        end_seconds = safe_float(row.get("end_time_seconds", start_seconds + 30))
        rows.append({
            "label": row.get("time_label") or row.get("interval") or row.get("time_bin") or "",
            "clock": f"{analysis_clock_label(analysis, start_seconds)} - {analysis_clock_label(analysis, end_seconds)}",
            "clock_short": compact_clock_range(analysis, start_seconds, end_seconds),
            "start": start_seconds,
            "end": end_seconds,
            "mid": (start_seconds + end_seconds) / 2,
            "visible": safe_int(row.get("visible_people_max", row.get("people_count", 0))),
            "visible_avg": safe_float(row.get("visible_people_avg")),
            "events": safe_int(row.get("total_events")),
            "entries": safe_int(row.get("zone_entries", row.get("store_entries", 0))),
            "exits": safe_int(row.get("store_exits")),
            "unique": safe_int(row.get("unique_people_count")),
        })
    return rows


def event_time_seconds(row):
    timestamp = row.get("timestamp")
    if timestamp is not None:
        text = str(timestamp).strip()
        if ":" in text:
            parts = [safe_float(part) for part in text.split(":")]
            if len(parts) == 3:
                return parts[0] * 3600 + parts[1] * 60 + parts[2]
            if len(parts) == 2:
                return parts[0] * 60 + parts[1]
        return safe_float(text)
    frame_index = safe_float(row.get("frame_index"))
    return frame_index


def traffic_surface_payload(analysis, zone_rows, zone_metric_rows, time_rows, event_rows):
    series = time_series_rows(time_rows, analysis)
    if not series:
        duration = safe_float(analysis.total_frames) / safe_float(analysis.fps or 30)
        series = [{
            "label": "00:00 - fin",
            "clock": f"{analysis_clock_label(analysis, 0)} - {analysis_clock_label(analysis, duration)}",
            "clock_short": compact_clock_range(analysis, 0, duration),
            "start": 0,
            "end": max(duration, 30),
            "mid": max(duration, 30) / 2,
            "visible": 0,
            "events": 0,
            "entries": 0,
            "exits": 0,
            "unique": 0,
        }]

    zone_labels = []
    for index, row in enumerate(zone_rows or zone_metric_rows):
        label = row.get("zone_name") or row.get("name") or row.get("zone_id") or f"Zona {index + 1}"
        if label not in zone_labels:
            zone_labels.append(label)
    if not zone_labels:
        zone_labels = ["Actividad general"]

    matrix = [[0 for _ in series] for _ in zone_labels]
    zone_index = {label: index for index, label in enumerate(zone_labels)}

    for row in event_rows:
        label = row.get("zone_name") or row.get("zone_id") or "Actividad general"
        if label not in zone_index:
            continue
        seconds = event_time_seconds(row)
        bucket_index = len(series) - 1
        for index, bucket in enumerate(series):
            if bucket["start"] <= seconds < bucket["end"]:
                bucket_index = index
                break
        matrix[zone_index[label]][bucket_index] += 1

    if not any(any(value for value in row) for row in matrix):
        metrics_by_label = {}
        for row in zone_metric_rows or zone_rows:
            label = row.get("zone_name") or row.get("name") or row.get("zone_id") or "Actividad general"
            metrics_by_label[label] = safe_int(row.get("entry_count")) or safe_int(row.get("unique_people_count"))
        for label, value in metrics_by_label.items():
            if label in zone_index:
                matrix[zone_index[label]][0] = value

    peak = {"zone": "-", "time": "-", "value": 0}
    quiet = {"zone": "-", "time": "-", "value": 0}
    flat_values = []
    for zone_idx, zone in enumerate(zone_labels):
        for time_idx, bucket in enumerate(series):
            value = matrix[zone_idx][time_idx]
            flat_values.append((value, zone, bucket["clock"]))
            if value > peak["value"]:
                peak = {"zone": zone, "time": bucket["clock"], "value": value}
    positive_values = [item for item in flat_values if item[0] > 0]
    if positive_values:
        value, zone, label = min(positive_values, key=lambda item: item[0])
        quiet = {"zone": zone, "time": label, "value": value}

    return {
        "times": [row["clock"] for row in series],
        "timeShortLabels": [row["clock_short"] for row in series],
        "timeSeconds": [row["mid"] for row in series],
        "zones": zone_labels,
        "z": matrix,
        "peak": peak,
        "quiet": quiet,
    }


def operational_insights(analysis, zone_rows, zone_metric_rows, time_rows, event_rows):
    ranking = ranking_rows([], zone_metric_rows, zone_rows)
    series = time_series_rows(time_rows, analysis)
    surface = traffic_surface_payload(analysis, zone_rows, zone_metric_rows, time_rows, event_rows)
    max_people = max(series, key=lambda row: row["visible"], default=None)
    peak_time = max(series, key=lambda row: row["events"] or row["entries"] or row["visible"], default=None)
    quiet_time = min(series, key=lambda row: row["events"] or row["entries"] or row["visible"], default=None)
    busiest_zone = ranking[0] if ranking else {
        "label": surface["peak"]["zone"],
        "value": surface["peak"]["value"],
    }
    return {
        "busiest_zone": busiest_zone,
        "max_people": {
            "label": max_people["clock_short"] if max_people else "-",
            "value": max_people["visible"] if max_people else 0,
        },
        "peak_time": {
            "label": peak_time["clock_short"] if peak_time else surface["peak"]["time"],
            "value": (peak_time["events"] or peak_time["entries"] or peak_time["visible"]) if peak_time else surface["peak"]["value"],
        },
        "quiet_time": {
            "label": quiet_time["clock_short"] if quiet_time else surface["quiet"]["time"],
            "value": (quiet_time["events"] or quiet_time["entries"] or quiet_time["visible"]) if quiet_time else surface["quiet"]["value"],
        },
    }


def first_frame_visual_metrics(analysis):
    frame_path = Path(analysis.first_frame.path) if getattr(analysis, "first_frame", None) else None
    if not frame_path or not frame_path.exists():
        return {
            "available": False,
            "brightness": 0,
            "contrast": 0,
            "sharpness": 0,
            "comment": "No hay frame base disponible para revisar brillo, contraste y nitidez.",
        }

    try:
        import cv2
        import numpy as np
    except ImportError:
        return {
            "available": False,
            "brightness": 0,
            "contrast": 0,
            "sharpness": 0,
            "comment": "Falta OpenCV para calcular calidad visual del frame.",
        }

    frame = cv2.imread(str(frame_path))
    if frame is None:
        return {
            "available": False,
            "brightness": 0,
            "contrast": 0,
            "sharpness": 0,
            "comment": "No se pudo leer el frame base para evaluar calidad visual.",
        }

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    brightness = float(np.mean(gray))
    contrast = float(np.std(gray))
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    comments = []
    if brightness < 65:
        comments.append("la imagen se ve oscura")
    elif brightness > 190:
        comments.append("la imagen esta sobreexpuesta")
    if contrast < 32:
        comments.append("hay bajo contraste entre personas y fondo")
    if sharpness < 95:
        comments.append("la nitidez parece baja o hay movimiento/camara blanda")
    return {
        "available": True,
        "brightness": round(brightness, 1),
        "contrast": round(contrast, 1),
        "sharpness": round(sharpness, 1),
        "comment": "; ".join(comments) if comments else "El frame base tiene condiciones visuales razonables para deteccion.",
    }


def video_quality_score(analysis):
    width = safe_int(getattr(analysis, "frame_width", 0))
    height = safe_int(getattr(analysis, "frame_height", 0))
    fps = safe_float(getattr(analysis, "fps", 0))
    total_frames = safe_int(getattr(analysis, "total_frames", 0))
    processed_frames = safe_int(getattr(analysis, "processed_frames", 0))
    duration = total_frames / fps if fps else 0
    zones_count = len(getattr(analysis, "zones", []) or [])
    visual = first_frame_visual_metrics(analysis)

    score = 0
    checks = []

    resolution_ok = width >= 1280 and height >= 720
    score += 20 if resolution_ok else 10 if width and height else 0
    checks.append({"label": "Resolucion", "value": f"{width}x{height}" if width and height else "Sin metadata", "ok": resolution_ok})

    fps_ok = fps >= 24
    score += 15 if fps_ok else 8 if fps else 0
    checks.append({"label": "FPS", "value": format_number(fps) if fps else "-", "ok": fps_ok})

    duration_ok = duration >= 30
    score += 10 if duration_ok else 5 if duration else 0
    checks.append({"label": "Duracion", "value": format_hms(duration), "ok": duration_ok})

    zones_ok = zones_count > 0
    score += 10 if zones_ok else 0
    checks.append({"label": "Zonas", "value": str(zones_count), "ok": zones_ok})

    coverage = processed_frames / total_frames if total_frames else 0
    coverage_ok = coverage >= 0.95 or analysis.status == AnalysisRun.Status.COMPLETED
    score += 10 if coverage_ok else 4 if processed_frames else 0
    checks.append({"label": "Cobertura", "value": f"{round(coverage * 100)}%" if total_frames else "-", "ok": coverage_ok})

    if visual["available"]:
        brightness_ok = 65 <= visual["brightness"] <= 190
        contrast_ok = visual["contrast"] >= 32
        sharpness_ok = visual["sharpness"] >= 95
        score += 15 if brightness_ok else 5
        score += 10 if contrast_ok else 3
        score += 10 if sharpness_ok else 3
        checks.append({"label": "Brillo", "value": visual["brightness"], "ok": brightness_ok})
        checks.append({"label": "Contraste", "value": visual["contrast"], "ok": contrast_ok})
        checks.append({"label": "Nitidez", "value": visual["sharpness"], "ok": sharpness_ok})

    score = min(100, round(score))
    label = "Excelente" if score >= 85 else "Operativa" if score >= 70 else "Revisar" if score >= 50 else "Critica"
    return {"score": score, "label": label, "checks": checks, "visual": visual}


def friction_rows(zone_metric_rows, zone_rows):
    source = zone_metric_rows or zone_rows
    rows = []
    for row in source:
        entries = safe_int(row.get("entry_count"))
        unique = safe_int(row.get("unique_people_count"))
        dwell = safe_float(row.get("avg_dwell_time_seconds"))
        score = round(entries * 0.45 + unique * 0.2 + dwell * 0.35, 1)
        if score > 0:
            rows.append({
                "label": row.get("zone_name") or row.get("zone_id") or "Zona",
                "score": score,
                "entries": entries,
                "unique": unique,
                "dwell": format_hms(dwell),
            })
    return sorted(rows, key=lambda row: row["score"], reverse=True)[:8]


def trajectory_cluster_rows(people_rows):
    clusters = {}
    for row in people_rows:
        first_zone = row.get("first_zone") or "Sin zona inicial"
        last_zone = row.get("last_zone") or "Sin zona final"
        key = f"{first_zone} -> {last_zone}"
        cluster = clusters.setdefault(key, {
            "label": key,
            "count": 0,
            "visible_seconds": 0.0,
            "distance": 0.0,
        })
        cluster["count"] += 1
        cluster["visible_seconds"] += safe_float(row.get("visible_time_seconds"))
        cluster["distance"] += safe_float(row.get("distance_px"))

    rows = []
    for cluster in clusters.values():
        count = max(1, cluster["count"])
        rows.append({
            "label": cluster["label"],
            "count": cluster["count"],
            "avg_visible": format_hms(cluster["visible_seconds"] / count),
            "avg_distance": round(cluster["distance"] / count, 1),
        })
    return sorted(rows, key=lambda row: row["count"], reverse=True)[:8]


def layout_scenario_rows(friction_data):
    scenarios = []
    for row in friction_data[:3]:
        scenarios.append({
            "title": f"Redistribuir {row['label']}",
            "body": "Duplicar, ampliar o dividir esta zona podria reducir espera percibida si el flujo esta concentrado.",
            "impact": f"-{min(24, max(8, int(row['score'] // 4)))}% friccion estimada",
        })
    return scenarios


def narrative_summary(analysis, summary, insights, alerts, comparison, video_quality):
    lines = [
        f"El analisis {analysis.display_name} muestra {summary.get('total_people', '-')} personas validadas y {summary.get('total_zone_entries', '0')} entradas a zonas.",
        f"La zona dominante es {insights['busiest_zone']['label']} y el peak se observa en {insights['peak_time']['label']}.",
        f"La calidad tecnica del video queda en {video_quality['score']}/100 ({video_quality['label']}).",
    ]
    if alerts:
        lines.append(f"La alerta principal es {alerts[0]['title'].lower()}: {alerts[0]['body']}")
    if comparison:
        lines.append(f"Frente a {comparison['analysis'].display_name}, las entradas cambian {comparison['entries']['absolute']:+d}.")
    return lines


def local_ai_analyst(summary, insights, alerts, layout_scenarios, video_quality):
    return {
        "enabled": False,
        "source": "local",
        "status": "Configura OPENAI_API_KEY para activar analista IA.",
        "narrative": narrative_summary_placeholder(summary, insights, alerts, video_quality),
        "layout_recommendations": layout_scenarios,
        "video_quality_comment": video_quality["visual"]["comment"],
        "video_improvement_actions": [
            "Usa un plano fijo con buena iluminacion frontal.",
            "Evita contraluces, reflejos fuertes y camara en movimiento.",
            "Mantén personas completas dentro del encuadre en las zonas criticas.",
        ],
        "confidence": "Media",
    }


def narrative_summary_placeholder(summary, insights, alerts, video_quality):
    lines = [
        f"Se detectan {summary.get('total_people', '-')} personas validadas y {summary.get('total_zone_entries', '0')} entradas a zonas.",
        f"El foco principal esta en {insights['busiest_zone']['label']} y el peak operativo aparece cerca de {insights['peak_time']['label']}.",
        f"La calidad visual queda en {video_quality['score']}/100 ({video_quality['label']}): {video_quality['visual']['comment']}",
    ]
    if alerts:
        lines.append(f"Prioridad sugerida: revisar {alerts[0]['title'].lower()} porque puede afectar interpretacion o operacion.")
    return lines


def first_frame_data_url(analysis):
    frame_path = Path(analysis.first_frame.path) if getattr(analysis, "first_frame", None) else None
    if not frame_path or not frame_path.exists():
        return ""
    try:
        from PIL import Image
    except ImportError:
        return ""

    try:
        with Image.open(frame_path) as image:
            image.thumbnail((960, 540))
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="JPEG", quality=78)
    except Exception:
        return ""
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def openai_analyst_schema():
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "narrative": {"type": "array", "items": {"type": "string"}},
            "layout_recommendations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "title": {"type": "string"},
                        "body": {"type": "string"},
                        "impact": {"type": "string"},
                    },
                    "required": ["title", "body", "impact"],
                },
            },
            "video_quality_comment": {"type": "string"},
            "video_improvement_actions": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "string"},
        },
        "required": [
            "narrative",
            "layout_recommendations",
            "video_quality_comment",
            "video_improvement_actions",
            "confidence",
        ],
    }


def extract_response_text(response_payload):
    if response_payload.get("output_text"):
        return response_payload["output_text"]
    for output in response_payload.get("output", []):
        for content in output.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                return content["text"]
    return ""


def request_openai_analyst(analysis, summary, insights, alerts, comparison, video_quality, layout_scenarios):
    api_key = getattr(settings, "OPENAI_API_KEY", "")
    if not api_key:
        return None

    payload = {
        "analysis": {
            "name": analysis.display_name,
            "establishment": analysis.mall_label,
            "category": analysis.category_label,
            "area": analysis.area_label,
            "status": analysis.get_status_display(),
        },
        "summary": summary,
        "insights": insights,
        "alerts": alerts,
        "comparison": {
            "previous_analysis": comparison["analysis"].display_name,
            "people_delta": comparison["people"],
            "entries_delta": comparison["entries"],
        } if comparison else None,
        "video_quality": video_quality,
        "layout_scenarios": layout_scenarios,
        "zones": analysis.zones,
    }
    content = [
        {
            "type": "input_text",
            "text": (
                "Actua como analista senior de datos y operaciones. Devuelve hallazgos accionables, "
                "recomendaciones de layout y comentarios de calidad de video basados solo en esta evidencia. "
                "Evita exagerar certeza si los datos son escasos."
            ),
        },
        {"type": "input_text", "text": json.dumps(payload, ensure_ascii=False)},
    ]
    image_url = first_frame_data_url(analysis)
    if image_url:
        content.append({"type": "input_image", "image_url": image_url})

    request_payload = {
        "model": getattr(settings, "OPENAI_ANALYST_MODEL", "gpt-4o-mini"),
        "input": [{"role": "user", "content": content}],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "peoplemetrics_analyst",
                "strict": True,
                "schema": openai_analyst_schema(),
            }
        },
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(request_payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=24) as response:
            body = response.read().decode("utf-8")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
        return None

    try:
        parsed = json.loads(extract_response_text(json.loads(body)))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    parsed.update({"enabled": True, "source": "openai", "status": "Analisis generado por IA"})
    return parsed


def ai_analyst_context(analysis, summary, insights, alerts, comparison, video_quality, layout_scenarios):
    fallback = local_ai_analyst(summary, insights, alerts, layout_scenarios, video_quality)
    if not getattr(settings, "OPENAI_API_KEY", ""):
        return fallback

    cache_key = "ai_analyst_v1"
    cached = InsightNote.objects.filter(analysis=analysis, insight_key=cache_key).first()
    if cached and cached.updated_at >= analysis.updated_at:
        try:
            data = json.loads(cached.body)
            data.update({"enabled": True, "source": "openai", "status": "Analisis generado por IA"})
            return data
        except (TypeError, ValueError, json.JSONDecodeError):
            pass

    generated = request_openai_analyst(analysis, summary, insights, alerts, comparison, video_quality, layout_scenarios)
    if not generated:
        fallback["status"] = "IA no disponible temporalmente; mostrando analisis local."
        return fallback

    InsightNote.objects.update_or_create(
        analysis=analysis,
        insight_key=cache_key,
        defaults={"body": json.dumps(generated, ensure_ascii=False)},
    )
    return generated


def operational_alerts(analysis, summary, insights, chart_payload, zone_metric_rows, zone_rows, video_quality):
    alerts = []
    total_entries = safe_int(summary.get("total_zone_entries"))
    total_people = safe_int(summary.get("total_people"))
    max_people = safe_int(insights["max_people"]["value"])
    peak_value = safe_int(insights["peak_time"]["value"])
    time_values = [
        safe_int(row.get("events")) or safe_int(row.get("entries")) or safe_int(row.get("visible"))
        for row in chart_payload.get("time", [])
    ]
    avg_activity = sum(time_values) / len(time_values) if time_values else 0
    busiest = insights["busiest_zone"]

    if peak_value and avg_activity and peak_value >= avg_activity * 1.6:
        alerts.append({
            "level": "high",
            "title": "Peak anomalo",
            "body": f"{insights['peak_time']['label']} concentra {peak_value} eventos, sobre el promedio del video.",
        })
    if time_values and min(time_values) == 0:
        alerts.append({
            "level": "medium",
            "title": "Caida de deteccion",
            "body": "Hay tramos sin actividad detectada; conviene revisar si es baja demanda real, oclusion o perdida de tracking.",
        })
    if max_people >= max(8, round(total_people * 0.35)) and total_people:
        alerts.append({
            "level": "high",
            "title": "Sobreocupacion relativa",
            "body": f"El maximo simultaneo llega a {max_people} personas, alto frente al total validado del video.",
        })
    if total_entries and safe_int(busiest["value"]) >= total_entries * 0.45:
        alerts.append({
            "level": "high",
            "title": "Zona dominante",
            "body": f"{busiest['label']} concentra una parte relevante de las entradas.",
        })
    metric_source = zone_metric_rows or zone_rows
    for row in metric_source:
        if safe_float(row.get("avg_dwell_time_seconds")) >= 60:
            alerts.append({
                "level": "medium",
                "title": "Cola persistente",
                "body": f"{row.get('zone_name') or row.get('zone_id') or 'Una zona'} supera 60 segundos promedio.",
            })
            break
    if metric_source:
        cold_zones = [
            row.get("zone_name") or row.get("zone_id") or "Zona"
            for row in metric_source
            if safe_int(row.get("entry_count")) == 0 and (safe_int(row.get("unique_people_count")) == 0 or total_entries > 0)
        ]
        if cold_zones and len(cold_zones) < len(metric_source):
            alerts.append({
                "level": "medium",
                "title": "Zona fria",
                "body": f"{cold_zones[0]} no registra entradas mientras otras zonas si reciben flujo.",
            })
    if video_quality["score"] < 70:
        alerts.append({
            "level": "medium",
            "title": "Calidad de video mejorable",
            "body": f"Score {video_quality['score']}/100. Interpreta los resultados con cautela.",
        })
    if analysis.status != AnalysisRun.Status.COMPLETED:
        alerts.append({
            "level": "low",
            "title": "Analisis no completado",
            "body": "Algunas metricas pueden estar incompletas hasta terminar la ejecucion.",
        })
    return alerts[:5]


def analysis_comparison(analysis, summary, ranking_rows_data):
    if not analysis:
        return None
    candidates = AnalysisRun.objects.filter(
        status=AnalysisRun.Status.COMPLETED,
        created_at__lt=analysis.created_at,
    ).exclude(pk=analysis.pk)
    if analysis.mall_group_id:
        candidates = candidates.filter(mall_group=analysis.mall_group)
    if analysis.category:
        candidates = candidates.filter(category=analysis.category)
    if analysis.area:
        candidates = candidates.filter(area=analysis.area)
    previous = candidates.first()
    if not previous:
        return None

    previous_snapshot = analysis_summary_snapshot(previous)
    current_people = safe_int(summary.get("total_people"))
    current_entries = safe_int(summary.get("total_zone_entries"))
    previous_people = previous_snapshot["total_people"]
    previous_entries = previous_snapshot["zone_entries"]

    def delta(current, previous):
        absolute = current - previous
        pct = round((absolute / previous) * 100, 1) if previous else None
        return {"current": current, "previous": previous, "absolute": absolute, "pct": pct}

    return {
        "analysis": previous,
        "people": delta(current_people, previous_people),
        "entries": delta(current_entries, previous_entries),
        "top_zone": ranking_rows_data[0]["label"] if ranking_rows_data else "-",
    }


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
        "store_entries": safe_int(summary.get("total_store_entries") or summary.get("total_focus_activity")),
        "avg_dwell_seconds": safe_float(summary.get("avg_dwell_time_seconds")),
        "avg_dwell_label": summary.get("avg_dwell_time", "-"),
    }


def analysis_bundle_entries(analysis):
    ensure_results_database(analysis)
    entries = []
    files = {
        "video": Path(analysis.video.path) if analysis.video else None,
        "first_frame": Path(analysis.first_frame.path) if analysis.first_frame else None,
    }
    for label, path in files.items():
        if path and path.exists():
            entries.append({
                "arcname": f"assets/{label}{path.suffix.lower()}",
                "path": path,
            })

    output_path = analysis.output_path
    if output_path.exists():
        for child in sorted(output_path.rglob("*")):
            if child.is_file():
                entries.append({
                    "arcname": f"outputs/{child.relative_to(output_path).as_posix()}",
                    "path": child,
                })

    manifest = {
        "analysis_id": str(analysis.pk),
        "display_name": analysis.display_name,
        "status": analysis.status,
        "status_label": analysis.get_status_display(),
        "mall": analysis.mall_label,
        "category": analysis.category_label,
        "area": analysis.area_label,
        "created_at": analysis.created_at.isoformat() if analysis.created_at else "",
        "updated_at": analysis.updated_at.isoformat() if analysis.updated_at else "",
        "video_name": Path(analysis.video.name).name if analysis.video else "",
        "frame_width": analysis.frame_width,
        "frame_height": analysis.frame_height,
        "fps": analysis.fps,
        "total_frames": analysis.total_frames,
        "zones": analysis.zones,
    }
    entries.append({
        "arcname": "manifest.json",
        "content": json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"),
    })
    return entries


def build_analysis_zip_bytes(analysis):
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for entry in analysis_bundle_entries(analysis):
            if "path" in entry:
                archive.write(entry["path"], entry["arcname"])
            else:
                archive.writestr(entry["arcname"], entry["content"])
    bundle.seek(0)
    return bundle


def build_mall_zip_bytes(mall):
    bundle = io.BytesIO()
    analyses = list(mall.analyses.order_by("-created_at"))
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        manifest = {
            "mall_id": mall.pk,
            "mall_name": mall.name,
            "accent_color": mall.accent_color,
            "notes": mall.notes,
            "analysis_count": len(analyses),
            "analyses": [
                {
                    "analysis_id": str(analysis.pk),
                    "display_name": analysis.display_name,
                    "status": analysis.status,
                    "status_label": analysis.get_status_display(),
                }
                for analysis in analyses
            ],
        }
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"))

        for index, analysis in enumerate(analyses, start=1):
            folder_name = f"{index:02d}-{slug_token(analysis.display_name, 'analysis')}"
            for entry in analysis_bundle_entries(analysis):
                arcname = f"analyses/{folder_name}/{entry['arcname']}"
                if "path" in entry:
                    archive.write(entry["path"], arcname)
                else:
                    archive.writestr(arcname, entry["content"])
    bundle.seek(0)
    return bundle


def executive_report_lines(analysis):
    context = dashboard_context(analysis)
    summary = context["summary"]
    insights = context["operational_insights"]
    quality = context["video_quality"]
    alerts = context["operational_alerts"]
    lines = [
        f"PIPOLMETRICS - Reporte ejecutivo",
        f"Analisis: {analysis.display_name}",
        f"Establecimiento: {analysis.mall_label or 'Sin establecimiento'}",
        f"Categoria: {analysis.category_label or 'General'}",
        f"Zona o sector: {analysis.area_label or 'Sin sector'}",
        "",
        "Resumen",
        f"Personas validadas: {summary.get('total_people', '-')}",
        f"Entradas a zonas: {summary.get('total_zone_entries', '0')}",
        f"Actividad focal: {summary.get('total_focus_activity', summary.get('total_zone_entries', '0'))}",
        f"Permanencia promedio: {summary.get('avg_dwell_time', '-')}",
        "",
        "Highlights",
        f"Zona mas transitada: {insights['busiest_zone']['label']} ({insights['busiest_zone']['value']} eventos)",
        f"Maximo de personas: {insights['max_people']['value']} ({insights['max_people']['label']})",
        f"Horario peak: {insights['peak_time']['label']} ({insights['peak_time']['value']} eventos)",
        f"Horario minimo: {insights['quiet_time']['label']} ({insights['quiet_time']['value']} eventos)",
        f"Calidad de video: {quality['score']}/100 - {quality['label']}",
        "",
        "Alertas operativas",
    ]
    if alerts:
        lines.extend(f"- {alert['title']}: {alert['body']}" for alert in alerts)
    else:
        lines.append("- Sin alertas relevantes con la evidencia actual.")
    if context["analysis_comparison"]:
        comparison = context["analysis_comparison"]
        lines.extend([
            "",
            "Comparacion",
            f"Base anterior: {comparison['analysis'].display_name}",
            f"Personas: {comparison['people']['current']} vs {comparison['people']['previous']} ({comparison['people']['absolute']:+d})",
            f"Entradas: {comparison['entries']['current']} vs {comparison['entries']['previous']} ({comparison['entries']['absolute']:+d})",
        ])
    return lines


def mall_executive_report_lines(mall):
    analyses = list(mall.analyses.order_by("-created_at")[:12])
    completed = [analysis for analysis in analyses if analysis.status == AnalysisRun.Status.COMPLETED]
    snapshots = [analysis_summary_snapshot(analysis) for analysis in completed]
    total_people = sum(snapshot["total_people"] for snapshot in snapshots)
    total_entries = sum(snapshot["zone_entries"] for snapshot in snapshots)
    total_focus = sum(snapshot["store_entries"] for snapshot in snapshots)
    lines = [
        "PIPOLMETRICS - Reporte ejecutivo de establecimiento",
        f"Establecimiento: {mall.name}",
        f"Notas operativas: {mall.notes or 'Sin notas'}",
        f"Analisis revisados: {len(analyses)}",
        f"Analisis completados: {len(completed)}",
        "",
        "Resumen acumulado",
        f"Personas validadas: {total_people}",
        f"Entradas a zonas: {total_entries}",
        f"Actividad focal: {total_focus}",
        "",
        "Analisis incluidos",
    ]
    if snapshots:
        for snapshot in snapshots[:8]:
            lines.append(
                f"- {snapshot['analysis'].display_name}: {snapshot['total_people']} personas, {snapshot['zone_entries']} entradas"
            )
    else:
        lines.append("- Sin analisis completados para consolidar.")
    return lines


def pdf_escape(text):
    return str(text).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf_from_lines(lines):
    content_lines = ["BT", "/F1 11 Tf", "50 780 Td", "14 TL"]
    for index, line in enumerate(lines[:48]):
        if index:
            content_lines.append("T*")
        content_lines.append(f"({pdf_escape(line[:96])}) Tj")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    pdf = io.BytesIO()
    pdf.write(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(pdf.tell())
        pdf.write(f"{index} 0 obj\n".encode("ascii"))
        pdf.write(obj)
        pdf.write(b"\nendobj\n")
    xref_offset = pdf.tell()
    pdf.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.write(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii"))
    pdf.seek(0)
    return pdf


def build_executive_pdf_bytes(analysis):
    return build_pdf_from_lines(executive_report_lines(analysis))


def build_mall_executive_pdf_bytes(mall):
    return build_pdf_from_lines(mall_executive_report_lines(mall))


def pptx_slide_xml(title, bullets):
    bullet_xml = "".join(
        f"<a:p><a:r><a:rPr lang=\"es-CL\" sz=\"2200\"/><a:t>{escape(str(bullet))}</a:t></a:r></a:p>"
        for bullet in bullets
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree>
    <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>
    <p:sp><p:nvSpPr><p:cNvPr id="2" name="Title"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="457200" y="365760"/><a:ext cx="8229600" cy="914400"/></a:xfrm></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="es-CL" sz="3600" b="1"/><a:t>{escape(str(title))}</a:t></a:r></a:p></p:txBody></p:sp>
    <p:sp><p:nvSpPr><p:cNvPr id="3" name="Body"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="685800" y="1371600"/><a:ext cx="7772400" cy="4572000"/></a:xfrm></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/>{bullet_xml}</p:txBody></p:sp>
  </p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>"""


def build_pptx_from_lines(lines):
    chunks = [
        ("Resumen ejecutivo", lines[1:10]),
        ("Highlights operativos", lines[12:20]),
        ("Alertas y siguientes pasos", lines[22:34]),
    ]
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
<Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
<Override PartName="/ppt/slides/slide2.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
<Override PartName="/ppt/slides/slide3.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
</Types>""")
        archive.writestr("_rels/.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
</Relationships>""")
        archive.writestr("ppt/presentation.xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
<p:sldIdLst><p:sldId id="256" r:id="rId1"/><p:sldId id="257" r:id="rId2"/><p:sldId id="258" r:id="rId3"/></p:sldIdLst>
<p:sldSz cx="9144000" cy="5143500" type="wide"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>""")
        archive.writestr("ppt/_rels/presentation.xml.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide2.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide3.xml"/>
</Relationships>""")
        for index, (title, bullets) in enumerate(chunks, start=1):
            archive.writestr(f"ppt/slides/slide{index}.xml", pptx_slide_xml(title, bullets[:8]))
            archive.writestr(f"ppt/slides/_rels/slide{index}.xml.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>""")
    bundle.seek(0)
    return bundle


def build_executive_pptx_bytes(analysis):
    return build_pptx_from_lines(executive_report_lines(analysis))


def build_mall_executive_pptx_bytes(mall):
    return build_pptx_from_lines(mall_executive_report_lines(mall))


def mall_overview_cards(analyses=None):
    cards = []
    malls = list(Mall.objects.all())
    allowed_ids = None
    if analyses is not None:
        allowed_ids = set(analyses.values_list("pk", flat=True))
    for mall in malls:
        mall_analyses = list(mall.analyses.order_by("-created_at"))
        if allowed_ids is not None:
            mall_analyses = [analysis for analysis in mall_analyses if analysis.pk in allowed_ids]
            if not mall_analyses:
                continue
        completed = [analysis for analysis in mall_analyses if analysis.status == AnalysisRun.Status.COMPLETED]
        snapshots = [analysis_summary_snapshot(analysis) for analysis in completed[:6]]
        latest_snapshot = snapshots[0] if snapshots else None

        total_people = sum(snapshot["total_people"] for snapshot in snapshots)
        total_zone_entries = sum(snapshot["zone_entries"] for snapshot in snapshots)
        total_focus_activity = sum(snapshot["store_entries"] for snapshot in snapshots)
        dwell_values = [snapshot["avg_dwell_seconds"] for snapshot in snapshots if snapshot["avg_dwell_seconds"] > 0]
        avg_dwell_seconds = sum(dwell_values) / len(dwell_values) if dwell_values else 0
        hours = int(avg_dwell_seconds) // 3600
        minutes = (int(avg_dwell_seconds) % 3600) // 60
        seconds = int(avg_dwell_seconds) % 60
        avg_dwell_label = f"{hours:02d}:{minutes:02d}:{seconds:02d}" if dwell_values else "-"

        cards.append({
            "mall": mall,
            "analysis_count": len(mall_analyses),
            "completed_count": len(completed),
            "latest_snapshot": latest_snapshot,
            "recent_snapshots": snapshots[:3],
            "total_people": total_people,
            "total_zone_entries": total_zone_entries,
            "total_focus_activity": total_focus_activity,
            "avg_dwell_label": avg_dwell_label,
        })
    return sorted(cards, key=lambda card: card["analysis_count"], reverse=True)


def dashboard_context(analysis=None, overview_analyses=None):
    if analysis is None:
        mall_cards = mall_overview_cards(overview_analyses)
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
        "zoneActivity": zone_activity_rows(store_rows, zone_metric_rows, zone_rows),
        "spatialZones": spatial_zone_rows(zone_rows, zone_metric_rows),
        "time": time_series_rows(time_rows, analysis),
        "trafficSurface": traffic_surface_payload(analysis, zone_rows, zone_metric_rows, time_rows, event_rows),
        "friction": friction_rows(zone_metric_rows, zone_rows),
        "clusters": trajectory_cluster_rows(people_rows),
        "stairs": stair_rows_for_chart(stair_rows),
    }
    insights = operational_insights(analysis, zone_rows, zone_metric_rows, time_rows, event_rows)
    video_quality = video_quality_score(analysis)
    alerts = operational_alerts(analysis, summary, insights, chart_payload, zone_metric_rows, zone_rows, video_quality)
    comparison = analysis_comparison(analysis, summary, chart_payload["ranking"])
    scenarios = layout_scenario_rows(chart_payload["friction"])
    narrative = narrative_summary(analysis, summary, insights, alerts, comparison, video_quality)
    ai_analyst = ai_analyst_context(analysis, summary, insights, alerts, comparison, video_quality, scenarios)
    insight_notes = {
        note.insight_key: note
        for note in InsightNote.objects.filter(analysis=analysis)
    }

    return {
        "dashboard_mode": "analysis",
        "analysis": analysis,
        "analyses": AnalysisRun.objects.all()[:12],
        "summary": summary,
        "ranking_rows": chart_payload["ranking"],
        "store_flow_rows": chart_payload["zoneActivity"],
        "spatial_zone_rows": chart_payload["spatialZones"],
        "time_chart_rows": chart_payload["time"],
        "stair_chart_rows": chart_payload["stairs"],
        "operational_insights": insights,
        "operational_alerts": alerts,
        "analysis_comparison": comparison,
        "video_quality": video_quality,
        "friction_rows": chart_payload["friction"],
        "trajectory_clusters": chart_payload["clusters"],
        "layout_scenarios": scenarios,
        "narrative_summary": narrative,
        "ai_analyst": ai_analyst,
        "metric_dictionary": METRIC_DICTIONARY,
        "insight_notes": insight_notes,
        "zone_versions": analysis.zone_versions.select_related("created_by")[:6],
        "audit_logs": AnalysisAuditLog.objects.select_related("actor").filter(analysis=analysis)[:8],
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
                "name": REPORT_LABELS.get(label, label),
                "filename": filename,
                "exists": report_path(filename, analysis).exists(),
                "url": f"{analysis.report_media_prefix}{filename}" if analysis and report_path(filename, analysis).exists() else "",
            }
            for label, filename in REPORT_FILES.items()
        ],
    }


def reports_context(analysis=None):
    context = dashboard_context(analysis)
    malls = list(Mall.objects.prefetch_related("analyses").all())
    context.update({
        "mall_report_rows": [
            {
                "mall": mall,
                "analyses": list(mall.analyses.order_by("-created_at")),
            }
            for mall in malls
        ],
        "unassigned_analyses": AnalysisRun.objects.select_related("mall_group").filter(mall_group__isnull=True).order_by("-created_at")[:80],
    })
    return context
