import csv
import json
import re
import sqlite3
import time
from collections import defaultdict, deque
from pathlib import Path

from django.utils import timezone

import config
from config import (
    ZONE_STYLES,
    confidence,
    display_every_n_frames,
    heatmap_output_file,
    iou_value,
    model_name,
    parking_frame_stride,
    parking_model_name,
    tracker_type,
    zone_report_file,
)

from .models import AnalysisRun


analytics_summary_file = "analytics_summary.csv"
person_tracks_file = "person_tracks.csv"
zone_events_file = "zone_events.csv"
zone_metrics_file = "zone_metrics.csv"
store_metrics_file = "store_metrics.csv"
dwell_times_file = "dwell_times.csv"
time_bins_file = "time_bins.csv"
stair_metrics_file = "stair_metrics.csv"
zones_config_file = "zonas_configuradas.json"
analytics_database_file = "analysis_results.sqlite3"
parking_slots_file = "parking_slots.csv"
parking_sessions_file = "parking_sessions.csv"
parking_summary_file = "parking_summary.csv"
vehicle_class_ids = {2, 3, 5, 7}

tracking_confidence = max(float(confidence), 0.40)
min_confirmed_frames = 8
min_person_height_px = 45
min_person_area_px = 1200
min_width_height_ratio = 0.12
max_width_height_ratio = 1.25
reid_max_seconds = 1.25
reid_max_distance_px = 85
min_zone_presence_seconds = 0.35
entry_disappear_seconds = 2.0
stair_direction_threshold_px = 25
time_bin_seconds = 30

if "frente_tienda" not in ZONE_STYLES:
    ZONE_STYLES["frente_tienda"] = {
        "label": "FRENTE TIENDA",
        "bgr": (255, 140, 0),
        "hex": "#00A8FF",
    }


def display_zone_label(zone):
    custom_name = str(zone.get("name", "")).strip()
    if custom_name:
        return custom_name
    zone_type = zone.get("type", "zona")
    base_label = ZONE_STYLES.get(zone_type, {}).get("label", zone_type.upper())
    return f"{base_label} {zone.get('id', '')}".strip()


def safe_div(numerator, denominator):
    if denominator == 0:
        return 0
    return numerator / denominator


def format_seconds(seconds):
    try:
        seconds = int(float(seconds))
    except Exception:
        seconds = 0
    minutes = seconds // 60
    remaining_seconds = seconds % 60
    return f"{minutes:02d}:{remaining_seconds:02d}"


def write_csv_file(path, fieldnames, rows):
    with Path(path).open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def sqlite_table_name(filename):
    stem = re.sub(r"[^0-9a-zA-Z_]+", "_", Path(filename).stem).strip("_").lower()
    if not stem:
        stem = "table"
    if stem[0].isdigit():
        stem = f"t_{stem}"
    return stem


def import_csv_to_sqlite(connection, csv_path, table_name):
    if not csv_path.exists():
        return 0

    with csv_path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        fields = reader.fieldnames or []
        if not fields:
            return 0
        quoted_fields = ", ".join(f'"{field}" TEXT' for field in fields)
        connection.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        connection.execute(f'CREATE TABLE "{table_name}" ({quoted_fields})')

        placeholders = ", ".join("?" for _ in fields)
        quoted_names = ", ".join(f'"{field}"' for field in fields)
        rows = [[row.get(field, "") for field in fields] for row in reader]
        if rows:
            connection.executemany(
                f'INSERT INTO "{table_name}" ({quoted_names}) VALUES ({placeholders})',
                rows,
            )
        return len(rows)


def build_results_database(output_dir, analysis_id, video_path, zones):
    output_dir = Path(output_dir)
    database_path = output_dir / analytics_database_file
    if database_path.exists():
        database_path.unlink()

    csv_files = [
        analytics_summary_file,
        person_tracks_file,
        zone_events_file,
        zone_metrics_file,
        store_metrics_file,
        dwell_times_file,
        time_bins_file,
        stair_metrics_file,
        zone_report_file,
        parking_slots_file,
        parking_sessions_file,
        parking_summary_file,
    ]
    asset_files = [heatmap_output_file, zones_config_file]

    with sqlite3.connect(database_path) as connection:
        connection.execute("""
            CREATE TABLE manifest (
                name TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                exists_on_disk INTEGER NOT NULL,
                size_bytes INTEGER NOT NULL,
                imported_table TEXT NOT NULL,
                row_count INTEGER NOT NULL
            )
        """)
        connection.execute("""
            CREATE TABLE study (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        connection.executemany(
            "INSERT INTO study (key, value) VALUES (?, ?)",
            [
                ("analysis_id", str(analysis_id)),
                ("video_path", str(video_path)),
                ("heatmap_file", heatmap_output_file),
            ],
        )
        connection.execute("""
            CREATE TABLE zones_geometry (
                zone_id TEXT PRIMARY KEY,
                zone_name TEXT NOT NULL,
                zone_type TEXT NOT NULL,
                points_json TEXT NOT NULL,
                x1 INTEGER NOT NULL,
                y1 INTEGER NOT NULL,
                x2 INTEGER NOT NULL,
                y2 INTEGER NOT NULL
            )
        """)
        connection.executemany(
            """
            INSERT INTO zones_geometry
            (zone_id, zone_name, zone_type, points_json, x1, y1, x2, y2)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    zone["id"],
                    display_zone_label(zone),
                    zone["type"],
                    json.dumps(zone.get("points", []), ensure_ascii=False),
                    zone["x1"],
                    zone["y1"],
                    zone["x2"],
                    zone["y2"],
                )
                for zone in zones
            ],
        )

        for filename in csv_files:
            path = output_dir / filename
            table_name = sqlite_table_name(filename)
            row_count = import_csv_to_sqlite(connection, path, table_name)
            connection.execute(
                "INSERT INTO manifest VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    filename,
                    "csv",
                    filename,
                    int(path.exists()),
                    path.stat().st_size if path.exists() else 0,
                    table_name,
                    row_count,
                ),
            )

        for filename in asset_files:
            path = output_dir / filename
            connection.execute(
                "INSERT INTO manifest VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    filename,
                    "asset",
                    filename,
                    int(path.exists()),
                    path.stat().st_size if path.exists() else 0,
                    "",
                    0,
                ),
            )


def get_store_name_from_zone(zone):
    name = display_zone_label(zone).strip()
    lower_name = name.lower()
    prefixes = [
        "puerta de ",
        "puerta ",
        "frente tienda ",
        "frente de ",
        "frente ",
        "local ",
    ]
    for prefix in prefixes:
        if lower_name.startswith(prefix):
            return name[len(prefix):].strip() or name
    return name


def save_zone_report(output_dir, zones, zone_counts):
    path = Path(output_dir) / zone_report_file
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow([
            "zone_id",
            "zone_name",
            "zone_type",
            "points_json",
            "x1",
            "y1",
            "x2",
            "y2",
            "entry_count",
        ])
        for zone in zones:
            writer.writerow([
                zone["id"],
                display_zone_label(zone),
                zone["type"],
                json.dumps(zone.get("points", []), ensure_ascii=False),
                zone["x1"],
                zone["y1"],
                zone["x2"],
                zone["y2"],
                zone_counts.get(zone["id"], 0),
            ])


def export_professional_analytics(
    output_dir,
    video_path,
    fps,
    total_frames,
    frame_width,
    frame_height,
    person_labels,
    person_stats,
    zone_metrics,
    store_metrics,
    stair_metrics,
    events,
    dwell_rows,
    time_bins,
    visible_people_samples,
    rejected_detection_count,
    raw_track_count,
    confirmed_people_count,
):
    output_dir = Path(output_dir)
    duration_seconds = safe_div(total_frames, fps)
    total_people = len(person_labels)

    visible_values = [sample["visible_people"] for sample in visible_people_samples]
    avg_visible = safe_div(sum(visible_values), len(visible_values)) if visible_values else 0
    max_visible = max(visible_values) if visible_values else 0

    total_store_entries = sum(metric["estimated_entries"] for metric in store_metrics.values())
    total_store_exits = sum(metric["estimated_exits"] for metric in store_metrics.values())
    total_exterior_traffic = sum(metric["exterior_traffic"] for metric in store_metrics.values())
    total_stair_up = sum(metric["up_count"] for metric in stair_metrics.values())
    total_stair_down = sum(metric["down_count"] for metric in stair_metrics.values())

    all_dwell_seconds = [row["dwell_time_seconds"] for row in dwell_rows]
    avg_dwell = safe_div(sum(all_dwell_seconds), len(all_dwell_seconds)) if all_dwell_seconds else 0

    summary_rows = [{
        "video_name": Path(video_path).name,
        "video_path": video_path,
        "duration_seconds": round(duration_seconds, 2),
        "duration_formatted": format_seconds(duration_seconds),
        "fps": round(fps, 2),
        "total_frames": total_frames,
        "frame_width": frame_width,
        "frame_height": frame_height,
        "total_people": total_people,
        "raw_track_count": raw_track_count,
        "confirmed_people_count": confirmed_people_count,
        "rejected_detection_count": rejected_detection_count,
        "avg_visible_people": round(avg_visible, 2),
        "max_visible_people": max_visible,
        "total_events": len(events),
        "total_zone_entries": sum(metric["entry_count"] for metric in zone_metrics.values()),
        "total_store_entries": total_store_entries,
        "total_store_exits": total_store_exits,
        "total_exterior_traffic": total_exterior_traffic,
        "total_stair_up": total_stair_up,
        "total_stair_down": total_stair_down,
        "avg_dwell_time": format_seconds(avg_dwell),
        "avg_dwell_time_seconds": round(avg_dwell, 2),
        "dwell_observations": len(dwell_rows),
    }]

    write_csv_file(
        output_dir / analytics_summary_file,
        [
            "video_name",
            "video_path",
            "duration_seconds",
            "duration_formatted",
            "fps",
            "total_frames",
            "frame_width",
            "frame_height",
            "total_people",
            "raw_track_count",
            "confirmed_people_count",
            "rejected_detection_count",
            "avg_visible_people",
            "max_visible_people",
            "total_events",
            "total_zone_entries",
            "total_store_entries",
            "total_store_exits",
            "total_exterior_traffic",
            "total_stair_up",
            "total_stair_down",
            "avg_dwell_time",
            "avg_dwell_time_seconds",
            "dwell_observations",
        ],
        summary_rows,
    )

    person_rows = []
    for person_id in sorted(person_labels.keys()):
        stats = person_stats.get(person_id)
        if stats is None:
            continue
        visible_time = safe_div(stats["visible_frames"], fps)
        avg_speed = safe_div(stats["distance_px"], visible_time)
        person_rows.append({
            "person_id": person_id,
            "person_label": person_labels.get(person_id, f"persona_{person_id}"),
            "raw_track_ids": " | ".join(str(raw_id) for raw_id in sorted(stats["raw_track_ids"])),
            "first_frame": stats["first_frame"],
            "last_frame": stats["last_frame"],
            "first_time_seconds": round(stats["first_time"], 2),
            "last_time_seconds": round(stats["last_time"], 2),
            "visible_time_seconds": round(visible_time, 2),
            "visible_time_formatted": format_seconds(visible_time),
            "visible_frames": stats["visible_frames"],
            "distance_px": round(stats["distance_px"], 2),
            "avg_speed_px_s": round(avg_speed, 2),
            "zones_visited": " | ".join(sorted(stats["zones_visited"])),
            "zones_visited_count": len(stats["zones_visited"]),
            "first_zone": stats.get("first_zone", ""),
            "last_zone": stats.get("last_zone", ""),
        })

    write_csv_file(
        output_dir / person_tracks_file,
        [
            "person_id",
            "person_label",
            "raw_track_ids",
            "first_frame",
            "last_frame",
            "first_time_seconds",
            "last_time_seconds",
            "visible_time_seconds",
            "visible_time_formatted",
            "visible_frames",
            "distance_px",
            "avg_speed_px_s",
            "zones_visited",
            "zones_visited_count",
            "first_zone",
            "last_zone",
        ],
        person_rows,
    )

    zone_rows = []
    for zone_id, metric in zone_metrics.items():
        dwell_list = metric["dwell_times"]
        avg_zone_dwell = safe_div(sum(dwell_list), len(dwell_list)) if dwell_list else 0
        zone_rows.append({
            "zone_id": zone_id,
            "zone_name": metric["zone_name"],
            "zone_type": metric["zone_type"],
            "entry_count": metric["entry_count"],
            "exit_count": metric["exit_count"],
            "unique_people_count": len(metric["unique_people"]),
            "total_dwell_time_seconds": round(sum(dwell_list), 2),
            "avg_dwell_time_seconds": round(avg_zone_dwell, 2),
            "avg_dwell_time_formatted": format_seconds(avg_zone_dwell),
            "max_dwell_time_seconds": round(max(dwell_list), 2) if dwell_list else 0,
            "min_dwell_time_seconds": round(min(dwell_list), 2) if dwell_list else 0,
            "first_activity_time": round(metric["first_activity_time"], 2) if metric["first_activity_time"] is not None else "",
            "last_activity_time": round(metric["last_activity_time"], 2) if metric["last_activity_time"] is not None else "",
            "peak_activity_bin": metric.get("peak_activity_bin", ""),
        })

    write_csv_file(
        output_dir / zone_metrics_file,
        [
            "zone_id",
            "zone_name",
            "zone_type",
            "entry_count",
            "exit_count",
            "unique_people_count",
            "total_dwell_time_seconds",
            "avg_dwell_time_seconds",
            "avg_dwell_time_formatted",
            "max_dwell_time_seconds",
            "min_dwell_time_seconds",
            "first_activity_time",
            "last_activity_time",
            "peak_activity_bin",
        ],
        zone_rows,
    )

    store_rows = []
    for store_name, metric in store_metrics.items():
        dwell_list = metric["dwell_times"]
        avg_store_dwell = safe_div(sum(dwell_list), len(dwell_list)) if dwell_list else 0
        conversion_rate = safe_div(metric["estimated_entries"], metric["exterior_traffic"])
        exit_entry_ratio = safe_div(metric["estimated_exits"], metric["estimated_entries"])
        traffic_score = (
            metric["exterior_traffic"] * 0.4
            + metric["estimated_entries"] * 0.4
            + avg_store_dwell * 0.2
        )
        store_rows.append({
            "store_name": store_name,
            "exterior_traffic": metric["exterior_traffic"],
            "exterior_unique_people": len(metric["exterior_unique_people"]),
            "door_crossings": metric["door_crossings"],
            "estimated_entries": metric["estimated_entries"],
            "estimated_exits": metric["estimated_exits"],
            "estimated_people_inside": metric["estimated_entries"] - metric["estimated_exits"],
            "ignored_exit_events": metric["ignored_exit_events"],
            "dwell_observations": len(dwell_list),
            "avg_dwell_time_seconds": round(avg_store_dwell, 2),
            "avg_dwell_time_formatted": format_seconds(avg_store_dwell),
            "min_dwell_time_seconds": round(min(dwell_list), 2) if dwell_list else 0,
            "max_dwell_time_seconds": round(max(dwell_list), 2) if dwell_list else 0,
            "conversion_rate": round(conversion_rate, 4),
            "exit_entry_ratio": round(exit_entry_ratio, 4),
            "traffic_score": round(traffic_score, 2),
        })

    store_rows = sorted(store_rows, key=lambda row: row["traffic_score"], reverse=True)
    write_csv_file(
        output_dir / store_metrics_file,
        [
            "store_name",
            "exterior_traffic",
            "exterior_unique_people",
            "door_crossings",
            "estimated_entries",
            "estimated_exits",
            "estimated_people_inside",
            "ignored_exit_events",
            "dwell_observations",
            "avg_dwell_time_seconds",
            "avg_dwell_time_formatted",
            "min_dwell_time_seconds",
            "max_dwell_time_seconds",
            "conversion_rate",
            "exit_entry_ratio",
            "traffic_score",
        ],
        store_rows,
    )

    write_csv_file(
        output_dir / dwell_times_file,
        [
            "store_name",
            "entry_time_seconds",
            "exit_time_seconds",
            "dwell_time_seconds",
            "dwell_time_formatted",
            "entry_event_id",
            "exit_event_id",
            "confidence",
        ],
        dwell_rows,
    )

    event_rows = []
    for i, event in enumerate(events, start=1):
        event_row = dict(event)
        event_row["event_id"] = i
        event_rows.append(event_row)

    write_csv_file(
        output_dir / zone_events_file,
        [
            "event_id",
            "timestamp",
            "frame_index",
            "event_type",
            "person_id",
            "person_label",
            "raw_track_id",
            "zone_id",
            "zone_name",
            "zone_type",
            "store_name",
            "x",
            "y",
            "extra",
        ],
        event_rows,
    )

    time_rows = []
    for bin_index in sorted(time_bins.keys()):
        bin_data = time_bins[bin_index]
        visible_avg = safe_div(bin_data["visible_people_sum"], bin_data["visible_samples"])
        start_time = bin_index * time_bin_seconds
        end_time = start_time + time_bin_seconds
        time_rows.append({
            "time_bin": bin_index,
            "start_time_seconds": round(start_time, 2),
            "end_time_seconds": round(end_time, 2),
            "time_label": f"{format_seconds(start_time)} - {format_seconds(end_time)}",
            "visible_people_avg": round(visible_avg, 2),
            "visible_people_max": bin_data["visible_people_max"],
            "unique_people_count": len(bin_data["unique_people"]),
            "zone_entries": bin_data["zone_entries"],
            "store_entries": bin_data["store_entries"],
            "store_exits": bin_data["store_exits"],
            "exterior_traffic": bin_data["exterior_traffic"],
            "stair_up": bin_data["stair_up"],
            "stair_down": bin_data["stair_down"],
            "total_events": bin_data["total_events"],
            "people_count": bin_data["visible_people_max"],
        })

    write_csv_file(
        output_dir / time_bins_file,
        [
            "time_bin",
            "start_time_seconds",
            "end_time_seconds",
            "time_label",
            "visible_people_avg",
            "visible_people_max",
            "unique_people_count",
            "zone_entries",
            "store_entries",
            "store_exits",
            "exterior_traffic",
            "stair_up",
            "stair_down",
            "total_events",
            "people_count",
        ],
        time_rows,
    )

    stair_rows = []
    for stair_id, metric in stair_metrics.items():
        total_usage = metric["up_count"] + metric["down_count"]
        stair_rows.append({
            "stair_id": stair_id,
            "stair_name": metric["stair_name"],
            "up_count": metric["up_count"],
            "down_count": metric["down_count"],
            "total_usage": total_usage,
            "unique_people_count": len(metric["unique_people"]),
            "up_down_ratio": round(safe_div(metric["up_count"], metric["down_count"]), 4),
        })

    write_csv_file(
        output_dir / stair_metrics_file,
        [
            "stair_id",
            "stair_name",
            "up_count",
            "down_count",
            "total_usage",
            "unique_people_count",
            "up_down_ratio",
        ],
        stair_rows,
    )


def update_analysis(analysis_id, **fields):
    fields["updated_at"] = timezone.now()
    AnalysisRun.objects.filter(pk=analysis_id).update(**fields)


def should_cancel(analysis_id):
    return AnalysisRun.objects.filter(pk=analysis_id, status=AnalysisRun.Status.CANCELED).exists()


def fail_analysis(analysis_id, message):
    update_analysis(
        analysis_id,
        status=AnalysisRun.Status.FAILED,
        status_message="Error durante el analisis",
        error_message=str(message),
        finished_at=timezone.now(),
    )


def slot_center(slot):
    return ((slot["x1"] + slot["x2"]) / 2.0, (slot["y1"] + slot["y2"]) / 2.0)


def point_inside_rect(x, y, rect):
    return rect["x1"] <= x <= rect["x2"] and rect["y1"] <= y <= rect["y2"]


def boxes_iou(a, b):
    ax1, ay1, ax2, ay2 = a["x1"], a["y1"], a["x2"], a["y2"]
    bx1, by1, bx2, by2 = b["x1"], b["y1"], b["x2"], b["y2"]
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter = inter_w * inter_h
    if inter <= 0:
        return 0.0
    area_a = max(1.0, (ax2 - ax1) * (ay2 - ay1))
    area_b = max(1.0, (bx2 - bx1) * (by2 - by1))
    return inter / (area_a + area_b - inter)


def dedupe_vehicle_detections(detections):
    ordered = sorted(detections, key=lambda item: item["conf"], reverse=True)
    kept = []
    for det in ordered:
        if any(boxes_iou(det, existing) >= 0.45 for existing in kept):
            continue
        kept.append(det)
    return kept


def parking_zone_slots(zone, sample_box):
    zone_width = max(1, zone["x2"] - zone["x1"])
    zone_height = max(1, zone["y2"] - zone["y1"])
    sample_w = max(24.0, sample_box["w"])
    sample_h = max(24.0, sample_box["h"])
    slot_long = max(sample_w, sample_h) * 1.08
    cols = max(1, int(zone_width // max(slot_long, 1)))
    rows = 1
    effective_slot_w = zone_width / cols
    effective_slot_h = zone_height

    slots = []
    for row in range(rows):
        for col in range(cols):
            x1 = int(zone["x1"] + col * effective_slot_w)
            y1 = int(zone["y1"] + row * effective_slot_h)
            x2 = int(zone["x1"] + (col + 1) * effective_slot_w)
            y2 = int(zone["y1"] + (row + 1) * effective_slot_h)
            slots.append({
                "slot_id": f"{zone['id']}_slot_{row + 1:02d}_{col + 1:02d}",
                "zone_id": zone["id"],
                "zone_name": display_zone_label(zone),
                "row": row + 1,
                "col": col + 1,
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
            })
    return slots


def export_parking_analytics(
    output_dir,
    fps,
    total_frames,
    frame_width,
    frame_height,
    zones,
    slots,
    slot_sessions,
    time_bins,
    peak_occupied_slots,
    unique_vehicles,
):
    output_dir = Path(output_dir)
    total_slots = len(slots)
    arrivals = len(slot_sessions)
    departures = sum(1 for session in slot_sessions if session.get("departed"))
    dwell_seconds = [session["duration_seconds"] for session in slot_sessions if session.get("duration_seconds", 0) > 0]
    avg_dwell = sum(dwell_seconds) / len(dwell_seconds) if dwell_seconds else 0
    occupancy_samples = [row["occupied_slots"] for row in time_bins if row.get("samples")]
    avg_occupied = sum(occupancy_samples) / len(occupancy_samples) if occupancy_samples else 0
    occupancy_rate = (avg_occupied / total_slots * 100) if total_slots else 0
    current_occupied = time_bins[-1]["occupied_slots"] if time_bins else 0
    free_slots = max(total_slots - current_occupied, 0)

    summary_row = {
        "total_people": unique_vehicles,
        "total_zone_entries": arrivals,
        "total_focus_activity": departures,
        "avg_dwell_time": format_seconds(avg_dwell),
        "flow_heatmap_points": int(sum(occupancy_samples)),
        "slots_total": total_slots,
        "slots_free": free_slots,
        "peak_occupied_slots": peak_occupied_slots,
        "avg_occupancy_rate": round(occupancy_rate, 1),
        "avg_dwell_seconds": round(avg_dwell, 1),
    }
    write_csv_file(output_dir / analytics_summary_file, list(summary_row.keys()), [summary_row])
    write_csv_file(output_dir / parking_summary_file, list(summary_row.keys()), [summary_row])

    zone_rows = []
    for zone in zones:
        zone_slots = [slot for slot in slots if slot["zone_id"] == zone["id"]]
        zone_sessions = [session for session in slot_sessions if session["zone_id"] == zone["id"]]
        zone_peak = max((row["occupied_slots"] for row in time_bins if row["zone_id"] == zone["id"]), default=0)
        zone_avg_dwell = sum(session["duration_seconds"] for session in zone_sessions) / len(zone_sessions) if zone_sessions else 0
        zone_rows.append({
            "zone_id": zone["id"],
            "zone_name": display_zone_label(zone),
            "zone_type": zone["type"],
            "entry_count": len(zone_sessions),
            "exit_count": sum(1 for session in zone_sessions if session.get("departed")),
            "unique_people_count": len(zone_sessions),
            "avg_dwell_time_seconds": round(zone_avg_dwell, 1),
            "avg_dwell_time_formatted": format_seconds(zone_avg_dwell),
            "slots_total": len(zone_slots),
            "peak_occupied_slots": zone_peak,
        })
    write_csv_file(output_dir / zone_metrics_file, list(zone_rows[0].keys()) if zone_rows else [
        "zone_id", "zone_name", "zone_type", "entry_count", "exit_count", "unique_people_count", "avg_dwell_time_seconds",
        "avg_dwell_time_formatted", "slots_total", "peak_occupied_slots",
    ], zone_rows)

    slot_rows = []
    for slot in slots:
        sessions = [session for session in slot_sessions if session["slot_id"] == slot["slot_id"]]
        occupied_seconds = sum(session["duration_seconds"] for session in sessions)
        slot_rows.append({
            "slot_id": slot["slot_id"],
            "zone_id": slot["zone_id"],
            "zone_name": slot["zone_name"],
            "row": slot["row"],
            "col": slot["col"],
            "occupied_count": len(sessions),
            "occupied_seconds": round(occupied_seconds, 1),
            "avg_dwell_seconds": round((occupied_seconds / len(sessions)) if sessions else 0, 1),
            "x1": slot["x1"],
            "y1": slot["y1"],
            "x2": slot["x2"],
            "y2": slot["y2"],
        })
    write_csv_file(output_dir / parking_slots_file, list(slot_rows[0].keys()) if slot_rows else [
        "slot_id", "zone_id", "zone_name", "row", "col", "occupied_count", "occupied_seconds", "avg_dwell_seconds", "x1", "y1", "x2", "y2",
    ], slot_rows)

    session_rows = []
    dwell_rows = []
    person_rows = []
    event_rows = []
    for index, session in enumerate(slot_sessions, start=1):
        vehicle_label = f"vehiculo_{index}"
        session_rows.append({
            "vehicle_id": index,
            "vehicle_label": vehicle_label,
            "slot_id": session["slot_id"],
            "zone_id": session["zone_id"],
            "zone_name": session["zone_name"],
            "arrival_seconds": round(session["arrival_seconds"], 2),
            "departure_seconds": round(session["departure_seconds"], 2) if session.get("departure_seconds") is not None else "",
            "duration_seconds": round(session["duration_seconds"], 2),
            "duration_formatted": format_seconds(session["duration_seconds"]),
            "departed": int(bool(session.get("departed"))),
        })
        dwell_rows.append({
            "person_id": index,
            "person_label": vehicle_label,
            "zone_id": session["zone_id"],
            "zone_name": session["zone_name"],
            "duration_seconds": round(session["duration_seconds"], 2),
            "duration_formatted": format_seconds(session["duration_seconds"]),
        })
        person_rows.append({
            "person_id": index,
            "person_label": vehicle_label,
            "first_zone": session["zone_name"],
            "last_zone": session["zone_name"],
            "visible_time_seconds": round(session["duration_seconds"], 2),
            "distance_px": 0,
            "zones_visited": session["zone_name"],
            "zones_visited_count": 1,
        })
        event_rows.append({
            "event_type": "vehicle_arrival",
            "person_id": index,
            "person_label": vehicle_label,
            "time_seconds": round(session["arrival_seconds"], 2),
            "frame_index": session["arrival_frame"],
            "x": session["x"],
            "y": session["y"],
            "zone_id": session["zone_id"],
            "zone_name": session["zone_name"],
            "store_name": "",
            "extra": session["slot_id"],
        })
        if session.get("departure_seconds") is not None:
            event_rows.append({
                "event_type": "vehicle_departure",
                "person_id": index,
                "person_label": vehicle_label,
                "time_seconds": round(session["departure_seconds"], 2),
                "frame_index": session["departure_frame"],
                "x": session["x"],
                "y": session["y"],
                "zone_id": session["zone_id"],
                "zone_name": session["zone_name"],
                "store_name": "",
                "extra": session["slot_id"],
            })

    write_csv_file(output_dir / parking_sessions_file, list(session_rows[0].keys()) if session_rows else [
        "vehicle_id", "vehicle_label", "slot_id", "zone_id", "zone_name", "arrival_seconds", "departure_seconds", "duration_seconds", "duration_formatted", "departed",
    ], session_rows)
    write_csv_file(output_dir / dwell_times_file, list(dwell_rows[0].keys()) if dwell_rows else [
        "person_id", "person_label", "zone_id", "zone_name", "duration_seconds", "duration_formatted",
    ], dwell_rows)
    write_csv_file(output_dir / person_tracks_file, list(person_rows[0].keys()) if person_rows else [
        "person_id", "person_label", "first_zone", "last_zone", "visible_time_seconds", "distance_px", "zones_visited", "zones_visited_count",
    ], person_rows)
    write_csv_file(output_dir / zone_events_file, list(event_rows[0].keys()) if event_rows else [
        "event_type", "person_id", "person_label", "time_seconds", "frame_index", "x", "y", "zone_id", "zone_name", "store_name", "extra",
    ], event_rows)
    write_csv_file(output_dir / store_metrics_file, ["store_name", "exterior_traffic", "door_crossings", "estimated_entries"], [])
    write_csv_file(output_dir / stair_metrics_file, ["stair_id", "stair_name", "up_count", "down_count", "total_usage", "unique_people_count", "up_down_ratio"], [])

    time_rows = []
    for row in time_bins:
        avg_occupied_slots = (row["occupied_sum"] / row["samples"]) if row["samples"] else row["occupied_slots"]
        free_now = max(total_slots - row["occupied_slots"], 0)
        time_rows.append({
            "interval_start_seconds": row["start_seconds"],
            "interval_end_seconds": row["end_seconds"],
            "time_label": f"{format_seconds(row['start_seconds'])} - {format_seconds(row['end_seconds'])}",
            "visible_count": round(avg_occupied_slots, 2),
            "entries": row["arrivals"],
            "events": row["arrivals"] + row["departures"],
            "occupied_slots": row["occupied_slots"],
            "free_slots": free_now,
            "arrivals": row["arrivals"],
            "departures": row["departures"],
        })
    write_csv_file(output_dir / time_bins_file, list(time_rows[0].keys()) if time_rows else [
        "interval_start_seconds", "interval_end_seconds", "time_label", "visible_count", "entries", "events", "occupied_slots", "free_slots", "arrivals", "departures",
    ], time_rows)


def run_parking_analysis_job(analysis, output_dir, vision_utils, YOLO, cv2, np):
    video_path = str(Path(analysis.video.path))
    zones = [
        vision_utils.normalize_zone_geometry(zone.copy(), analysis.frame_width, analysis.frame_height)
        for zone in analysis.zones
    ]
    if not zones:
        fail_analysis(analysis.pk, "Debes configurar al menos una zona de estacionamiento antes de iniciar.")
        return

    with (output_dir / zones_config_file).open("w", encoding="utf-8") as file:
        json.dump({
            "video": video_path,
            "frame_width": analysis.frame_width,
            "frame_height": analysis.frame_height,
            "zones": zones,
        }, file, indent=2, ensure_ascii=False)

    update_analysis(analysis.pk, status_message="Cargando modelo YOLO para vehiculos")
    model = YOLO(parking_model_name)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        fail_analysis(analysis.pk, f"No se pudo abrir el video: {video_path}")
        return

    ok, first_frame = cap.read()
    if not ok:
        cap.release()
        fail_analysis(analysis.pk, "No se pudo leer el primer frame del video.")
        return

    frame_height, frame_width = first_frame.shape[:2]
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    def collect_vehicle_boxes(result, offset_x=0.0, offset_y=0.0):
        detections = []
        if not result or result[0].boxes is None:
            return detections
        for box in result[0].boxes:
            cls_id = int(box.cls[0].item()) if box.cls is not None else -1
            if cls_id not in vehicle_class_ids:
                continue
            x1, y1, x2, y2 = [float(value) for value in box.xyxy[0].tolist()]
            conf_score = float(box.conf[0].item()) if box.conf is not None else 0.0
            detections.append({
                "x1": x1 + offset_x, "y1": y1 + offset_y, "x2": x2 + offset_x, "y2": y2 + offset_y,
                "w": max(1.0, x2 - x1), "h": max(1.0, y2 - y1),
                "cx": (x1 + x2) / 2.0 + offset_x, "cy": (y1 + y2) / 2.0 + offset_y,
                "conf": conf_score,
            })
        return detections

    def enhance_night_frame(frame):
        return cv2.convertScaleAbs(frame, alpha=1.22, beta=12)

    def tiled_vehicle_detections(frame, grid=2):
        detections = []
        fh, fw = frame.shape[:2]
        tile_w = fw // grid
        tile_h = fh // grid
        overlap_x = tile_w // 6
        overlap_y = tile_h // 6
        for gy in range(grid):
            for gx in range(grid):
                x1 = max(0, gx * tile_w - overlap_x)
                y1 = max(0, gy * tile_h - overlap_y)
                x2 = min(fw, (gx + 1) * tile_w + overlap_x)
                y2 = min(fh, (gy + 1) * tile_h + overlap_y)
                tile = frame[y1:y2, x1:x2]
                result = model(tile, verbose=False, conf=max(tracking_confidence, 0.08), iou=iou_value, imgsz=1280)
                detections.extend(collect_vehicle_boxes(result, x1, y1))
        return detections

    def vehicle_detections(frame, detailed=False):
        enhanced = enhance_night_frame(frame)
        detections = collect_vehicle_boxes(
            model(enhanced, verbose=False, conf=max(tracking_confidence, 0.08), iou=iou_value, imgsz=1280)
        )
        if detailed or len(detections) <= 1:
            detections.extend(tiled_vehicle_detections(enhanced, grid=2))
        if detailed and len(detections) <= 2:
            detections.extend(tiled_vehicle_detections(enhanced, grid=4))
        return dedupe_vehicle_detections(detections)

    def draw_vehicle_boxes(frame, detections):
        for det in detections:
            x1, y1, x2, y2 = [int(det[key]) for key in ("x1", "y1", "x2", "y2")]
            cv2.rectangle(frame, (x1, y1), (x2, y2), (92, 255, 160), 2)
            cv2.putText(
                frame,
                f"auto {det['conf']:.2f}",
                (x1, max(20, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                (92, 255, 160),
                2,
            )
        return frame

    initial_detections = vehicle_detections(first_frame, detailed=True)
    slot_specs = []
    for zone in zones:
        inside = [det for det in initial_detections if vision_utils.point_inside_zone(det["cx"], det["cy"], zone)]
        sample = max(inside, key=lambda det: det["conf"], default=None)
        if sample is None:
            zone_w = max(80, zone["x2"] - zone["x1"])
            zone_h = max(80, zone["y2"] - zone["y1"])
            sample = {"w": max(38, zone_w / 6), "h": max(28, zone_h / 2.4)}
        slot_specs.extend(parking_zone_slots(zone, sample))
    if not slot_specs:
        fail_analysis(analysis.pk, "No se pudieron generar slots de estacionamiento a partir de las zonas.")
        return

    slot_state = {
        slot["slot_id"]: {
            "occupied": False,
            "current_session": None,
        }
        for slot in slot_specs
    }
    slot_sessions = []
    heatmap = np.zeros((frame_height, frame_width), dtype=np.float32)
    frame_count = 0
    analyzed_frame_count = 0
    best_frame = None
    best_occupied = -1
    peak_occupied_slots = 0
    preview_path = output_dir / "preview_frame.jpg"
    preview_interval = max(display_every_n_frames * 5, 5)
    preview_max_width = 1440
    processing_started_at = time.perf_counter()
    time_bins = []
    current_bin = None

    def ensure_time_bin(current_time):
        nonlocal current_bin
        bin_start = int(current_time // time_bin_seconds) * time_bin_seconds
        if current_bin is None or current_bin["start_seconds"] != bin_start:
            current_bin = {
                "start_seconds": bin_start,
                "end_seconds": bin_start + time_bin_seconds,
                "occupied_sum": 0.0,
                "occupied_slots": 0,
                "samples": 0,
                "arrivals": 0,
                "departures": 0,
                "zone_id": zones[0]["id"] if zones else "",
            }
            time_bins.append(current_bin)
        return current_bin

    update_analysis(analysis.pk, status_message="Analizando ocupacion de estacionamientos")
    while True:
        if should_cancel(analysis.pk):
            cap.release()
            update_analysis(
                analysis.pk,
                status=AnalysisRun.Status.CANCELED,
                progress=0,
                status_message="Analisis cancelado",
                finished_at=timezone.now(),
            )
            return

        ok, frame = cap.read()
        if not ok:
            break
        frame_count += 1
        should_process = frame_count == 1 or frame_count % max(1, parking_frame_stride) == 0
        if not should_process:
            if total_frames and frame_count % max(1, parking_frame_stride * 2) == 0:
                progress_value = min(94, int((frame_count / max(total_frames, 1)) * 94))
                update_analysis(
                    analysis.pk,
                    progress=progress_value,
                    processed_frames=frame_count,
                    status_message="Muestreando video para ocupacion de estacionamientos",
                )
            continue

        analyzed_frame_count += 1
        current_time = frame_count / fps if fps else 0
        bin_row = ensure_time_bin(current_time)
        detailed_scan = analyzed_frame_count % 12 == 0
        detections = vehicle_detections(frame, detailed=detailed_scan)

        occupied_now = set()
        arrivals = 0
        departures = 0

        draw_vehicle_boxes(frame, detections)

        for slot in slot_specs:
            matching = [det for det in detections if point_inside_rect(det["cx"], det["cy"], slot)]
            state = slot_state[slot["slot_id"]]
            if matching:
                det = max(matching, key=lambda item: item["conf"])
                occupied_now.add(slot["slot_id"])
                if not state["occupied"]:
                    arrivals += 1
                    state["occupied"] = True
                    state["current_session"] = {
                        "slot_id": slot["slot_id"],
                        "zone_id": slot["zone_id"],
                        "zone_name": slot["zone_name"],
                        "arrival_seconds": current_time,
                        "arrival_frame": frame_count,
                        "x": round(det["cx"], 1),
                        "y": round(det["cy"], 1),
                        "departed": False,
                    }
                overlay_color = (96, 165, 250)
                cv2.rectangle(frame, (slot["x1"], slot["y1"]), (slot["x2"], slot["y2"]), overlay_color, 2)
                cv2.rectangle(heatmap, (slot["x1"], slot["y1"]), (slot["x2"], slot["y2"]), 1.0, -1)
            else:
                if state["occupied"] and state["current_session"] is not None:
                    departures += 1
                    session = state["current_session"]
                    session["departure_seconds"] = current_time
                    session["departure_frame"] = frame_count
                    session["duration_seconds"] = max(0, current_time - session["arrival_seconds"])
                    session["departed"] = True
                    slot_sessions.append(session)
                    state["current_session"] = None
                state["occupied"] = False
                cv2.rectangle(frame, (slot["x1"], slot["y1"]), (slot["x2"], slot["y2"]), (80, 88, 105), 1)

        occupied_count = len(occupied_now)
        peak_occupied_slots = max(peak_occupied_slots, occupied_count)
        bin_row["occupied_sum"] += occupied_count
        bin_row["occupied_slots"] = occupied_count
        bin_row["samples"] += 1
        bin_row["arrivals"] += arrivals
        bin_row["departures"] += departures

        for zone in zones:
            cv2.putText(
                frame,
                f"{display_zone_label(zone)} | ocupados {occupied_count}/{len([slot for slot in slot_specs if slot['zone_id'] == zone['id']])}",
                (zone["x1"], max(zone["y1"] - 8, 24)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (96, 165, 250),
                2,
            )
            zone_polygon = np.array([(point["x"], point["y"]) for point in zone.get("points", [])], dtype=np.int32)
            if len(zone_polygon) >= 3:
                cv2.polylines(frame, [zone_polygon], True, (96, 165, 250), 2)

        if best_frame is None or occupied_count > best_occupied:
            best_occupied = occupied_count
            best_frame = frame.copy()

        if frame_count % preview_interval == 0:
            progress = int((frame_count / max(total_frames, 1)) * 100)
            preview_frame = frame
            if frame_width > preview_max_width:
                preview_scale = preview_max_width / frame_width
                preview_frame = cv2.resize(frame, (preview_max_width, int(frame_height * preview_scale)), interpolation=cv2.INTER_AREA)
            elapsed = max(time.perf_counter() - processing_started_at, 0.001)
            analysis_fps = frame_count / elapsed
            cv2.imwrite(str(preview_path), preview_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 72])
            update_analysis(
                analysis.pk,
                progress=min(progress, 99),
                processed_frames=frame_count,
                confirmed_people=len(slot_sessions) + sum(1 for state in slot_state.values() if state["occupied"]),
                status_message=f"Frame {frame_count:,} de {total_frames:,} | {analysis_fps:.1f} fps | slots ocupados {occupied_count}/{len(slot_specs)}",
            )

    cap.release()
    final_time = frame_count / fps if fps else 0
    for state in slot_state.values():
        if state["occupied"] and state["current_session"] is not None:
            session = state["current_session"]
            session["departure_seconds"] = final_time
            session["departure_frame"] = frame_count
            session["duration_seconds"] = max(0, final_time - session["arrival_seconds"])
            session["departed"] = False
            slot_sessions.append(session)

    if best_frame is None:
        fail_analysis(analysis.pk, "No se pudo generar un frame representativo del estacionamiento.")
        return

    update_analysis(analysis.pk, progress=99, status_message="Generando heatmap y reportes de estacionamiento")
    final_image = vision_utils.generate_final_heatmap(best_frame, heatmap, zones, {zone["id"]: peak_occupied_slots for zone in zones})
    cv2.imwrite(str(output_dir / heatmap_output_file), final_image)
    save_zone_report(output_dir, zones, {zone["id"]: peak_occupied_slots for zone in zones})
    export_parking_analytics(
        output_dir=output_dir,
        fps=fps,
        total_frames=frame_count,
        frame_width=frame_width,
        frame_height=frame_height,
        zones=zones,
        slots=slot_specs,
        slot_sessions=slot_sessions,
        time_bins=time_bins,
        peak_occupied_slots=peak_occupied_slots,
        unique_vehicles=len(slot_sessions),
    )
    build_results_database(output_dir, analysis.pk, video_path, zones)
    update_analysis(
        analysis.pk,
        status=AnalysisRun.Status.COMPLETED,
        progress=100,
        processed_frames=frame_count,
        confirmed_people=len(slot_sessions),
        status_message="Analisis de estacionamiento completado",
        finished_at=timezone.now(),
    )


def run_analysis_job(analysis_id):
    analysis = AnalysisRun.objects.get(pk=analysis_id)
    analysis.mark_running()
    output_dir = analysis.output_path
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        import cv2
        import numpy as np
        import vision_utils
        from ultralytics import YOLO
    except ImportError as error:
        fail_analysis(
            analysis_id,
            "Faltan dependencias para ejecutar YOLO. Instala requirements.txt antes de analizar videos.",
        )
        return

    vision_utils.get_zone_label = display_zone_label
    draw_zones_on_frame = vision_utils.draw_zones_on_frame
    generate_final_heatmap = vision_utils.generate_final_heatmap
    point_inside_zone = vision_utils.point_inside_zone
    normalize_zone_geometry = vision_utils.normalize_zone_geometry

    try:
        if analysis.is_parking:
            return run_parking_analysis_job(analysis, output_dir, vision_utils, YOLO, cv2, np)

        video_path = str(Path(analysis.video.path))
        zones = [
            normalize_zone_geometry(zone.copy(), analysis.frame_width, analysis.frame_height)
            for zone in analysis.zones
        ]
        if not zones:
            fail_analysis(analysis_id, "Debes configurar al menos una zona antes de iniciar.")
            return

        with (output_dir / zones_config_file).open("w", encoding="utf-8") as file:
            json.dump({
                "video": video_path,
                "frame_width": analysis.frame_width,
                "frame_height": analysis.frame_height,
                "zones": zones,
            }, file, indent=2, ensure_ascii=False)

        update_analysis(analysis_id, status_message="Cargando modelo YOLO")
        model = YOLO(model_name)

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            fail_analysis(analysis_id, f"No se pudo abrir el video: {video_path}")
            return

        ok, first_frame = cap.read()
        if not ok:
            cap.release()
            fail_analysis(analysis_id, "No se pudo leer el primer frame del video.")
            return

        frame_height, frame_width = first_frame.shape[:2]
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

        dynamic_min_height = max(min_person_height_px, frame_height * 0.035)
        dynamic_min_area = max(min_person_area_px, frame_width * frame_height * 0.00020)

        def valid_person_box(x1, y1, x2, y2):
            w = max(1, x2 - x1)
            h = max(1, y2 - y1)
            area = w * h
            ratio = w / h
            if h < dynamic_min_height:
                return False
            if area < dynamic_min_area:
                return False
            if ratio < min_width_height_ratio or ratio > max_width_height_ratio:
                return False
            return True

        heatmap = np.zeros((frame_height, frame_width), dtype=np.float32)
        person_labels = {}
        next_person_number = 1
        next_person_id = 1
        frame_count = 0
        best_frame = None
        best_score = 0
        zone_by_id = {zone["id"]: zone for zone in zones}
        zone_counts = {zone["id"]: 0 for zone in zones}

        raw_track_to_person = {}
        raw_tracks_seen = set()
        confirmed_people = set()
        rejected_detection_count = 0

        active_zone_state = defaultdict(set)
        pending_zone_starts = {}
        zone_entry_start = {}
        person_stats = {}
        last_seen_data = {}
        processed_inactive_people = set()
        visible_people_samples = []

        zone_metrics = {}
        for zone in zones:
            zone_metrics[zone["id"]] = {
                "zone_id": zone["id"],
                "zone_name": display_zone_label(zone),
                "zone_type": zone["type"],
                "entry_count": 0,
                "exit_count": 0,
                "unique_people": set(),
                "dwell_times": [],
                "first_activity_time": None,
                "last_activity_time": None,
                "peak_activity_bin": "",
            }

        store_metrics = defaultdict(lambda: {
            "exterior_traffic": 0,
            "exterior_unique_people": set(),
            "door_crossings": 0,
            "estimated_entries": 0,
            "estimated_exits": 0,
            "ignored_exit_events": 0,
            "dwell_times": [],
        })
        store_entry_queues = defaultdict(deque)

        stair_metrics = {}
        stair_track_state = {}
        for zone in zones:
            if zone["type"] == "escalera":
                stair_metrics[zone["id"]] = {
                    "stair_name": display_zone_label(zone),
                    "up_count": 0,
                    "down_count": 0,
                    "unique_people": set(),
                }

        events = []
        dwell_rows = []
        time_bins = defaultdict(lambda: {
            "visible_people_sum": 0,
            "visible_samples": 0,
            "visible_people_max": 0,
            "unique_people": set(),
            "zone_entries": 0,
            "store_entries": 0,
            "store_exits": 0,
            "exterior_traffic": 0,
            "stair_up": 0,
            "stair_down": 0,
            "total_events": 0,
        })

        def current_bin_index(current_time):
            return int(current_time // time_bin_seconds)

        def add_event(event_type, person_id, timestamp, frame_index, x, y, zone=None, store_name="", extra="", raw_track_id=""):
            person_label = person_labels.get(person_id, f"persona_{person_id}") if person_id is not None else ""
            event = {
                "timestamp": round(timestamp, 2),
                "frame_index": frame_index,
                "event_type": event_type,
                "person_id": person_id if person_id is not None else "",
                "person_label": person_label,
                "raw_track_id": raw_track_id,
                "zone_id": zone["id"] if zone else "",
                "zone_name": display_zone_label(zone) if zone else "",
                "zone_type": zone["type"] if zone else "",
                "store_name": store_name,
                "x": x,
                "y": y,
                "extra": extra,
            }
            events.append(event)
            time_bins[current_bin_index(timestamp)]["total_events"] += 1
            return len(events)

        def find_reid_person(center_x, center_y, current_time, already_assigned_people):
            best_person_id = None
            best_distance = None
            for person_id in confirmed_people:
                if person_id in already_assigned_people:
                    continue
                last_data = last_seen_data.get(person_id)
                if last_data is None:
                    continue
                time_gap = current_time - last_data["time"]
                if time_gap < 0 or time_gap > reid_max_seconds:
                    continue
                distance = float(np.hypot(center_x - last_data["x"], center_y - last_data["y"]))
                if distance > reid_max_distance_px:
                    continue
                if best_distance is None or distance < best_distance:
                    best_distance = distance
                    best_person_id = person_id
            return best_person_id

        def get_or_create_person_id(raw_track_id, center_x, center_y, current_time, already_assigned_people):
            nonlocal next_person_id
            raw_tracks_seen.add(raw_track_id)
            if raw_track_id in raw_track_to_person:
                return raw_track_to_person[raw_track_id]
            reidentified_person_id = find_reid_person(center_x, center_y, current_time, already_assigned_people)
            if reidentified_person_id is not None:
                raw_track_to_person[raw_track_id] = reidentified_person_id
                person_stats[reidentified_person_id]["raw_track_ids"].add(raw_track_id)
                return reidentified_person_id
            person_id = next_person_id
            next_person_id += 1
            raw_track_to_person[raw_track_id] = person_id
            return person_id

        def ensure_person_stats(person_id, raw_track_id, frame_index, timestamp, center_x, center_y):
            if person_id not in person_stats:
                person_stats[person_id] = {
                    "first_frame": frame_index,
                    "last_frame": frame_index,
                    "first_time": timestamp,
                    "last_time": timestamp,
                    "visible_frames": 0,
                    "distance_px": 0.0,
                    "last_position": None,
                    "zones_visited": set(),
                    "first_zone": "",
                    "last_zone": "",
                    "first_seen_zone_ids": set(),
                    "probable_exit_counted_zones": set(),
                    "raw_track_ids": set(),
                }
            stats = person_stats[person_id]
            stats["raw_track_ids"].add(raw_track_id)
            stats["last_frame"] = frame_index
            stats["last_time"] = timestamp
            stats["visible_frames"] += 1
            if stats["last_position"] is not None:
                lx, ly = stats["last_position"]
                stats["distance_px"] += float(np.hypot(center_x - lx, center_y - ly))
            stats["last_position"] = (center_x, center_y)
            return stats

        def confirm_person_if_ready(person_id, raw_track_id, stats, current_inside_zones, current_time, frame_index, center_x, center_y):
            nonlocal next_person_number
            if person_id in confirmed_people:
                return True
            if stats["visible_frames"] < min_confirmed_frames:
                return False
            confirmed_people.add(person_id)
            person_labels[person_id] = f"persona_{next_person_number}"
            next_person_number += 1
            stats["first_seen_zone_ids"] = set(current_inside_zones)
            add_event("person_first_seen", person_id, current_time, frame_index, center_x, center_y, raw_track_id=raw_track_id)
            return True

        def register_store_entry(store_name, timestamp, frame_index, person_id, x, y, zone):
            metric = store_metrics[store_name]
            metric["estimated_entries"] += 1
            event_id = add_event("store_entry", person_id, timestamp, frame_index, x, y, zone, store_name, "probable_entry_by_disappearance")
            store_entry_queues[store_name].append({"entry_time": timestamp, "entry_event_id": event_id})
            time_bins[current_bin_index(timestamp)]["store_entries"] += 1

        def register_store_exit(store_name, timestamp, frame_index, person_id, x, y, zone):
            metric = store_metrics[store_name]
            metric["estimated_exits"] += 1
            exit_event_id = add_event("store_exit", person_id, timestamp, frame_index, x, y, zone, store_name, "probable_exit_by_door_to_outside")
            time_bins[current_bin_index(timestamp)]["store_exits"] += 1
            if store_entry_queues[store_name]:
                entry_data = store_entry_queues[store_name].popleft()
                dwell_time = max(0, timestamp - entry_data["entry_time"])
                metric["dwell_times"].append(dwell_time)
                dwell_rows.append({
                    "store_name": store_name,
                    "entry_time_seconds": round(entry_data["entry_time"], 2),
                    "exit_time_seconds": round(timestamp, 2),
                    "dwell_time_seconds": round(dwell_time, 2),
                    "dwell_time_formatted": format_seconds(dwell_time),
                    "entry_event_id": entry_data["entry_event_id"],
                    "exit_event_id": exit_event_id,
                    "confidence": "estimated_fifo",
                })
            else:
                metric["ignored_exit_events"] += 1

        def register_zone_enter(person_id, raw_track_id, zone_id, current_time, frame_index, center_x, center_y):
            zone = zone_by_id[zone_id]
            zone_counts[zone_id] += 1
            metric = zone_metrics[zone_id]
            metric["entry_count"] += 1
            metric["unique_people"].add(person_id)
            metric["first_activity_time"] = current_time if metric["first_activity_time"] is None else metric["first_activity_time"]
            metric["last_activity_time"] = current_time
            bin_index = current_bin_index(current_time)
            metric["peak_activity_bin"] = f"{format_seconds(bin_index * time_bin_seconds)} - {format_seconds((bin_index + 1) * time_bin_seconds)}"
            zone_entry_start[(person_id, zone_id)] = current_time
            time_bins[bin_index]["zone_entries"] += 1

            zone_name = display_zone_label(zone)
            stats = person_stats[person_id]
            stats["zones_visited"].add(zone_name)
            if not stats["first_zone"]:
                stats["first_zone"] = zone_name
            stats["last_zone"] = zone_name

            if zone["type"] == "frente_tienda":
                store_name = get_store_name_from_zone(zone)
                store_metrics[store_name]["exterior_traffic"] += 1
                store_metrics[store_name]["exterior_unique_people"].add(person_id)
                time_bins[bin_index]["exterior_traffic"] += 1
                add_event("exterior_traffic", person_id, current_time, frame_index, center_x, center_y, zone, store_name, raw_track_id=raw_track_id)
            elif zone["type"] == "puerta":
                store_name = get_store_name_from_zone(zone)
                store_metrics[store_name]["door_crossings"] += 1
                add_event("door_crossing", person_id, current_time, frame_index, center_x, center_y, zone, store_name, raw_track_id=raw_track_id)
            elif zone["type"] == "escalera":
                stair_track_state[(person_id, zone_id)] = {"start_y": center_y, "start_time": current_time}
                stair_metrics.setdefault(zone_id, {
                    "stair_name": display_zone_label(zone),
                    "up_count": 0,
                    "down_count": 0,
                    "unique_people": set(),
                })
                stair_metrics[zone_id]["unique_people"].add(person_id)
            add_event("zone_enter", person_id, current_time, frame_index, center_x, center_y, zone, raw_track_id=raw_track_id)

        def register_zone_exit(person_id, raw_track_id, zone_id, current_time, frame_index, center_x, center_y):
            zone = zone_by_id[zone_id]
            metric = zone_metrics[zone_id]
            metric["exit_count"] += 1
            metric["last_activity_time"] = current_time
            start_key = (person_id, zone_id)
            if start_key in zone_entry_start:
                zone_dwell = max(0, current_time - zone_entry_start.pop(start_key))
                metric["dwell_times"].append(zone_dwell)
            stats = person_stats[person_id]
            if zone["type"] == "puerta":
                store_name = get_store_name_from_zone(zone)
                first_seen_in_this_door = zone_id in stats.get("first_seen_zone_ids", set())
                not_counted_before = zone_id not in stats.get("probable_exit_counted_zones", set())
                if first_seen_in_this_door and not_counted_before:
                    register_store_exit(store_name, current_time, frame_index, person_id, center_x, center_y, zone)
                    stats["probable_exit_counted_zones"].add(zone_id)

            if zone["type"] == "escalera":
                stair_key = (person_id, zone_id)
                stair_start = stair_track_state.pop(stair_key, None)
                if stair_start is not None:
                    delta_y = center_y - stair_start["start_y"]
                    bin_index = current_bin_index(current_time)
                    if delta_y < -stair_direction_threshold_px:
                        stair_metrics[zone_id]["up_count"] += 1
                        time_bins[bin_index]["stair_up"] += 1
                        add_event("stair_up", person_id, current_time, frame_index, center_x, center_y, zone, raw_track_id=raw_track_id)
                    elif delta_y > stair_direction_threshold_px:
                        stair_metrics[zone_id]["down_count"] += 1
                        time_bins[bin_index]["stair_down"] += 1
                        add_event("stair_down", person_id, current_time, frame_index, center_x, center_y, zone, raw_track_id=raw_track_id)
            add_event("zone_exit", person_id, current_time, frame_index, center_x, center_y, zone, raw_track_id=raw_track_id)

        update_analysis(analysis_id, status_message="Analizando video con filtros estadisticos")
        preview_path = output_dir / "preview_frame.jpg"
        preview_interval = max(display_every_n_frames * 6, 12)
        preview_max_width = 1280
        processing_started_at = time.perf_counter()

        while True:
            if should_cancel(analysis_id):
                cap.release()
                update_analysis(
                    analysis_id,
                    status=AnalysisRun.Status.CANCELED,
                    status_message="Analisis cancelado",
                    finished_at=timezone.now(),
                )
                return

            ret, frame = cap.read()
            if not ret:
                break

            frame_count += 1
            current_time = frame_count / fps
            bin_index = current_bin_index(current_time)
            visible_confirmed_people = set()
            already_assigned_people = set()

            results = model.track(
                frame,
                persist=True,
                tracker=tracker_type,
                classes=[0],
                conf=tracking_confidence,
                iou=iou_value,
                verbose=False,
            )

            if results[0].boxes.id is not None:
                boxes = results[0].boxes.xyxy.cpu().numpy()
                raw_track_ids = results[0].boxes.id.cpu().numpy().astype(int)
                for box, raw_track_id in zip(boxes, raw_track_ids):
                    raw_track_id = int(raw_track_id)
                    x1, y1, x2, y2 = map(int, box)
                    if not valid_person_box(x1, y1, x2, y2):
                        rejected_detection_count += 1
                        continue
                    center_x = int((x1 + x2) / 2)
                    center_y = int((y1 + y2) / 2)
                    center_x = int(np.clip(center_x, 0, frame_width - 1))
                    center_y = int(np.clip(center_y, 0, frame_height - 1))
                    person_id = get_or_create_person_id(raw_track_id, center_x, center_y, current_time, already_assigned_people)
                    already_assigned_people.add(person_id)
                    stats = ensure_person_stats(person_id, raw_track_id, frame_count, current_time, center_x, center_y)
                    current_inside_zones = {
                        zone["id"]
                        for zone in zones
                        if point_inside_zone(center_x, center_y, zone)
                    }
                    is_confirmed = confirm_person_if_ready(
                        person_id,
                        raw_track_id,
                        stats,
                        current_inside_zones,
                        current_time,
                        frame_count,
                        center_x,
                        center_y,
                    )
                    if not is_confirmed:
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (160, 160, 160), 1)
                        cv2.putText(
                            frame,
                            "validando",
                            (x1, max(y1 - 10, 20)),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.55,
                            (160, 160, 160),
                            1,
                        )
                        continue
                    visible_confirmed_people.add(person_id)
                    processed_inactive_people.discard(person_id)
                    heatmap[center_y, center_x] += 1
                    active_zones = active_zone_state[person_id]

                    for zone_id in current_inside_zones:
                        if zone_id in active_zones:
                            continue
                        pending_key = (person_id, zone_id)
                        if pending_key not in pending_zone_starts:
                            pending_zone_starts[pending_key] = current_time
                        elif current_time - pending_zone_starts[pending_key] >= min_zone_presence_seconds:
                            active_zones.add(zone_id)
                            pending_zone_starts.pop(pending_key, None)
                            register_zone_enter(person_id, raw_track_id, zone_id, current_time, frame_count, center_x, center_y)

                    for zone_id in list(active_zones):
                        if zone_id not in current_inside_zones:
                            active_zones.remove(zone_id)
                            pending_zone_starts.pop((person_id, zone_id), None)
                            register_zone_exit(person_id, raw_track_id, zone_id, current_time, frame_count, center_x, center_y)

                    for pending_key in list(pending_zone_starts.keys()):
                        pending_person_id, pending_zone_id = pending_key
                        if pending_person_id == person_id and pending_zone_id not in current_inside_zones:
                            pending_zone_starts.pop(pending_key, None)

                    last_seen_data[person_id] = {
                        "time": current_time,
                        "frame": frame_count,
                        "x": center_x,
                        "y": center_y,
                        "active_zones": set(active_zone_state[person_id]),
                    }
                    label = person_labels[person_id]
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (235, 99, 37), 2)
                    cv2.putText(
                        frame,
                        label,
                        (x1, max(y1 - 10, 20)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.65,
                        (235, 99, 37),
                        2,
                    )
                    cv2.circle(frame, (center_x, center_y), 4, (214, 255, 114), -1)

            for person_id, last_data in list(last_seen_data.items()):
                if person_id in visible_confirmed_people or person_id in processed_inactive_people:
                    continue
                if current_time - last_data["time"] < entry_disappear_seconds:
                    continue
                processed_inactive_people.add(person_id)
                add_event("person_last_seen", person_id, last_data["time"], last_data["frame"], last_data["x"], last_data["y"])
                for zone_id in last_data["active_zones"]:
                    zone = zone_by_id.get(zone_id)
                    if zone is not None and zone["type"] == "puerta":
                        register_store_entry(
                            get_store_name_from_zone(zone),
                            last_data["time"],
                            last_data["frame"],
                            person_id,
                            last_data["x"],
                            last_data["y"],
                            zone,
                        )

            draw_zones_on_frame(frame, zones, zone_counts, alpha=0.12)
            current_people = len(visible_confirmed_people)
            time_bins[bin_index]["visible_people_sum"] += current_people
            time_bins[bin_index]["visible_samples"] += 1
            time_bins[bin_index]["visible_people_max"] = max(time_bins[bin_index]["visible_people_max"], current_people)
            for person_id in visible_confirmed_people:
                time_bins[bin_index]["unique_people"].add(person_id)
            visible_people_samples.append({"frame": frame_count, "timestamp": current_time, "visible_people": current_people})

            score = current_people + np.max(heatmap) * 0.05
            if best_frame is None or score > best_score:
                best_score = score
                best_frame = frame.copy()

            if frame_count % preview_interval == 0:
                progress = int((frame_count / max(total_frames, 1)) * 100)
                preview_frame = frame
                if frame_width > preview_max_width:
                    preview_scale = preview_max_width / frame_width
                    preview_frame = cv2.resize(
                        frame,
                        (preview_max_width, int(frame_height * preview_scale)),
                        interpolation=cv2.INTER_AREA,
                    )
                elapsed = max(time.perf_counter() - processing_started_at, 0.001)
                analysis_fps = frame_count / elapsed
                cv2.imwrite(str(preview_path), preview_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 72])
                update_analysis(
                    analysis_id,
                    progress=min(progress, 99),
                    processed_frames=frame_count,
                    confirmed_people=len(person_labels),
                    status_message=f"Frame {frame_count:,} de {total_frames:,} | {analysis_fps:.1f} fps",
                )

        cap.release()

        for person_id, last_data in list(last_seen_data.items()):
            if person_id not in processed_inactive_people:
                processed_inactive_people.add(person_id)
                add_event("person_last_seen", person_id, last_data["time"], last_data["frame"], last_data["x"], last_data["y"])
                for zone_id in last_data["active_zones"]:
                    zone = zone_by_id.get(zone_id)
                    if zone is not None and zone["type"] == "puerta":
                        register_store_entry(
                            get_store_name_from_zone(zone),
                            last_data["time"],
                            last_data["frame"],
                            person_id,
                            last_data["x"],
                            last_data["y"],
                            zone,
                        )

        if best_frame is None:
            fail_analysis(analysis_id, "No se pudo generar un frame representativo.")
            return

        update_analysis(analysis_id, progress=99, status_message="Generando heatmap y reportes")
        final_image = generate_final_heatmap(best_frame, heatmap, zones, zone_counts)
        cv2.imwrite(str(output_dir / heatmap_output_file), final_image)
        save_zone_report(output_dir, zones, zone_counts)
        export_professional_analytics(
            output_dir=output_dir,
            video_path=video_path,
            fps=fps,
            total_frames=frame_count,
            frame_width=frame_width,
            frame_height=frame_height,
            person_labels=person_labels,
            person_stats=person_stats,
            zone_metrics=zone_metrics,
            store_metrics=store_metrics,
            stair_metrics=stair_metrics,
            events=events,
            dwell_rows=dwell_rows,
            time_bins=time_bins,
            visible_people_samples=visible_people_samples,
            rejected_detection_count=rejected_detection_count,
            raw_track_count=len(raw_tracks_seen),
            confirmed_people_count=len(confirmed_people),
        )
        build_results_database(output_dir, analysis_id, video_path, zones)

        update_analysis(
            analysis_id,
            status=AnalysisRun.Status.COMPLETED,
            progress=100,
            processed_frames=frame_count,
            confirmed_people=len(person_labels),
            status_message="Analisis completado",
            finished_at=timezone.now(),
        )

    except Exception as error:
        fail_analysis(analysis_id, error)
