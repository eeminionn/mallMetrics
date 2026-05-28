import os
import threading
import queue
import csv
import tkinter as tk
from tkinter import messagebox, filedialog, simpledialog
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageTk
import customtkinter as ctk
from ultralytics import YOLO

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except Exception:
    DND_FILES = None
    TkinterDnD = None
    DND_AVAILABLE = False

import config
import vision_utils

from config import (
    video_path as DEFAULT_VIDEO_PATH,
    model_name,
    tracker_type,
    confidence,
    iou_value,
    display_every_n_frames,
    heatmap_output_file,
    zone_report_file,
    APP_BG,
    SIDEBAR_BG,
    PANEL_BG,
    CARD_BG,
    CARD_BG_2,
    TEXT_MAIN,
    TEXT_MUTED,
    BLUE,
    ZONE_STYLES,
)
from database import init_database, authenticate_user
from vision_utils import (
    load_existing_zones,
    save_zones,
    get_zone_label as base_get_zone_label,
    point_inside_zone,
    draw_zones_on_frame,
    generate_final_heatmap,
)
from results_view import ResultsView

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}


def display_zone_label(zone):
    custom_name = str(zone.get("name", "")).strip()
    if custom_name:
        return custom_name
    return base_get_zone_label(zone)


# Esto hace que draw_zones_on_frame(), que vive dentro de vision_utils.py,
# también use los nombres personalizados de las zonas.
vision_utils.get_zone_label = display_zone_label


def save_zone_report(zones, zone_counts):
    with open(zone_report_file, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow([
            "zone_id",
            "zone_name",
            "zone_type",
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
                zone["x1"],
                zone["y1"],
                zone["x2"],
                zone["y2"],
                zone_counts.get(zone["id"], 0),
            ])

    print(f"Reporte de zonas guardado en: {zone_report_file}")


if DND_AVAILABLE:
    class BaseApp(ctk.CTk, TkinterDnD.DnDWrapper):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.TkdndVersion = TkinterDnD._require(self)
else:
    BaseApp = ctk.CTk


class RetailAnalyticsApp(BaseApp):
    def __init__(self):
        super().__init__()

        self.title("Retail Vision Analytics")
        self.geometry("1280x780")
        self.minsize(950, 620)
        self.configure(fg_color=APP_BG)

        try:
            self.state("zoomed")
        except Exception:
            pass

        self.fullscreen = False
        self.current_user = None
        self.current_role = None
        self.current_video_path = DEFAULT_VIDEO_PATH

        self.bind("<F11>", self.toggle_fullscreen)
        self.bind("<Escape>", self.exit_fullscreen)

        # Editor de zonas
        self.zone_first_frame = None
        self.zone_frame_width = 0
        self.zone_frame_height = 0
        self.zone_canvas = None
        self.zone_photo = None
        self.zone_scale = 1
        self.zone_offset_x = 0
        self.zone_offset_y = 0
        self.zone_display_width = 0
        self.zone_display_height = 0
        self.zone_current_type = "puerta"
        self.zone_buttons = {}
        self.zones = []
        self.zone_drawing = False
        self.zone_start_canvas = None
        self.zone_temp_canvas = None
        self.zone_counter_label = None

        # Selector de video
        self.video_path_label = None
        self.video_status_label = None

        # Análisis
        self.analysis_queue = None
        self.analysis_stop_event = None
        self.analysis_thread = None
        self.analysis_running = False
        self.analysis_canvas = None
        self.analysis_photo = None
        self.analysis_current_frame = None
        self.analysis_status_label = None
        self.analysis_progress = None
        self.analysis_frame_label = None
        self.analysis_people_label = None
        self.analysis_zone_label = None
        self.analysis_results_button = None
        self.analysis_zones = []

        self.show_login()

    # ============================================================
    # CONTROL GENERAL
    # ============================================================

    def toggle_fullscreen(self, event=None):
        self.fullscreen = not self.fullscreen
        self.attributes("-fullscreen", self.fullscreen)

    def exit_fullscreen(self, event=None):
        self.fullscreen = False
        self.attributes("-fullscreen", False)

    def clear_window(self):
        for widget in self.winfo_children():
            widget.destroy()

    def stop_analysis_if_running(self):
        if self.analysis_running and self.analysis_stop_event is not None:
            self.analysis_stop_event.set()
            self.analysis_running = False

    # ============================================================
    # LOGIN
    # ============================================================

    def show_login(self):
        self.stop_analysis_if_running()
        self.clear_window()
        self.unbind("<Return>")

        main = ctk.CTkFrame(self, fg_color=APP_BG)
        main.pack(fill="both", expand=True)
        main.grid_columnconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=0)
        main.grid_rowconfigure(0, weight=1)

        left_panel = ctk.CTkFrame(main, fg_color=SIDEBAR_BG, corner_radius=0)
        left_panel.grid(row=0, column=0, sticky="nsew")

        right_panel = ctk.CTkFrame(main, width=460, fg_color=CARD_BG, corner_radius=0)
        right_panel.grid(row=0, column=1, sticky="ns")
        right_panel.grid_propagate(False)

        title = ctk.CTkLabel(
            left_panel,
            text="Retail Vision\nAnalytics",
            font=("Segoe UI", 56, "bold"),
            text_color=TEXT_MAIN,
            justify="left",
        )
        title.pack(anchor="w", padx=86, pady=(120, 10))

        subtitle = ctk.CTkLabel(
            left_panel,
            text="Sistema de análisis de flujo peatonal, zonas de interés,\nmapas de calor y comportamiento en centros comerciales.",
            font=("Segoe UI", 19),
            text_color=TEXT_MUTED,
            justify="left",
        )
        subtitle.pack(anchor="w", padx=90, pady=(8, 34))

        feature_box = ctk.CTkFrame(left_panel, fg_color=CARD_BG_2, corner_radius=24)
        feature_box.pack(anchor="w", padx=90, pady=18)

        features = [
            "Detección y seguimiento de personas con YOLO",
            "Demarcación de puertas, salidas, escaleras y zonas",
            "Mapa de calor dinámico de tránsito peatonal",
            "Base preparada para métricas por tienda",
        ]

        for feature in features:
            label = ctk.CTkLabel(
                feature_box,
                text=f"✓ {feature}",
                font=("Segoe UI", 16),
                text_color="#DDE6F3",
            )
            label.pack(anchor="w", padx=28, pady=8)

        login_title = ctk.CTkLabel(
            right_panel,
            text="Iniciar sesión",
            font=("Segoe UI", 31, "bold"),
            text_color=TEXT_MAIN,
        )
        login_title.pack(anchor="w", padx=44, pady=(120, 8))

        login_subtitle = ctk.CTkLabel(
            right_panel,
            text="Ingresa tus credenciales para continuar.",
            font=("Segoe UI", 14),
            text_color=TEXT_MUTED,
        )
        login_subtitle.pack(anchor="w", padx=44, pady=(0, 34))

        self.username_entry = ctk.CTkEntry(
            right_panel,
            height=50,
            corner_radius=14,
            placeholder_text="Usuario",
            font=("Segoe UI", 15),
            fg_color="#202838",
            border_color="#30384A",
        )
        self.username_entry.pack(fill="x", padx=44, pady=8)

        self.password_entry = ctk.CTkEntry(
            right_panel,
            height=50,
            corner_radius=14,
            placeholder_text="Contraseña",
            show="*",
            font=("Segoe UI", 15),
            fg_color="#202838",
            border_color="#30384A",
        )
        self.password_entry.pack(fill="x", padx=44, pady=8)

        self.login_message = ctk.CTkLabel(
            right_panel,
            text="",
            font=("Segoe UI", 13),
            text_color="#FF6B6B",
        )
        self.login_message.pack(anchor="w", padx=46, pady=(6, 10))

        login_button = ctk.CTkButton(
            right_panel,
            text="Entrar al sistema",
            height=52,
            corner_radius=16,
            font=("Segoe UI", 16, "bold"),
            fg_color=BLUE,
            hover_color="#1F6FDB",
            command=self.login,
        )
        login_button.pack(fill="x", padx=44, pady=(8, 18))

        helper = ctk.CTkLabel(
            right_panel,
            text="Usuario demo: admin\nContraseña demo: admin",
            font=("Segoe UI", 13),
            text_color="#7D8797",
            justify="left",
        )
        helper.pack(anchor="w", padx=46, pady=(8, 0))

        hint = ctk.CTkLabel(
            right_panel,
            text="F11 = pantalla completa | ESC = salir",
            font=("Segoe UI", 12),
            text_color="#687385",
        )
        hint.pack(side="bottom", anchor="w", padx=44, pady=26)

        self.username_entry.focus()
        self.bind("<Return>", lambda event: self.login())

    def login(self):
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()

        valid, role = authenticate_user(username, password)

        if valid:
            self.current_user = username
            self.current_role = role
            self.show_dashboard()
        else:
            self.login_message.configure(text="Credenciales incorrectas. Intenta nuevamente.")

    # ============================================================
    # DASHBOARD
    # ============================================================

    def show_dashboard(self):
        self.stop_analysis_if_running()
        self.clear_window()
        self.unbind("<Return>")

        main = ctk.CTkFrame(self, fg_color=APP_BG)
        main.pack(fill="both", expand=True)
        main.grid_columnconfigure(0, weight=0)
        main.grid_columnconfigure(1, weight=1)
        main.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(main, width=285, fg_color=SIDEBAR_BG, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)

        content = ctk.CTkScrollableFrame(main, fg_color=APP_BG)
        content.grid(row=0, column=1, sticky="nsew")

        logo = ctk.CTkLabel(sidebar, text="RVA", font=("Segoe UI", 36, "bold"), text_color=TEXT_MAIN)
        logo.pack(anchor="w", padx=34, pady=(38, 4))

        logo_sub = ctk.CTkLabel(
            sidebar,
            text="Retail Vision Analytics",
            font=("Segoe UI", 14),
            text_color="#8C96A8",
        )
        logo_sub.pack(anchor="w", padx=36, pady=(0, 34))

        user_box = ctk.CTkFrame(sidebar, fg_color=CARD_BG_2, corner_radius=18)
        user_box.pack(fill="x", padx=24, pady=12)

        user_label = ctk.CTkLabel(
            user_box,
            text=f"Usuario: {self.current_user}",
            font=("Segoe UI", 15, "bold"),
            text_color=TEXT_MAIN,
        )
        user_label.pack(anchor="w", padx=18, pady=(16, 4))

        role_label = ctk.CTkLabel(
            user_box,
            text=f"Rol: {self.current_role}",
            font=("Segoe UI", 13),
            text_color=TEXT_MUTED,
        )
        role_label.pack(anchor="w", padx=18, pady=(0, 16))

        fullscreen_button = ctk.CTkButton(
            sidebar,
            text="Pantalla completa",
            height=42,
            corner_radius=14,
            fg_color="#252B38",
            hover_color="#333B4C",
            font=("Segoe UI", 14, "bold"),
            command=self.toggle_fullscreen,
        )
        fullscreen_button.pack(fill="x", padx=24, pady=(14, 8))

        logout_button = ctk.CTkButton(
            sidebar,
            text="Cerrar sesión",
            height=44,
            corner_radius=14,
            fg_color="#4A2528",
            hover_color="#69343A",
            font=("Segoe UI", 14, "bold"),
            command=self.show_login,
        )
        logout_button.pack(side="bottom", fill="x", padx=24, pady=28)

        header = ctk.CTkLabel(
            content,
            text="Dashboard principal",
            font=("Segoe UI", 38, "bold"),
            text_color=TEXT_MAIN,
        )
        header.pack(anchor="w", padx=48, pady=(46, 4))

        subheader = ctk.CTkLabel(
            content,
            text="Selecciona una herramienta para comenzar.",
            font=("Segoe UI", 17),
            text_color=TEXT_MUTED,
        )
        subheader.pack(anchor="w", padx=50, pady=(0, 30))

        cards_frame = ctk.CTkFrame(content, fg_color="transparent")
        cards_frame.pack(fill="both", expand=True, padx=44, pady=10)
        cards_frame.grid_columnconfigure(0, weight=1)
        cards_frame.grid_columnconfigure(1, weight=1)

        self.create_dashboard_card(
            parent=cards_frame,
            row=0,
            column=0,
            title="Analizar video",
            description="Selecciona un video, configura zonas, ejecuta detección YOLO y genera mapa de calor.",
            button_text="Iniciar análisis",
            command=self.start_video_analysis,
            accent_color="#2F80ED",
        )

        self.create_dashboard_card(
            parent=cards_frame,
            row=0,
            column=1,
            title="Ver gráficas",
            description="Visualización de métricas, horarios peak, permanencia por tienda y uso de escaleras.",
            button_text="Ver resultados",
            command=self.show_results_view,
            accent_color="#8E44AD",
        )

        self.create_dashboard_card(
            parent=cards_frame,
            row=1,
            column=0,
            title="Archivos generados",
            description="Abre la carpeta del proyecto para revisar heatmap, CSV y configuración de zonas.",
            button_text="Abrir carpeta",
            command=self.open_project_folder,
            accent_color="#27AE60",
        )

        self.create_dashboard_card(
            parent=cards_frame,
            row=1,
            column=1,
            title="Configuración",
            description="Próximamente podrás modificar parámetros del modelo, tracking y sensibilidad del mapa de calor.",
            button_text="En desarrollo",
            command=self.show_config_placeholder,
            accent_color="#F2994A",
        )

    def create_dashboard_card(self, parent, row, column, title, description, button_text, command, accent_color):
        card = ctk.CTkFrame(parent, fg_color=PANEL_BG, corner_radius=28)
        card.grid(row=row, column=column, padx=16, pady=16, sticky="nsew")

        accent = ctk.CTkFrame(card, height=7, fg_color=accent_color, corner_radius=8)
        accent.pack(fill="x", padx=28, pady=(28, 22))

        title_label = ctk.CTkLabel(card, text=title, font=("Segoe UI", 28, "bold"), text_color=TEXT_MAIN)
        title_label.pack(anchor="w", padx=32, pady=(0, 10))

        description_label = ctk.CTkLabel(
            card,
            text=description,
            font=("Segoe UI", 16),
            text_color=TEXT_MUTED,
            wraplength=440,
            justify="left",
        )
        description_label.pack(anchor="w", padx=32, pady=(0, 28))

        button = ctk.CTkButton(
            card,
            text=button_text,
            height=50,
            corner_radius=16,
            font=("Segoe UI", 15, "bold"),
            fg_color=accent_color,
            hover_color=accent_color,
            command=command,
        )
        button.pack(anchor="w", padx=32, pady=(8, 32))

    def show_results_view(self):
        self.stop_analysis_if_running()
        self.clear_window()
        self.unbind("<Return>")

        results_view = ResultsView(
            self,
            on_back=self.show_dashboard,
            project_dir=os.getcwd(),
        )
        results_view.pack(fill="both", expand=True)

    def show_config_placeholder(self):
        messagebox.showinfo("Configuración", "Esta sección todavía no está desarrollada.")

    def open_project_folder(self):
        os.startfile(os.getcwd())

    # ============================================================
    # SELECTOR DE VIDEO
    # ============================================================

    def start_video_analysis(self):
        self.show_video_selector()

    def show_video_selector(self):
        self.stop_analysis_if_running()
        self.clear_window()
        self.unbind("<Return>")

        main = ctk.CTkFrame(self, fg_color=APP_BG)
        main.pack(fill="both", expand=True)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)

        topbar = ctk.CTkFrame(main, height=76, fg_color=SIDEBAR_BG, corner_radius=0)
        topbar.grid(row=0, column=0, sticky="ew")
        topbar.grid_propagate(False)

        back_button = ctk.CTkButton(
            topbar,
            text="← Volver",
            width=120,
            height=40,
            corner_radius=14,
            fg_color="#252B38",
            hover_color="#333B4C",
            font=("Segoe UI", 14, "bold"),
            command=self.show_dashboard,
        )
        back_button.pack(side="left", padx=24, pady=18)

        title = ctk.CTkLabel(topbar, text="Seleccionar video", font=("Segoe UI", 24, "bold"), text_color=TEXT_MAIN)
        title.pack(side="left", padx=10)

        fullscreen_button = ctk.CTkButton(
            topbar,
            text="Pantalla completa",
            width=170,
            height=40,
            corner_radius=14,
            fg_color=BLUE,
            hover_color="#1F6FDB",
            font=("Segoe UI", 14, "bold"),
            command=self.toggle_fullscreen,
        )
        fullscreen_button.pack(side="right", padx=24, pady=18)

        content = ctk.CTkScrollableFrame(main, fg_color=APP_BG)
        content.grid(row=1, column=0, sticky="nsew", padx=40, pady=30)

        title_label = ctk.CTkLabel(
            content,
            text="Elige el video que quieres analizar",
            font=("Segoe UI", 34, "bold"),
            text_color=TEXT_MAIN,
        )
        title_label.pack(anchor="w", pady=(10, 6))

        subtitle_label = ctk.CTkLabel(
            content,
            text="Puedes seleccionar un archivo desde tu carpeta o arrastrarlo sobre el recuadro.",
            font=("Segoe UI", 16),
            text_color=TEXT_MUTED,
        )
        subtitle_label.pack(anchor="w", pady=(0, 28))

        drop_card = ctk.CTkFrame(content, fg_color=PANEL_BG, corner_radius=28, height=260)
        drop_card.pack(fill="x", pady=12)
        drop_card.pack_propagate(False)

        drop_title = ctk.CTkLabel(
            drop_card,
            text="Arrastra tu video aquí",
            font=("Segoe UI", 28, "bold"),
            text_color=TEXT_MAIN,
        )
        drop_title.pack(pady=(42, 8))

        drop_subtitle_text = "o usa el botón para buscarlo en tu computador"
        if not DND_AVAILABLE:
            drop_subtitle_text += "\nDrag & drop requiere instalar tkinterdnd2"

        drop_subtitle = ctk.CTkLabel(
            drop_card,
            text=drop_subtitle_text,
            font=("Segoe UI", 15),
            text_color=TEXT_MUTED,
            justify="center",
        )
        drop_subtitle.pack(pady=(0, 22))

        choose_button = ctk.CTkButton(
            drop_card,
            text="Seleccionar archivo",
            height=48,
            width=220,
            corner_radius=16,
            font=("Segoe UI", 15, "bold"),
            fg_color=BLUE,
            hover_color="#1F6FDB",
            command=self.choose_video_file,
        )
        choose_button.pack()

        if DND_AVAILABLE:
            try:
                drop_card.drop_target_register(DND_FILES)
                drop_card.dnd_bind("<<Drop>>", self.on_video_drop)
                drop_title.drop_target_register(DND_FILES)
                drop_title.dnd_bind("<<Drop>>", self.on_video_drop)
                drop_subtitle.drop_target_register(DND_FILES)
                drop_subtitle.dnd_bind("<<Drop>>", self.on_video_drop)
            except Exception as error:
                print(f"No se pudo activar drag and drop: {error}")

        info_card = ctk.CTkFrame(content, fg_color=CARD_BG, corner_radius=22)
        info_card.pack(fill="x", pady=(24, 12))

        self.video_path_label = ctk.CTkLabel(
            info_card,
            text=f"Video seleccionado: {self.current_video_path}",
            font=("Segoe UI", 15, "bold"),
            text_color=TEXT_MAIN,
            wraplength=950,
            justify="left",
        )
        self.video_path_label.pack(anchor="w", padx=24, pady=(22, 6))

        self.video_status_label = ctk.CTkLabel(
            info_card,
            text="Formatos recomendados: MP4, AVI, MOV, MKV.",
            font=("Segoe UI", 14),
            text_color=TEXT_MUTED,
            wraplength=950,
            justify="left",
        )
        self.video_status_label.pack(anchor="w", padx=24, pady=(0, 22))

        action_frame = ctk.CTkFrame(content, fg_color="transparent")
        action_frame.pack(fill="x", pady=20)

        continue_button = ctk.CTkButton(
            action_frame,
            text="Continuar a demarcar zonas",
            height=54,
            corner_radius=18,
            font=("Segoe UI", 16, "bold"),
            fg_color=BLUE,
            hover_color="#1F6FDB",
            command=self.continue_to_zone_editor,
        )
        continue_button.pack(side="left")

        default_button = ctk.CTkButton(
            action_frame,
            text="Usar video.mp4 por defecto",
            height=54,
            corner_radius=18,
            font=("Segoe UI", 15, "bold"),
            fg_color="#252B38",
            hover_color="#333B4C",
            command=lambda: self.set_selected_video(DEFAULT_VIDEO_PATH),
        )
        default_button.pack(side="left", padx=14)

    def choose_video_file(self):
        file_path = filedialog.askopenfilename(
            title="Seleccionar video",
            filetypes=[
                ("Videos", "*.mp4 *.avi *.mov *.mkv *.webm *.m4v"),
                ("Todos los archivos", "*.*"),
            ],
        )
        if file_path:
            self.set_selected_video(file_path)

    def on_video_drop(self, event):
        try:
            files = self.tk.splitlist(event.data)
            if not files:
                return
            file_path = files[0].strip("{}")
            self.set_selected_video(file_path)
        except Exception as error:
            messagebox.showerror("Error", f"No se pudo leer el archivo arrastrado:\n{error}")

    def set_selected_video(self, file_path):
        path = str(Path(file_path))
        extension = Path(path).suffix.lower()

        if extension not in VIDEO_EXTENSIONS:
            messagebox.showerror("Formato no válido", "Selecciona un archivo de video válido.")
            return

        if not os.path.exists(path):
            messagebox.showerror("Archivo no encontrado", f"No existe el archivo:\n{path}")
            return

        self.current_video_path = path
        config.video_path = path
        vision_utils.video_path = path

        if self.video_path_label is not None:
            self.video_path_label.configure(text=f"Video seleccionado: {path}")

        if self.video_status_label is not None:
            self.video_status_label.configure(text="Video cargado correctamente. Puedes continuar.")

    def continue_to_zone_editor(self):
        if not os.path.exists(self.current_video_path):
            messagebox.showerror("Video no encontrado", f"No se encontró el archivo:\n{self.current_video_path}")
            return

        cap = cv2.VideoCapture(self.current_video_path)
        if not cap.isOpened():
            messagebox.showerror("Error", f"No se pudo abrir el video:\n{self.current_video_path}")
            return

        ret, first_frame = cap.read()
        cap.release()

        if not ret:
            messagebox.showerror("Error", "No se pudo leer el primer frame del video.")
            return

        self.show_zone_editor(first_frame)

    # ============================================================
    # EDITOR DE ZONAS
    # ============================================================

    def show_zone_editor(self, first_frame):
        self.stop_analysis_if_running()
        self.clear_window()
        self.unbind("<Return>")

        self.zone_first_frame = first_frame.copy()
        self.zone_frame_height, self.zone_frame_width = first_frame.shape[:2]
        self.zones = load_existing_zones(self.zone_frame_width, self.zone_frame_height)

        self.zone_current_type = "puerta"
        self.zone_buttons = {}
        self.zone_drawing = False
        self.zone_start_canvas = None
        self.zone_temp_canvas = None

        main = ctk.CTkFrame(self, fg_color=APP_BG)
        main.pack(fill="both", expand=True)
        main.grid_columnconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=0)
        main.grid_rowconfigure(1, weight=1)

        topbar = ctk.CTkFrame(main, height=76, fg_color=SIDEBAR_BG, corner_radius=0)
        topbar.grid(row=0, column=0, columnspan=2, sticky="ew")
        topbar.grid_propagate(False)

        back_button = ctk.CTkButton(
            topbar,
            text="← Volver",
            width=120,
            height=40,
            corner_radius=14,
            fg_color="#252B38",
            hover_color="#333B4C",
            font=("Segoe UI", 14, "bold"),
            command=self.show_video_selector,
        )
        back_button.pack(side="left", padx=24, pady=18)

        title = ctk.CTkLabel(
            topbar,
            text="Demarcación de zonas de análisis",
            font=("Segoe UI", 24, "bold"),
            text_color=TEXT_MAIN,
        )
        title.pack(side="left", padx=10)

        fullscreen_button = ctk.CTkButton(
            topbar,
            text="Pantalla completa",
            width=170,
            height=40,
            corner_radius=14,
            fg_color=BLUE,
            hover_color="#1F6FDB",
            font=("Segoe UI", 14, "bold"),
            command=self.toggle_fullscreen,
        )
        fullscreen_button.pack(side="right", padx=24, pady=18)

        video_panel = ctk.CTkFrame(main, fg_color=PANEL_BG, corner_radius=26)
        video_panel.grid(row=1, column=0, padx=22, pady=22, sticky="nsew")
        video_panel.grid_columnconfigure(0, weight=1)
        video_panel.grid_rowconfigure(1, weight=1)

        header_box = ctk.CTkFrame(video_panel, fg_color="transparent")
        header_box.grid(row=0, column=0, padx=24, pady=(20, 8), sticky="ew")

        video_header = ctk.CTkLabel(
            header_box,
            text="Frame base del video",
            font=("Segoe UI", 22, "bold"),
            text_color=TEXT_MAIN,
        )
        video_header.pack(anchor="w")

        video_subtitle = ctk.CTkLabel(
            header_box,
            text=f"Video: {Path(self.current_video_path).name} | Selecciona una categoría y arrastra sobre la imagen.",
            font=("Segoe UI", 14),
            text_color=TEXT_MUTED,
        )
        video_subtitle.pack(anchor="w", pady=(4, 0))

        canvas_container = ctk.CTkFrame(video_panel, fg_color="#070A11", corner_radius=20)
        canvas_container.grid(row=1, column=0, padx=24, pady=(8, 24), sticky="nsew")
        canvas_container.grid_columnconfigure(0, weight=1)
        canvas_container.grid_rowconfigure(0, weight=1)

        self.zone_canvas = tk.Canvas(canvas_container, bg="#070A11", highlightthickness=0, cursor="crosshair")
        self.zone_canvas.grid(row=0, column=0, padx=14, pady=14, sticky="nsew")
        self.zone_canvas.bind("<Configure>", self.on_zone_canvas_resize)
        self.zone_canvas.bind("<ButtonPress-1>", self.on_zone_mouse_down)
        self.zone_canvas.bind("<B1-Motion>", self.on_zone_mouse_drag)
        self.zone_canvas.bind("<ButtonRelease-1>", self.on_zone_mouse_up)

        side_panel = ctk.CTkScrollableFrame(main, width=370, fg_color=PANEL_BG, corner_radius=26)
        side_panel.grid(row=1, column=1, padx=(0, 22), pady=22, sticky="ns")

        side_title = ctk.CTkLabel(side_panel, text="Panel de control", font=("Segoe UI", 25, "bold"), text_color=TEXT_MAIN)
        side_title.pack(anchor="w", padx=22, pady=(24, 4))

        side_desc = ctk.CTkLabel(
            side_panel,
            text="Define áreas para medir entradas, salidas, tránsito por escaleras y permanencia.",
            font=("Segoe UI", 14),
            text_color=TEXT_MUTED,
            wraplength=300,
            justify="left",
        )
        side_desc.pack(anchor="w", padx=22, pady=(0, 22))

        self.create_zone_type_button(side_panel, "puerta", "Puerta de local", "Acceso a tienda o comercio")
        self.create_zone_type_button(side_panel, "escalera", "Escalera", "Conexión vertical entre pisos")
        self.create_zone_type_button(side_panel, "salida", "Salida", "Salida general del recinto")
        self.create_zone_type_button(side_panel, "zona", "Zona personalizada", "Área libre de interés")

        separator = ctk.CTkFrame(side_panel, height=1, fg_color="#283244")
        separator.pack(fill="x", padx=22, pady=24)

        self.zone_counter_label = ctk.CTkLabel(
            side_panel,
            text=f"Zonas configuradas: {len(self.zones)}",
            font=("Segoe UI", 15, "bold"),
            text_color=TEXT_MAIN,
        )
        self.zone_counter_label.pack(anchor="w", padx=22, pady=(0, 12))

        undo_button = ctk.CTkButton(
            side_panel,
            text="Deshacer última zona",
            height=44,
            corner_radius=14,
            font=("Segoe UI", 14, "bold"),
            fg_color="#303849",
            hover_color="#3A4356",
            command=self.zone_undo,
        )
        undo_button.pack(fill="x", padx=22, pady=6)

        clear_button = ctk.CTkButton(
            side_panel,
            text="Limpiar todas",
            height=44,
            corner_radius=14,
            font=("Segoe UI", 14, "bold"),
            fg_color="#4A2528",
            hover_color="#69343A",
            command=self.zone_clear,
        )
        clear_button.pack(fill="x", padx=22, pady=6)

        save_button = ctk.CTkButton(
            side_panel,
            text="Guardar zonas y analizar",
            height=54,
            corner_radius=18,
            font=("Segoe UI", 16, "bold"),
            fg_color=BLUE,
            hover_color="#1F6FDB",
            command=self.zone_save_and_run,
        )
        save_button.pack(fill="x", padx=22, pady=(26, 8))

        cancel_button = ctk.CTkButton(
            side_panel,
            text="Cancelar",
            height=46,
            corner_radius=16,
            font=("Segoe UI", 15, "bold"),
            fg_color="#252B38",
            hover_color="#333B4C",
            command=self.show_dashboard,
        )
        cancel_button.pack(fill="x", padx=22, pady=(0, 24))

        self.update_zone_type_buttons()
        self.after(100, self.redraw_zone_canvas)

    def create_zone_type_button(self, parent, zone_type, title, description):
        # Usamos una tarjeta con labels en vez de un CTkButton multilinea.
        # Así el texto no se corta ni se corre cuando cambia el tamaño del panel.
        card = ctk.CTkFrame(
            parent,
            height=92,
            corner_radius=18,
            fg_color="#202838",
        )
        card.pack(fill="x", padx=22, pady=7)
        card.pack_propagate(False)

        title_label = ctk.CTkLabel(
            card,
            text=title,
            font=("Segoe UI", 15, "bold"),
            text_color=TEXT_MAIN,
            anchor="w",
            justify="left",
        )
        title_label.pack(fill="x", padx=22, pady=(18, 2))

        desc_label = ctk.CTkLabel(
            card,
            text=description,
            font=("Segoe UI", 13, "bold"),
            text_color=TEXT_MAIN,
            anchor="w",
            justify="left",
            wraplength=280,
        )
        desc_label.pack(fill="x", padx=22, pady=(0, 14))

        def select_zone(event=None, selected_type=zone_type):
            self.set_zone_current_type(selected_type)

        card.bind("<Button-1>", select_zone)
        title_label.bind("<Button-1>", select_zone)
        desc_label.bind("<Button-1>", select_zone)

        self.zone_buttons[zone_type] = {
            "card": card,
            "title": title_label,
            "description": desc_label,
        }

    def update_zone_type_buttons(self):
        for zone_type, widgets in self.zone_buttons.items():
            card = widgets["card"]
            title_label = widgets["title"]
            desc_label = widgets["description"]

            if zone_type == self.zone_current_type:
                card.configure(fg_color=ZONE_STYLES[zone_type]["hex"])
                title_label.configure(text_color="#101010")
                desc_label.configure(text_color="#101010")
            else:
                card.configure(fg_color="#202838")
                title_label.configure(text_color=TEXT_MAIN)
                desc_label.configure(text_color=TEXT_MAIN)

    def set_zone_current_type(self, zone_type):
        self.zone_current_type = zone_type
        self.update_zone_type_buttons()

    def update_zone_canvas_metrics(self):
        if self.zone_canvas is None:
            return

        canvas_width = max(self.zone_canvas.winfo_width(), 100)
        canvas_height = max(self.zone_canvas.winfo_height(), 100)

        self.zone_scale = min(canvas_width / self.zone_frame_width, canvas_height / self.zone_frame_height)
        self.zone_display_width = int(self.zone_frame_width * self.zone_scale)
        self.zone_display_height = int(self.zone_frame_height * self.zone_scale)
        self.zone_offset_x = int((canvas_width - self.zone_display_width) / 2)
        self.zone_offset_y = int((canvas_height - self.zone_display_height) / 2)

    def original_to_canvas(self, x, y):
        return (
            self.zone_offset_x + int(x * self.zone_scale),
            self.zone_offset_y + int(y * self.zone_scale),
        )

    def canvas_to_original(self, canvas_x, canvas_y):
        original_x = int((canvas_x - self.zone_offset_x) / self.zone_scale)
        original_y = int((canvas_y - self.zone_offset_y) / self.zone_scale)
        original_x = int(np.clip(original_x, 0, self.zone_frame_width - 1))
        original_y = int(np.clip(original_y, 0, self.zone_frame_height - 1))
        return original_x, original_y

    def point_is_inside_video_canvas(self, x, y):
        return (
            self.zone_offset_x <= x <= self.zone_offset_x + self.zone_display_width
            and self.zone_offset_y <= y <= self.zone_offset_y + self.zone_display_height
        )

    def clip_canvas_point_to_video(self, x, y):
        clipped_x = int(np.clip(x, self.zone_offset_x, self.zone_offset_x + self.zone_display_width))
        clipped_y = int(np.clip(y, self.zone_offset_y, self.zone_offset_y + self.zone_display_height))
        return clipped_x, clipped_y

    def on_zone_canvas_resize(self, event=None):
        self.redraw_zone_canvas()

    def redraw_zone_canvas(self):
        if self.zone_canvas is None or self.zone_first_frame is None:
            return
        if not self.zone_canvas.winfo_exists():
            return

        self.update_zone_canvas_metrics()
        self.zone_canvas.delete("all")

        rgb_frame = cv2.cvtColor(self.zone_first_frame, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(rgb_frame)

        try:
            resample_method = Image.Resampling.LANCZOS
        except AttributeError:
            resample_method = Image.LANCZOS

        pil_image = pil_image.resize((self.zone_display_width, self.zone_display_height), resample_method)
        self.zone_photo = ImageTk.PhotoImage(pil_image)

        self.zone_canvas.create_image(self.zone_offset_x, self.zone_offset_y, anchor="nw", image=self.zone_photo)
        self.zone_canvas.create_rectangle(
            self.zone_offset_x,
            self.zone_offset_y,
            self.zone_offset_x + self.zone_display_width,
            self.zone_offset_y + self.zone_display_height,
            outline=BLUE,
            width=2,
        )

        for zone in self.zones:
            style = ZONE_STYLES.get(zone["type"], ZONE_STYLES["zona"])
            color = style["hex"]

            dx1, dy1 = self.original_to_canvas(zone["x1"], zone["y1"])
            dx2, dy2 = self.original_to_canvas(zone["x2"], zone["y2"])
            self.zone_canvas.create_rectangle(dx1, dy1, dx2, dy2, outline=color, width=3)

            label_text = display_zone_label(zone)
            font_size = max(10, min(15, int(11 + self.zone_scale * 3)))
            label_width = max(145, min(320, len(label_text) * 8 + 26))
            label_x1 = min(dx1, self.zone_offset_x + self.zone_display_width - label_width - 4)
            label_y1 = max(dy1 - 32, self.zone_offset_y + 4)
            label_y2 = label_y1 + 26

            self.zone_canvas.create_rectangle(
                label_x1,
                label_y1,
                label_x1 + label_width,
                label_y2,
                fill="#0B0F19",
                outline=color,
                width=1,
            )
            self.zone_canvas.create_text(
                label_x1 + 10,
                label_y1 + 13,
                anchor="w",
                text=label_text,
                fill=color,
                font=("Segoe UI", font_size, "bold"),
            )

        if self.zone_drawing and self.zone_start_canvas and self.zone_temp_canvas:
            x1, y1 = self.zone_start_canvas
            x2, y2 = self.zone_temp_canvas
            color = ZONE_STYLES[self.zone_current_type]["hex"]
            self.zone_canvas.create_rectangle(x1, y1, x2, y2, outline=color, width=3, dash=(8, 4))

    def on_zone_mouse_down(self, event):
        self.update_zone_canvas_metrics()
        if not self.point_is_inside_video_canvas(event.x, event.y):
            return
        self.zone_drawing = True
        start_x, start_y = self.clip_canvas_point_to_video(event.x, event.y)
        self.zone_start_canvas = (start_x, start_y)
        self.zone_temp_canvas = (start_x, start_y)
        self.redraw_zone_canvas()

    def on_zone_mouse_drag(self, event):
        if not self.zone_drawing:
            return
        x, y = self.clip_canvas_point_to_video(event.x, event.y)
        self.zone_temp_canvas = (x, y)
        self.redraw_zone_canvas()

    def on_zone_mouse_up(self, event):
        if not self.zone_drawing:
            return

        self.zone_drawing = False
        end_x, end_y = self.clip_canvas_point_to_video(event.x, event.y)
        start_x, start_y = self.zone_start_canvas

        ox1, oy1 = self.canvas_to_original(start_x, start_y)
        ox2, oy2 = self.canvas_to_original(end_x, end_y)

        self.zone_start_canvas = None
        self.zone_temp_canvas = None
        self.add_zone(self.zone_current_type, ox1, oy1, ox2, oy2)
        self.redraw_zone_canvas()

    def get_next_zone_id(self, zone_type):
        numbers = []
        for zone in self.zones:
            if zone["type"] == zone_type:
                try:
                    numbers.append(int(zone["id"].split("_")[-1]))
                except Exception:
                    pass
        next_number = max(numbers) + 1 if numbers else 1
        return f"{zone_type}_{next_number}"

    def add_zone(self, zone_type, x1, y1, x2, y2):
        x1, x2 = sorted([x1, x2])
        y1, y2 = sorted([y1, y2])

        if abs(x2 - x1) < 10 or abs(y2 - y1) < 10:
            print("Zona ignorada: rectángulo demasiado pequeño")
            return

        zone_id = self.get_next_zone_id(zone_type)
        default_name = f"{ZONE_STYLES[zone_type]['label']} {zone_id.split('_')[-1]}"

        zone_name = simpledialog.askstring(
            "Nombrar zona",
            "Nombre de la zona:",
            initialvalue=default_name,
            parent=self,
        )

        if zone_name is None or not zone_name.strip():
            zone_name = default_name

        zone = {
            "id": zone_id,
            "name": zone_name.strip(),
            "type": zone_type,
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
        }
        self.zones.append(zone)

        if self.zone_counter_label is not None:
            self.zone_counter_label.configure(text=f"Zonas configuradas: {len(self.zones)}")

        print(f"Zona creada: {zone['id']} | {zone['name']}")

    def zone_undo(self):
        if self.zones:
            removed = self.zones.pop()
            print(f"Zona eliminada: {removed['id']}")

        if self.zone_counter_label is not None:
            self.zone_counter_label.configure(text=f"Zonas configuradas: {len(self.zones)}")

        self.redraw_zone_canvas()

    def zone_clear(self):
        confirm = messagebox.askyesno("Limpiar zonas", "¿Seguro que quieres eliminar todas las zonas configuradas?")
        if confirm:
            self.zones.clear()
            if self.zone_counter_label is not None:
                self.zone_counter_label.configure(text=f"Zonas configuradas: {len(self.zones)}")
            self.redraw_zone_canvas()

    def zone_save_and_run(self):
        save_zones(self.zones, self.zone_frame_width, self.zone_frame_height)
        self.show_analysis_screen(self.zones)

    # ============================================================
    # PANTALLA DE ANÁLISIS
    # ============================================================

    def show_analysis_screen(self, zones):
        self.stop_analysis_if_running()
        self.clear_window()

        self.analysis_running = False
        self.analysis_queue = queue.Queue()
        self.analysis_stop_event = threading.Event()
        self.analysis_current_frame = None
        self.analysis_zones = [zone.copy() for zone in zones]

        main = ctk.CTkFrame(self, fg_color=APP_BG)
        main.pack(fill="both", expand=True)
        main.grid_columnconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=0)
        main.grid_rowconfigure(1, weight=1)

        topbar = ctk.CTkFrame(main, height=76, fg_color=SIDEBAR_BG, corner_radius=0)
        topbar.grid(row=0, column=0, columnspan=2, sticky="ew")
        topbar.grid_propagate(False)

        title = ctk.CTkLabel(topbar, text="Análisis de video", font=("Segoe UI", 24, "bold"), text_color=TEXT_MAIN)
        title.pack(side="left", padx=28, pady=18)

        fullscreen_button = ctk.CTkButton(
            topbar,
            text="Pantalla completa",
            width=170,
            height=40,
            corner_radius=14,
            fg_color=BLUE,
            hover_color="#1F6FDB",
            font=("Segoe UI", 14, "bold"),
            command=self.toggle_fullscreen,
        )
        fullscreen_button.pack(side="right", padx=24, pady=18)

        video_panel = ctk.CTkFrame(main, fg_color=PANEL_BG, corner_radius=26)
        video_panel.grid(row=1, column=0, padx=22, pady=22, sticky="nsew")
        video_panel.grid_columnconfigure(0, weight=1)
        video_panel.grid_rowconfigure(0, weight=1)

        self.analysis_canvas = tk.Canvas(video_panel, bg="#070A11", highlightthickness=0)
        self.analysis_canvas.grid(row=0, column=0, padx=16, pady=16, sticky="nsew")
        self.analysis_canvas.bind("<Configure>", lambda event: self.render_analysis_canvas())

        side_panel = ctk.CTkScrollableFrame(main, width=370, fg_color=PANEL_BG, corner_radius=26)
        side_panel.grid(row=1, column=1, padx=(0, 22), pady=22, sticky="ns")

        side_title = ctk.CTkLabel(side_panel, text="Estado del análisis", font=("Segoe UI", 25, "bold"), text_color=TEXT_MAIN)
        side_title.pack(anchor="w", padx=22, pady=(24, 4))

        self.analysis_status_label = ctk.CTkLabel(
            side_panel,
            text="Preparando análisis...",
            font=("Segoe UI", 15),
            text_color=TEXT_MUTED,
            wraplength=300,
            justify="left",
        )
        self.analysis_status_label.pack(anchor="w", padx=22, pady=(0, 18))

        self.analysis_progress = ctk.CTkProgressBar(side_panel, height=14, corner_radius=8)
        self.analysis_progress.pack(fill="x", padx=22, pady=(0, 18))
        self.analysis_progress.set(0)

        self.analysis_frame_label = ctk.CTkLabel(side_panel, text="Frames analizados: 0", font=("Segoe UI", 14), text_color=TEXT_MAIN)
        self.analysis_frame_label.pack(anchor="w", padx=22, pady=6)

        self.analysis_people_label = ctk.CTkLabel(side_panel, text="Personas únicas: 0", font=("Segoe UI", 14), text_color=TEXT_MAIN)
        self.analysis_people_label.pack(anchor="w", padx=22, pady=6)

        self.analysis_zone_label = ctk.CTkLabel(side_panel, text=f"Zonas configuradas: {len(zones)}", font=("Segoe UI", 14), text_color=TEXT_MAIN)
        self.analysis_zone_label.pack(anchor="w", padx=22, pady=6)

        stop_button = ctk.CTkButton(
            side_panel,
            text="Detener análisis",
            height=46,
            corner_radius=16,
            font=("Segoe UI", 15, "bold"),
            fg_color="#4A2528",
            hover_color="#69343A",
            command=self.stop_analysis_user,
        )
        stop_button.pack(fill="x", padx=22, pady=(26, 8))

        dashboard_button = ctk.CTkButton(
            side_panel,
            text="Volver al dashboard",
            height=46,
            corner_radius=16,
            font=("Segoe UI", 15, "bold"),
            fg_color="#252B38",
            hover_color="#333B4C",
            command=self.show_dashboard,
        )
        dashboard_button.pack(fill="x", padx=22, pady=(0, 8))

        self.analysis_results_button = ctk.CTkButton(
            side_panel,
            text="Ver gráficas",
            height=46,
            corner_radius=16,
            font=("Segoe UI", 15, "bold"),
            fg_color="#8E44AD",
            hover_color="#7D3C98",
            state="disabled",
            command=self.show_results_view,
        )
        self.analysis_results_button.pack(fill="x", padx=22, pady=(0, 24))

        self.start_analysis_thread()

    def start_analysis_thread(self):
        self.analysis_running = True
        self.analysis_thread = threading.Thread(target=self.analysis_worker, daemon=True)
        self.analysis_thread.start()
        self.after(50, self.poll_analysis_queue)

    def analysis_worker(self):
        try:
            self.analysis_queue.put({"type": "status", "text": "Cargando modelo YOLO..."})
            model = YOLO(model_name)

            cap = cv2.VideoCapture(self.current_video_path)
            if not cap.isOpened():
                self.analysis_queue.put({"type": "error", "text": f"No se pudo abrir el video: {self.current_video_path}"})
                return

            ret, first_frame = cap.read()
            if not ret:
                cap.release()
                self.analysis_queue.put({"type": "error", "text": "No se pudo leer el primer frame del video."})
                return

            frame_height, frame_width = first_frame.shape[:2]
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

            heatmap = np.zeros((frame_height, frame_width), dtype=np.float32)
            person_labels = {}
            next_person_number = 1
            frame_count = 0
            best_frame = None
            best_score = 0
            zones = [zone.copy() for zone in self.analysis_zones]
            zone_counts = {zone["id"]: 0 for zone in zones}
            person_zone_state = {}

            self.analysis_queue.put({"type": "status", "text": "Analizando video..."})

            while True:
                if self.analysis_stop_event.is_set():
                    cap.release()
                    self.analysis_queue.put({"type": "stopped", "text": "Análisis detenido por el usuario."})
                    return

                ret, frame = cap.read()
                if not ret:
                    break

                frame_count += 1
                current_people = 0

                results = model.track(
                    frame,
                    persist=True,
                    tracker=tracker_type,
                    classes=[0],
                    conf=confidence,
                    iou=iou_value,
                    verbose=False,
                )

                if results[0].boxes.id is not None:
                    boxes = results[0].boxes.xyxy.cpu().numpy()
                    track_ids = results[0].boxes.id.cpu().numpy().astype(int)
                    current_people = len(track_ids)

                    for box, track_id in zip(boxes, track_ids):
                        x1, y1, x2, y2 = map(int, box)

                        center_x = int((x1 + x2) / 2)
                        center_y = int((y1 + y2) / 2)
                        center_x = int(np.clip(center_x, 0, frame_width - 1))
                        center_y = int(np.clip(center_y, 0, frame_height - 1))

                        heatmap[center_y, center_x] += 1

                        if track_id not in person_labels:
                            person_labels[track_id] = f"persona_{next_person_number}"
                            next_person_number += 1

                        label = person_labels[track_id]
                        current_inside_zones = set()

                        for zone in zones:
                            if point_inside_zone(center_x, center_y, zone):
                                current_inside_zones.add(zone["id"])

                        previous_inside_zones = person_zone_state.get(track_id, set())
                        new_entries = current_inside_zones - previous_inside_zones

                        for zone_id in new_entries:
                            zone_counts[zone_id] += 1

                        person_zone_state[track_id] = current_inside_zones

                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        cv2.putText(frame, label, (x1, max(y1 - 10, 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
                        cv2.circle(frame, (center_x, center_y), 4, (0, 255, 255), -1)

                draw_zones_on_frame(frame, zones, zone_counts, alpha=0.12)

                score = current_people + np.max(heatmap) * 0.05
                if best_frame is None or score > best_score:
                    best_score = score
                    best_frame = frame.copy()

                if frame_count % display_every_n_frames == 0:
                    self.analysis_queue.put({
                        "type": "frame",
                        "frame": frame.copy(),
                        "frame_count": frame_count,
                        "total_frames": total_frames,
                        "unique_people": len(person_labels),
                    })

            cap.release()

            if best_frame is None:
                self.analysis_queue.put({"type": "error", "text": "No se pudo generar frame representativo."})
                return

            self.analysis_queue.put({"type": "status", "text": "Generando heatmap final..."})
            final_image = generate_final_heatmap(best_frame, heatmap, zones, zone_counts)

            cv2.imwrite(heatmap_output_file, final_image)
            save_zone_report(zones, zone_counts)

            self.analysis_queue.put({
                "type": "finished",
                "frame": final_image.copy(),
                "frame_count": frame_count,
                "total_frames": total_frames,
                "unique_people": len(person_labels),
                "text": f"Análisis completado.\nImagen: {heatmap_output_file}\nReporte: {zone_report_file}",
            })

        except Exception as error:
            self.analysis_queue.put({"type": "error", "text": f"Error durante el análisis:\n{error}"})

    def poll_analysis_queue(self):
        if self.analysis_queue is None:
            return

        try:
            while True:
                item = self.analysis_queue.get_nowait()
                item_type = item.get("type")

                if item_type == "status":
                    if self.analysis_status_label is not None:
                        self.analysis_status_label.configure(text=item["text"])

                elif item_type == "frame":
                    self.analysis_current_frame = item["frame"]
                    self.render_analysis_canvas()

                    total = item.get("total_frames", 0)
                    frame_count = item.get("frame_count", 0)

                    if total > 0 and self.analysis_progress is not None:
                        self.analysis_progress.set(min(frame_count / total, 1))

                    if self.analysis_frame_label is not None:
                        self.analysis_frame_label.configure(text=f"Frames analizados: {frame_count}")

                    if self.analysis_people_label is not None:
                        self.analysis_people_label.configure(text=f"Personas únicas: {item.get('unique_people', 0)}")

                elif item_type == "finished":
                    self.analysis_running = False
                    self.analysis_current_frame = item["frame"]
                    self.render_analysis_canvas()

                    if self.analysis_progress is not None:
                        self.analysis_progress.set(1)

                    if self.analysis_status_label is not None:
                        self.analysis_status_label.configure(text=item["text"])

                    if self.analysis_frame_label is not None:
                        self.analysis_frame_label.configure(text=f"Frames analizados: {item.get('frame_count', 0)}")

                    if self.analysis_people_label is not None:
                        self.analysis_people_label.configure(text=f"Personas únicas: {item.get('unique_people', 0)}")

                    if self.analysis_results_button is not None:
                        self.analysis_results_button.configure(state="normal")

                    print("\n===================================")
                    print("ANÁLISIS COMPLETADO")
                    print("===================================")
                    print(f"Frames analizados: {item.get('frame_count', 0)}")
                    print(f"Personas únicas detectadas: {item.get('unique_people', 0)}")
                    print(f"Imagen guardada como: {heatmap_output_file}")
                    print(f"Reporte guardado como: {zone_report_file}")

                elif item_type == "stopped":
                    self.analysis_running = False
                    if self.analysis_status_label is not None:
                        self.analysis_status_label.configure(text=item["text"])

                elif item_type == "error":
                    self.analysis_running = False
                    if self.analysis_status_label is not None:
                        self.analysis_status_label.configure(text=item["text"])
                    messagebox.showerror("Error", item["text"])

        except queue.Empty:
            pass

        if self.analysis_running:
            self.after(50, self.poll_analysis_queue)

    def render_analysis_canvas(self):
        if self.analysis_canvas is None:
            return
        if self.analysis_current_frame is None:
            return
        if not self.analysis_canvas.winfo_exists():
            return

        frame = self.analysis_current_frame
        canvas_width = max(self.analysis_canvas.winfo_width(), 100)
        canvas_height = max(self.analysis_canvas.winfo_height(), 100)
        frame_height, frame_width = frame.shape[:2]

        scale = min(canvas_width / frame_width, canvas_height / frame_height)
        display_width = int(frame_width * scale)
        display_height = int(frame_height * scale)
        offset_x = int((canvas_width - display_width) / 2)
        offset_y = int((canvas_height - display_height) / 2)

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(rgb_frame)

        try:
            resample_method = Image.Resampling.LANCZOS
        except AttributeError:
            resample_method = Image.LANCZOS

        pil_image = pil_image.resize((display_width, display_height), resample_method)
        self.analysis_photo = ImageTk.PhotoImage(pil_image)

        self.analysis_canvas.delete("all")
        self.analysis_canvas.create_image(offset_x, offset_y, anchor="nw", image=self.analysis_photo)

    def stop_analysis_user(self):
        if self.analysis_stop_event is not None:
            self.analysis_stop_event.set()
        self.analysis_running = False
        if self.analysis_status_label is not None:
            self.analysis_status_label.configure(text="Deteniendo análisis...")


def main():
    init_database()
    app = RetailAnalyticsApp()
    app.mainloop()


if __name__ == "__main__":
    main()
