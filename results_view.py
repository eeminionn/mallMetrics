import os
import csv
from pathlib import Path
import tkinter as tk

import customtkinter as ctk
from PIL import Image, ImageTk

from config import (
    APP_BG,
    SIDEBAR_BG,
    PANEL_BG,
    CARD_BG,
    TEXT_MAIN,
    TEXT_MUTED,
    BLUE,
    heatmap_output_file,
    zone_report_file,
)


class ResultsView(ctk.CTkFrame):
    def __init__(self, master, on_back=None, project_dir=None):
        super().__init__(master, fg_color=APP_BG)

        self.master = master
        self.on_back = on_back
        self.project_dir = Path(project_dir or os.getcwd())

        self.zone_report_path = self.project_dir / zone_report_file
        self.heatmap_path = self.project_dir / heatmap_output_file
        self.store_metrics_path = self.project_dir / "store_metrics.csv"
        self.time_bins_path = self.project_dir / "time_bins.csv"
        self.stair_metrics_path = self.project_dir / "stair_metrics.csv"
        self.summary_path = self.project_dir / "analytics_summary.csv"
        self.zone_metrics_path = self.project_dir / "zone_metrics.csv"

        self.heatmap_image_ref = None

        self.zone_rows = []
        self.zone_metric_rows = []
        self.store_rows = []
        self.time_rows = []
        self.stair_rows = []
        self.summary = {}

        self.load_data()
        self.build_ui()

    # ============================================================
    # CARGA DE DATOS
    # ============================================================

    def read_csv_dicts(self, path):
        if not path.exists():
            return []

        try:
            with open(path, "r", encoding="utf-8") as file:
                reader = csv.DictReader(file)
                return list(reader)
        except UnicodeDecodeError:
            try:
                with open(path, "r", encoding="latin-1") as file:
                    reader = csv.DictReader(file)
                    return list(reader)
            except Exception as error:
                print(f"No se pudo leer {path}: {error}")
                return []
        except Exception as error:
            print(f"No se pudo leer {path}: {error}")
            return []

    def load_data(self):
        self.zone_rows = self.read_csv_dicts(self.zone_report_path)
        self.zone_metric_rows = self.read_csv_dicts(self.zone_metrics_path)
        self.store_rows = self.read_csv_dicts(self.store_metrics_path)
        self.time_rows = self.read_csv_dicts(self.time_bins_path)
        self.stair_rows = self.read_csv_dicts(self.stair_metrics_path)

        summary_rows = self.read_csv_dicts(self.summary_path)
        if summary_rows:
            self.summary = summary_rows[0]
        else:
            self.summary = self.build_summary_from_available_data()

    def build_summary_from_available_data(self):
        total_zone_entries = 0
        total_zones = len(self.zone_rows)

        for row in self.zone_rows:
            total_zone_entries += self.safe_int(row.get("entry_count", 0))

        return {
            "total_people": "—",
            "total_zone_entries": str(total_zone_entries),
            "total_store_entries": self.estimate_store_entries(),
            "avg_dwell_time": "—",
            "total_zones": str(total_zones),
            "flow_heatmap_points": "0",
        }

    def estimate_store_entries(self):
        total = 0
        for row in self.zone_rows:
            zone_type = str(row.get("zone_type", "")).lower()
            if zone_type == "puerta":
                total += self.safe_int(row.get("entry_count", 0))
        return str(total)

    def safe_int(self, value):
        try:
            return int(float(value))
        except Exception:
            return 0

    def safe_float(self, value):
        try:
            return float(value)
        except Exception:
            return 0.0

    def format_percent(self, value):
        return f"{value * 100:.1f}%"

    # ============================================================
    # UI PRINCIPAL
    # ============================================================

    def build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.build_topbar()

        self.content = ctk.CTkScrollableFrame(self, fg_color=APP_BG)
        self.content.grid(row=1, column=0, sticky="nsew")

        self.build_header()
        self.build_kpi_row()
        self.build_main_grid()
        self.build_detail_section()

    def build_topbar(self):
        topbar = ctk.CTkFrame(self, height=76, fg_color=SIDEBAR_BG, corner_radius=0)
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
            command=self.go_back,
        )
        back_button.pack(side="left", padx=24, pady=18)

        title = ctk.CTkLabel(
            topbar,
            text="Dashboard de resultados",
            font=("Segoe UI", 24, "bold"),
            text_color=TEXT_MAIN,
        )
        title.pack(side="left", padx=10)

        refresh_button = ctk.CTkButton(
            topbar,
            text="Actualizar datos",
            width=160,
            height=40,
            corner_radius=14,
            fg_color=BLUE,
            hover_color="#1F6FDB",
            font=("Segoe UI", 14, "bold"),
            command=self.refresh_data,
        )
        refresh_button.pack(side="right", padx=24, pady=18)

    def build_header(self):
        header = ctk.CTkLabel(
            self.content,
            text="Análisis de flujo peatonal",
            font=("Segoe UI", 36, "bold"),
            text_color=TEXT_MAIN,
        )
        header.pack(anchor="w", padx=44, pady=(34, 4))

        subtitle_text = "Resumen visual del último análisis generado por YOLO."
        if not self.zone_report_path.exists() and not self.store_metrics_path.exists():
            subtitle_text = "Todavía no hay datos suficientes. Ejecuta primero un análisis de video."

        subtitle = ctk.CTkLabel(
            self.content,
            text=subtitle_text,
            font=("Segoe UI", 16),
            text_color=TEXT_MUTED,
        )
        subtitle.pack(anchor="w", padx=46, pady=(0, 24))

    def build_kpi_row(self):
        kpi_frame = ctk.CTkFrame(self.content, fg_color="transparent")
        kpi_frame.pack(fill="x", padx=40, pady=(0, 16))

        for i in range(4):
            kpi_frame.grid_columnconfigure(i, weight=1)

        self.create_kpi_card(
            kpi_frame,
            column=0,
            title="Personas validadas",
            value=self.summary.get("total_people", "—"),
            description="Personas confirmadas por filtros estadísticos",
            accent="#2F80ED",
        )

        self.create_kpi_card(
            kpi_frame,
            column=1,
            title="Entradas a zonas",
            value=self.summary.get("total_zone_entries", "0"),
            description="Cruces válidos en áreas demarcadas",
            accent="#27AE60",
        )

        self.create_kpi_card(
            kpi_frame,
            column=2,
            title="Ingresos tienda",
            value=self.summary.get("total_store_entries", "0"),
            description="Estimación según puertas",
            accent="#F2994A",
        )

        self.create_kpi_card(
            kpi_frame,
            column=3,
            title="Flujo heatmap",
            value=self.summary.get("flow_heatmap_points", "0"),
            description="Puntos de movimiento real usados",
            accent="#8E44AD",
        )

    def create_kpi_card(self, parent, column, title, value, description, accent):
        card = ctk.CTkFrame(parent, fg_color=PANEL_BG, corner_radius=22)
        card.grid(row=0, column=column, padx=8, pady=8, sticky="nsew")

        accent_bar = ctk.CTkFrame(card, height=5, fg_color=accent, corner_radius=5)
        accent_bar.pack(fill="x", padx=18, pady=(18, 14))

        title_label = ctk.CTkLabel(card, text=title, font=("Segoe UI", 14, "bold"), text_color=TEXT_MUTED)
        title_label.pack(anchor="w", padx=20, pady=(0, 2))

        value_label = ctk.CTkLabel(card, text=str(value), font=("Segoe UI", 34, "bold"), text_color=TEXT_MAIN)
        value_label.pack(anchor="w", padx=20, pady=(0, 2))

        desc_label = ctk.CTkLabel(card, text=description, font=("Segoe UI", 12), text_color="#7D8797")
        desc_label.pack(anchor="w", padx=20, pady=(0, 18))

    # ============================================================
    # GRILLA PRINCIPAL
    # ============================================================

    def build_main_grid(self):
        grid = ctk.CTkFrame(self.content, fg_color="transparent")
        grid.pack(fill="both", expand=True, padx=40, pady=8)
        grid.grid_columnconfigure(0, weight=2)
        grid.grid_columnconfigure(1, weight=1)

        heatmap_card = ctk.CTkFrame(grid, fg_color=PANEL_BG, corner_radius=26)
        heatmap_card.grid(row=0, column=0, padx=8, pady=8, sticky="nsew")

        ranking_card = ctk.CTkFrame(grid, fg_color=PANEL_BG, corner_radius=26)
        ranking_card.grid(row=0, column=1, padx=8, pady=8, sticky="nsew")

        time_card = ctk.CTkFrame(grid, fg_color=PANEL_BG, corner_radius=26)
        time_card.grid(row=1, column=0, padx=8, pady=8, sticky="nsew")

        stair_card = ctk.CTkFrame(grid, fg_color=PANEL_BG, corner_radius=26)
        stair_card.grid(row=1, column=1, padx=8, pady=8, sticky="nsew")

        store_flow_card = ctk.CTkFrame(grid, fg_color=PANEL_BG, corner_radius=26)
        store_flow_card.grid(row=2, column=0, columnspan=2, padx=8, pady=8, sticky="nsew")

        self.build_heatmap_card(heatmap_card)
        self.build_ranking_card(ranking_card)
        self.build_time_card(time_card)
        self.build_stair_card(stair_card)
        self.build_store_flow_card(store_flow_card)

    def build_card_title(self, parent, title, subtitle=None):
        title_label = ctk.CTkLabel(parent, text=title, font=("Segoe UI", 22, "bold"), text_color=TEXT_MAIN)
        title_label.pack(anchor="w", padx=24, pady=(22, 2))

        if subtitle:
            subtitle_label = ctk.CTkLabel(
                parent,
                text=subtitle,
                font=("Segoe UI", 13),
                text_color=TEXT_MUTED,
                wraplength=780,
                justify="left",
            )
            subtitle_label.pack(anchor="w", padx=24, pady=(0, 14))

    def build_heatmap_card(self, parent):
        self.build_card_title(
            parent,
            "Mapa de calor por flujo real",
            "Calculado con movimiento efectivo. Personas estáticas o semi-estáticas no generan zonas rojas falsas.",
        )

        image_container = ctk.CTkFrame(parent, fg_color="#070A11", corner_radius=18)
        image_container.pack(fill="both", expand=True, padx=22, pady=(0, 22))

        canvas = tk.Canvas(image_container, bg="#070A11", highlightthickness=0, height=360)
        canvas.pack(fill="both", expand=True, padx=12, pady=12)

        def render_heatmap(event=None):
            canvas.delete("all")

            if not self.heatmap_path.exists():
                self.draw_empty_state(canvas)
                return

            try:
                image = Image.open(self.heatmap_path).convert("RGB")
                cw = max(canvas.winfo_width(), 100)
                ch = max(canvas.winfo_height(), 100)
                scale = min(cw / image.width, ch / image.height)
                new_size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
                image = image.resize(new_size, Image.Resampling.LANCZOS)
                self.heatmap_image_ref = ImageTk.PhotoImage(image)
                x = int((cw - new_size[0]) / 2)
                y = int((ch - new_size[1]) / 2)
                canvas.create_image(x, y, anchor="nw", image=self.heatmap_image_ref)
            except Exception as error:
                canvas.create_text(
                    max(canvas.winfo_width() // 2, 120),
                    max(canvas.winfo_height() // 2, 80),
                    text=f"No se pudo cargar el heatmap:\n{error}",
                    fill="#FF6B6B",
                    font=("Segoe UI", 14, "bold"),
                    justify="center",
                )

        canvas.bind("<Configure>", render_heatmap)
        canvas.after(100, render_heatmap)

    def build_ranking_card(self, parent):
        self.build_card_title(parent, "Ranking de zonas", "Ordenado por cruces detectados en cada área.")

        ranking_data = self.get_ranking_data()
        chart = tk.Canvas(parent, bg=PANEL_BG, highlightthickness=0, height=360)
        chart.pack(fill="both", expand=True, padx=18, pady=(0, 22))

        def render_chart(event=None):
            self.draw_horizontal_bar_chart(chart, ranking_data)

        chart.bind("<Configure>", render_chart)
        chart.after(100, render_chart)

    def build_time_card(self, parent):
        self.build_card_title(parent, "Flujo temporal", "Momentos de mayor presencia validada durante el video.")

        time_data = self.get_time_data()
        chart = tk.Canvas(parent, bg=PANEL_BG, highlightthickness=0, height=280)
        chart.pack(fill="both", expand=True, padx=18, pady=(0, 22))

        def render_chart(event=None):
            self.draw_line_chart(chart, time_data)

        chart.bind("<Configure>", render_chart)
        chart.after(100, render_chart)

    def build_stair_card(self, parent):
        self.build_card_title(parent, "Uso de escaleras", "Comparación de subidas y bajadas por escalera.")

        stair_data = self.get_stair_data()
        chart = tk.Canvas(parent, bg=PANEL_BG, highlightthickness=0, height=280)
        chart.pack(fill="both", expand=True, padx=18, pady=(0, 22))

        def render_chart(event=None):
            self.draw_grouped_bar_chart(chart, stair_data)

        chart.bind("<Configure>", render_chart)
        chart.after(100, render_chart)

    def build_store_flow_card(self, parent):
        self.build_card_title(
            parent,
            "Comparación de flujo entre tiendas",
            "Distribución porcentual del tránsito exterior por tienda. Si no hay zonas de frente de tienda, usa cruces de puerta como respaldo.",
        )

        store_flow_data = self.get_store_flow_data()
        chart = tk.Canvas(parent, bg=PANEL_BG, highlightthickness=0, height=360)
        chart.pack(fill="both", expand=True, padx=18, pady=(0, 22))

        def render_chart(event=None):
            self.draw_store_flow_donut_chart(chart, store_flow_data)

        chart.bind("<Configure>", render_chart)
        chart.after(100, render_chart)

    # ============================================================
    # DATOS PARA GRÁFICOS
    # ============================================================

    def get_ranking_data(self):
        if self.store_rows:
            rows = []
            for row in self.store_rows:
                name = row.get("store_name") or "Tienda"
                value = self.safe_int(row.get("exterior_traffic", 0))
                if value <= 0:
                    value = self.safe_int(row.get("door_crossings", 0))
                if value <= 0:
                    value = self.safe_int(row.get("estimated_entries", 0))
                rows.append((name, value))
            return sorted(rows, key=lambda x: x[1], reverse=True)[:8]

        rows = []
        source_rows = self.zone_metric_rows if self.zone_metric_rows else self.zone_rows
        for row in source_rows:
            name = row.get("zone_name") or row.get("zone_id") or "Zona"
            value = self.safe_int(row.get("entry_count", 0))
            rows.append((name, value))
        return sorted(rows, key=lambda x: x[1], reverse=True)[:8]

    def get_store_flow_data(self):
        rows = []

        # Fuente principal: store_metrics.csv
        if self.store_rows:
            for row in self.store_rows:
                name = row.get("store_name") or "Tienda"
                value = self.safe_int(row.get("exterior_traffic", 0))

                # Respaldo si todavía no marcaste frentes de tienda.
                if value <= 0:
                    value = self.safe_int(row.get("door_crossings", 0))
                if value <= 0:
                    value = self.safe_int(row.get("estimated_entries", 0))

                if value > 0:
                    rows.append((name, value))

        # Fuente secundaria: zone_metrics.csv o reporte_zonas.csv
        if not rows:
            source_rows = self.zone_metric_rows if self.zone_metric_rows else self.zone_rows
            for row in source_rows:
                zone_type = str(row.get("zone_type", "")).lower()
                if zone_type in ["frente_tienda", "puerta"]:
                    name = row.get("zone_name") or row.get("zone_id") or "Tienda"
                    value = self.safe_int(row.get("entry_count", 0))
                    if value > 0:
                        rows.append((name, value))

        return sorted(rows, key=lambda x: x[1], reverse=True)[:8]

    def get_time_data(self):
        rows = []
        for row in self.time_rows:
            label = row.get("time_label") or row.get("interval") or row.get("time_bin") or ""
            value = self.safe_int(row.get("visible_people_max", row.get("people_count", 0)))
            rows.append((label, value))
        return rows

    def get_stair_data(self):
        rows = []
        for row in self.stair_rows:
            name = row.get("stair_name") or row.get("zone_name") or row.get("stair_id") or "Escalera"
            up = self.safe_int(row.get("up_count", row.get("subidas", 0)))
            down = self.safe_int(row.get("down_count", row.get("bajadas", 0)))
            rows.append((name, up, down))
        return rows

    # ============================================================
    # DIBUJO DE GRÁFICOS
    # ============================================================

    def draw_empty_state(self, canvas, text="Sin datos registrados todavía"):
        canvas.delete("all")

        width = max(canvas.winfo_width(), 320)
        height = max(canvas.winfo_height(), 220)
        left = 48
        right = 28
        top = 28
        bottom = 46
        usable_w = width - left - right
        usable_h = height - top - bottom

        canvas.create_line(left, top, left, top + usable_h, fill="#30384A", width=1)
        canvas.create_line(left, top + usable_h, left + usable_w, top + usable_h, fill="#30384A", width=1)

        for i in range(5):
            y = top + int((usable_h / 4) * i)
            canvas.create_line(left, y, left + usable_w, y, fill="#1E2635", width=1)
            canvas.create_text(left - 10, y, anchor="e", text="0", fill="#7D8797", font=("Segoe UI", 10))

        zero_y = top + usable_h
        canvas.create_line(left, zero_y, left + usable_w, zero_y, fill=BLUE, width=3)

        for i in range(6):
            x = left + int((usable_w / 5) * i)
            canvas.create_oval(x - 4, zero_y - 4, x + 4, zero_y + 4, fill=BLUE, outline="")

        canvas.create_text(left, height - 18, anchor="w", text=text, fill=TEXT_MUTED, font=("Segoe UI", 11, "bold"))

    def draw_horizontal_bar_chart(self, canvas, data):
        canvas.delete("all")
        if not data:
            self.draw_empty_state(canvas)
            return

        width = max(canvas.winfo_width(), 320)
        height = max(canvas.winfo_height(), 220)
        left = 24
        right = 44
        top = 20
        row_height = max(32, min(46, int((height - 40) / max(len(data), 1))))
        max_value = max([value for _, value in data] + [1])
        bar_area_width = width - left - right - 150

        for i, (label, value) in enumerate(data):
            y = top + i * row_height
            short_label = label if len(label) <= 22 else label[:19] + "..."
            canvas.create_text(left, y + 16, anchor="w", text=short_label, fill=TEXT_MAIN, font=("Segoe UI", 11, "bold"))

            bar_x = left + 150
            bar_y = y + 7
            bar_h = 18
            bar_w = int((value / max_value) * bar_area_width)

            canvas.create_rectangle(bar_x, bar_y, bar_x + bar_area_width, bar_y + bar_h, fill="#202838", outline="")
            canvas.create_rectangle(bar_x, bar_y, bar_x + bar_w, bar_y + bar_h, fill=BLUE, outline="")
            canvas.create_text(bar_x + bar_area_width + 10, y + 16, anchor="w", text=str(value), fill=TEXT_MUTED, font=("Segoe UI", 11))

    def draw_line_chart(self, canvas, data):
        canvas.delete("all")
        if not data:
            self.draw_empty_state(canvas)
            return

        width = max(canvas.winfo_width(), 320)
        height = max(canvas.winfo_height(), 220)
        left = 50
        right = 24
        top = 20
        bottom = 45
        values = [value for _, value in data]
        max_value = max(values + [1])
        min_value = min(values + [0])
        usable_w = width - left - right
        usable_h = height - top - bottom

        canvas.create_line(left, top, left, top + usable_h, fill="#30384A", width=1)
        canvas.create_line(left, top + usable_h, left + usable_w, top + usable_h, fill="#30384A", width=1)

        for i in range(5):
            y = top + int((usable_h / 4) * i)
            canvas.create_line(left, y, left + usable_w, y, fill="#1E2635", width=1)

        points = []
        for i, (_, value) in enumerate(data):
            x = left + int((i / max(len(data) - 1, 1)) * usable_w)
            norm = (value - min_value) / max(max_value - min_value, 1)
            y = top + usable_h - int(norm * usable_h)
            points.append((x, y))

        for i in range(len(points) - 1):
            canvas.create_line(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1], fill=BLUE, width=3)

        for x, y in points:
            canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill=BLUE, outline="")

        canvas.create_text(left, top, anchor="e", text=str(max_value), fill=TEXT_MUTED, font=("Segoe UI", 10))
        canvas.create_text(left, top + usable_h, anchor="e", text=str(min_value), fill=TEXT_MUTED, font=("Segoe UI", 10))

    def draw_grouped_bar_chart(self, canvas, data):
        canvas.delete("all")
        if not data:
            self.draw_empty_state(canvas)
            return

        width = max(canvas.winfo_width(), 320)
        height = max(canvas.winfo_height(), 220)
        left = 42
        right = 24
        top = 20
        bottom = 55
        usable_w = width - left - right
        usable_h = height - top - bottom
        max_value = max([max(up, down) for _, up, down in data] + [1])
        group_w = usable_w / max(len(data), 1)

        canvas.create_line(left, top + usable_h, left + usable_w, top + usable_h, fill="#30384A", width=1)

        for i, (name, up, down) in enumerate(data):
            group_x = left + i * group_w
            bar_w = max(12, int(group_w * 0.22))
            up_h = int((up / max_value) * usable_h)
            down_h = int((down / max_value) * usable_h)
            x1 = int(group_x + group_w * 0.25)
            x2 = int(group_x + group_w * 0.55)
            base_y = top + usable_h

            canvas.create_rectangle(x1, base_y - up_h, x1 + bar_w, base_y, fill="#27AE60", outline="")
            canvas.create_rectangle(x2, base_y - down_h, x2 + bar_w, base_y, fill="#FF6B6B", outline="")

            short_name = name if len(name) <= 10 else name[:8] + "..."
            canvas.create_text(int(group_x + group_w / 2), base_y + 18, text=short_name, fill=TEXT_MUTED, font=("Segoe UI", 9))

        canvas.create_text(left + 10, top + 8, anchor="w", text="Verde: suben | Rojo: bajan", fill=TEXT_MUTED, font=("Segoe UI", 10))

    def draw_store_flow_donut_chart(self, canvas, data):
        canvas.delete("all")
        if not data:
            self.draw_empty_state(canvas, "Sin flujo por tienda registrado todavía")
            return

        width = max(canvas.winfo_width(), 520)
        height = max(canvas.winfo_height(), 300)
        total = sum(value for _, value in data)
        if total <= 0:
            self.draw_empty_state(canvas, "Sin flujo por tienda registrado todavía")
            return

        colors = ["#2F80ED", "#27AE60", "#F2994A", "#8E44AD", "#EB5757", "#00A8FF", "#F2C94C", "#56CCF2"]

        diameter = min(height - 70, width * 0.34, 240)
        x0 = 48
        y0 = int((height - diameter) / 2)
        x1 = x0 + diameter
        y1 = y0 + diameter

        start_angle = 90
        for index, (name, value) in enumerate(data):
            extent = (value / total) * 360
            canvas.create_arc(
                x0,
                y0,
                x1,
                y1,
                start=start_angle,
                extent=-extent,
                fill=colors[index % len(colors)],
                outline=PANEL_BG,
                width=2,
            )
            start_angle -= extent

        inner_margin = diameter * 0.28
        canvas.create_oval(
            x0 + inner_margin,
            y0 + inner_margin,
            x1 - inner_margin,
            y1 - inner_margin,
            fill=PANEL_BG,
            outline=PANEL_BG,
        )
        canvas.create_text(
            x0 + diameter / 2,
            y0 + diameter / 2 - 10,
            text=str(total),
            fill=TEXT_MAIN,
            font=("Segoe UI", 26, "bold"),
        )
        canvas.create_text(
            x0 + diameter / 2,
            y0 + diameter / 2 + 18,
            text="cruces",
            fill=TEXT_MUTED,
            font=("Segoe UI", 11, "bold"),
        )

        legend_x = int(x1 + 48)
        legend_y = 36
        row_h = 34

        canvas.create_text(
            legend_x,
            legend_y - 16,
            anchor="w",
            text="Distribución de flujo exterior",
            fill=TEXT_MAIN,
            font=("Segoe UI", 14, "bold"),
        )

        for index, (name, value) in enumerate(data):
            percent = value / total
            y = legend_y + index * row_h
            color = colors[index % len(colors)]
            short_name = name if len(name) <= 30 else name[:27] + "..."

            canvas.create_oval(legend_x, y, legend_x + 14, y + 14, fill=color, outline="")
            canvas.create_text(
                legend_x + 24,
                y + 7,
                anchor="w",
                text=short_name,
                fill=TEXT_MAIN,
                font=("Segoe UI", 11, "bold"),
            )
            canvas.create_text(
                width - 130,
                y + 7,
                anchor="w",
                text=f"{value} cruces",
                fill=TEXT_MUTED,
                font=("Segoe UI", 11),
            )
            canvas.create_text(
                width - 44,
                y + 7,
                anchor="e",
                text=self.format_percent(percent),
                fill=TEXT_MAIN,
                font=("Segoe UI", 11, "bold"),
            )

            bar_x = legend_x + 24
            bar_y = y + 19
            bar_w = max(120, width - bar_x - 64)
            canvas.create_rectangle(bar_x, bar_y, bar_x + bar_w, bar_y + 6, fill="#202838", outline="")
            canvas.create_rectangle(bar_x, bar_y, bar_x + int(bar_w * percent), bar_y + 6, fill=color, outline="")

    # ============================================================
    # DETALLE EXPANDIBLE
    # ============================================================

    def build_detail_section(self):
        section = ctk.CTkFrame(self.content, fg_color="transparent")
        section.pack(fill="x", padx=40, pady=(12, 40))

        title = ctk.CTkLabel(section, text="Detalle por zona / tienda", font=("Segoe UI", 28, "bold"), text_color=TEXT_MAIN)
        title.pack(anchor="w", padx=8, pady=(20, 12))

        rows = self.store_rows if self.store_rows else self.zone_metric_rows if self.zone_metric_rows else self.zone_rows
        if not rows:
            empty = ctk.CTkFrame(section, fg_color=PANEL_BG, corner_radius=22)
            empty.pack(fill="x", padx=8, pady=8)
            label = ctk.CTkLabel(
                empty,
                text="No hay datos para mostrar. Ejecuta primero un análisis de video.",
                font=("Segoe UI", 15),
                text_color=TEXT_MUTED,
            )
            label.pack(anchor="w", padx=22, pady=24)
            return

        for i, row in enumerate(rows):
            self.create_expandable_row(section, row, i)

    def create_expandable_row(self, parent, row, index):
        card = ctk.CTkFrame(parent, fg_color=PANEL_BG, corner_radius=20)
        card.pack(fill="x", padx=8, pady=7)

        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=18, pady=14)

        name = row.get("store_name") or row.get("zone_name") or row.get("zone_id") or row.get("name") or f"Elemento {index + 1}"
        zone_type = row.get("zone_type", row.get("type", "tienda"))
        entry_count = row.get("entry_count", row.get("exterior_traffic", row.get("estimated_entries", "0")))

        title = ctk.CTkLabel(header, text=name, font=("Segoe UI", 17, "bold"), text_color=TEXT_MAIN)
        title.pack(side="left")

        summary = ctk.CTkLabel(
            header,
            text=f"{zone_type}  |  valor principal: {entry_count}",
            font=("Segoe UI", 13),
            text_color=TEXT_MUTED,
        )
        summary.pack(side="left", padx=16)

        detail_frame = ctk.CTkFrame(card, fg_color=CARD_BG, corner_radius=16)

        def toggle():
            if detail_frame.winfo_ismapped():
                detail_frame.pack_forget()
                toggle_button.configure(text="Ver detalle")
            else:
                detail_frame.pack(fill="x", padx=18, pady=(0, 16))
                toggle_button.configure(text="Ocultar")

        toggle_button = ctk.CTkButton(
            header,
            text="Ver detalle",
            width=120,
            height=34,
            corner_radius=12,
            fg_color="#252B38",
            hover_color="#333B4C",
            font=("Segoe UI", 13, "bold"),
            command=toggle,
        )
        toggle_button.pack(side="right")

        details = self.format_row_details(row)
        detail_label = ctk.CTkLabel(
            detail_frame,
            text=details,
            font=("Segoe UI", 13),
            text_color=TEXT_MUTED,
            justify="left",
            wraplength=1000,
        )
        detail_label.pack(anchor="w", padx=18, pady=16)

    def format_row_details(self, row):
        lines = []
        for key, value in row.items():
            lines.append(f"{key}: {value}")
        return "\n".join(lines)

    # ============================================================
    # ACCIONES
    # ============================================================

    def refresh_data(self):
        for widget in self.content.winfo_children():
            widget.destroy()

        self.load_data()
        self.build_header()
        self.build_kpi_row()
        self.build_main_grid()
        self.build_detail_section()

    def go_back(self):
        if self.on_back:
            self.on_back()
        else:
            self.destroy()
