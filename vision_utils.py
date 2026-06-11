import os
import json
import csv
import cv2
import numpy as np

from config import (
    ZONE_STYLES,
    zones_file,
    zone_report_file,
    heatmap_percentile,
    min_visible_percent,
    video_path
)


def load_existing_zones(frame_width, frame_height):
    if not os.path.exists(zones_file):
        return []

    try:
        with open(zones_file, "r", encoding="utf-8") as file:
            data = json.load(file)

        zones = data.get("zones", [])
        valid_zones = []

        for zone in zones:
            if "id" in zone and "type" in zone:
                valid_zones.append(normalize_zone_geometry(zone, frame_width, frame_height))

        return valid_zones

    except Exception as error:
        print(f"No se pudieron cargar zonas existentes: {error}")
        return []


def save_zones(zones, frame_width, frame_height):
    data = {
        "video": video_path,
        "frame_width": frame_width,
        "frame_height": frame_height,
        "zones": zones
    }

    with open(zones_file, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)

    print(f"Zonas guardadas en: {zones_file}")


def get_zone_label(zone):
    zone_type = zone["type"]
    base_label = ZONE_STYLES.get(zone_type, {}).get("label", zone_type.upper())
    return f"{base_label} {zone['id']}"


def rectangle_points(zone):
    x1, y1 = int(zone.get("x1", 0)), int(zone.get("y1", 0))
    x2, y2 = int(zone.get("x2", 0)), int(zone.get("y2", 0))
    left, right = sorted([x1, x2])
    top, bottom = sorted([y1, y2])
    return [
        {"x": left, "y": top},
        {"x": right, "y": top},
        {"x": right, "y": bottom},
        {"x": left, "y": bottom},
    ]


def zone_points(zone):
    raw_points = zone.get("points")
    if isinstance(raw_points, list) and len(raw_points) >= 4:
        try:
            return [(int(point["x"]), int(point["y"])) for point in raw_points[:4]]
        except (KeyError, TypeError, ValueError):
            return [(point["x"], point["y"]) for point in rectangle_points(zone)]
    return [(point["x"], point["y"]) for point in rectangle_points(zone)]


def normalize_zone_geometry(zone, frame_width, frame_height):
    points = []
    for x, y in zone_points(zone):
        points.append({
            "x": int(np.clip(x, 0, frame_width - 1)),
            "y": int(np.clip(y, 0, frame_height - 1)),
        })

    xs = [point["x"] for point in points]
    ys = [point["y"] for point in points]
    zone["points"] = points
    zone["x1"] = min(xs)
    zone["y1"] = min(ys)
    zone["x2"] = max(xs)
    zone["y2"] = max(ys)
    return zone


def zone_polygon(zone):
    return np.array(zone_points(zone), dtype=np.int32)


def point_inside_zone(x, y, zone):
    polygon = zone_polygon(zone)
    if len(polygon) < 3:
        return False
    return cv2.pointPolygonTest(polygon, (float(x), float(y)), False) >= 0


def draw_zones_on_frame(frame, zones, zone_counts=None, alpha=0.12):
    if zone_counts is None:
        zone_counts = {}

    overlay = frame.copy()

    for zone in zones:
        color = ZONE_STYLES.get(zone["type"], {"bgr": (255, 255, 255)})["bgr"]
        polygon = zone_polygon(zone)
        cv2.fillPoly(overlay, [polygon], color)

    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)

    for zone in zones:
        color = ZONE_STYLES.get(zone["type"], {"bgr": (255, 255, 255)})["bgr"]
        polygon = zone_polygon(zone)
        min_x = int(np.min(polygon[:, 0]))
        min_y = int(np.min(polygon[:, 1]))

        entries = zone_counts.get(zone["id"], 0)
        label = f"{get_zone_label(zone)} | entradas: {entries}"

        cv2.polylines(frame, [polygon], True, color, 2)

        cv2.putText(
            frame,
            label,
            (min_x, max(min_y - 8, 22)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2
        )

    return frame


def save_zone_report(zones, zone_counts):
    with open(zone_report_file, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)

        writer.writerow([
            "zone_id",
            "zone_type",
            "points_json",
            "x1",
            "y1",
            "x2",
            "y2",
            "entry_count"
        ])

        for zone in zones:
            writer.writerow([
                zone["id"],
                zone["type"],
                json.dumps(zone_points(zone), ensure_ascii=False),
                zone["x1"],
                zone["y1"],
                zone["x2"],
                zone["y2"],
                zone_counts.get(zone["id"], 0)
            ])

    print(f"Reporte de zonas guardado en: {zone_report_file}")


def create_professional_scale(height):
    scale_width = 240
    margin_top = 80
    margin_bottom = 80
    bar_x1 = 45
    bar_x2 = 88

    scale = np.zeros((height, scale_width, 3), dtype=np.uint8)
    scale[:] = (25, 25, 25)

    bar_height = height - margin_top - margin_bottom

    gradient = np.linspace(255, 0, bar_height).astype(np.uint8)
    gradient = np.tile(gradient, (bar_x2 - bar_x1, 1)).T

    gradient_color = cv2.applyColorMap(
        gradient,
        cv2.COLORMAP_JET
    )

    scale[margin_top:margin_top + bar_height, bar_x1:bar_x2] = gradient_color

    font = cv2.FONT_HERSHEY_SIMPLEX

    cv2.putText(scale, "TRAFFIC", (25, 32), font, 0.72, (255, 255, 255), 2)
    cv2.putText(scale, "DENSITY (%)", (25, 60), font, 0.52, (210, 210, 210), 1)

    tick_values = [0, 20, 40, 60, 80, 100]

    for value in tick_values:
        y = int(margin_top + bar_height - (value / 100) * bar_height)

        cv2.line(
            scale,
            (bar_x2 + 6, y),
            (bar_x2 + 28, y),
            (255, 255, 255),
            1
        )

        cv2.putText(
            scale,
            f"{value}%",
            (bar_x2 + 38, y + 6),
            font,
            0.5,
            (255, 255, 255),
            1
        )

    cv2.putText(scale, "Relative scale", (25, height - 48), font, 0.43, (185, 185, 185), 1)
    cv2.putText(scale, "100% = peak zone", (25, height - 25), font, 0.43, (185, 185, 185), 1)

    return scale


def generate_final_heatmap(best_frame, heatmap, zones, zone_counts):
    height = best_frame.shape[0]

    heatmap_blur = cv2.GaussianBlur(
        heatmap,
        (151, 151),
        0
    )

    heatmap_log = np.log1p(heatmap_blur)

    max_value = np.percentile(
        heatmap_log,
        heatmap_percentile
    )

    if max_value <= 0:
        max_value = 1

    heatmap_percent = np.clip(
        (heatmap_log / max_value) * 100,
        0,
        100
    )

    heatmap_norm = np.clip(
        (heatmap_percent / 100) * 255,
        0,
        255
    ).astype(np.uint8)

    heatmap_color = cv2.applyColorMap(
        heatmap_norm,
        cv2.COLORMAP_JET
    )

    alpha_map = np.clip(
        (heatmap_percent - min_visible_percent) / (100 - min_visible_percent),
        0,
        1
    )

    alpha_map = alpha_map * 0.65
    alpha_map = alpha_map[:, :, None]

    overlay = (
        best_frame.astype(np.float32) * (1 - alpha_map) +
        heatmap_color.astype(np.float32) * alpha_map
    ).astype(np.uint8)

    draw_zones_on_frame(
        overlay,
        zones,
        zone_counts,
        alpha=0.08
    )

    scale = create_professional_scale(height)
    final_image = np.hstack((overlay, scale))

    return final_image
