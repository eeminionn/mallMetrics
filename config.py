# ============================================================
# CONFIGURACIÓN GENERAL DEL PROYECTO
# ============================================================

video_path = "video.mp4"

model_name = "yolo11n.pt"
parking_model_name = "yolo11x.pt"
tracker_type = "bytetrack.yaml"

confidence = 0.25
parking_confidence = 0.18
iou_value = 0.7

# Más alto = menos rojo en el heatmap
heatmap_percentile = 99.7

# Desde qué porcentaje empieza a mostrarse visualmente el heatmap
min_visible_percent = 6

zones_file = "zonas_configuradas.json"
zone_report_file = "reporte_zonas.csv"
heatmap_output_file = "heatmap_final.png"
database_file = "usuarios.db"

# Cada cuántos frames se actualiza la vista en la interfaz
display_every_n_frames = 2

# En estacionamientos no hace falta analizar cada frame para medir ocupacion.
parking_frame_stride = 4

# Cantidad de frames procesados consecutivos sin deteccion antes de cerrar una sesion.
parking_slot_miss_tolerance = 3

# Si el mismo slot recupera deteccion rapidamente, se considera la misma sesion.
parking_slot_reconnect_seconds = 10


# ============================================================
# COLORES DE INTERFAZ
# ============================================================

APP_BG = "#0B0F19"
SIDEBAR_BG = "#101827"
PANEL_BG = "#121826"
CARD_BG = "#151C2C"
CARD_BG_2 = "#1A2435"
TEXT_MAIN = "#FFFFFF"
TEXT_MUTED = "#AAB2C0"
BLUE = "#2F80ED"


# ============================================================
# ESTILOS DE ZONAS
# ============================================================

ZONE_STYLES = {
    "puerta": {
        "label": "PUERTA",
        "bgr": (0, 180, 255),
        "hex": "#FFB000"
    },
    "escalera": {
        "label": "ESCALERA",
        "bgr": (255, 0, 255),
        "hex": "#FF4DFF"
    },
    "salida": {
        "label": "SALIDA",
        "bgr": (0, 0, 255),
        "hex": "#FF3B30"
    },
    "zona": {
        "label": "ZONA",
        "bgr": (255, 255, 0),
        "hex": "#00D1FF"
    },
    "estacionamiento": {
        "label": "ESTACIONAMIENTO",
        "bgr": (255, 120, 0),
        "hex": "#60A5FA"
    }
}
