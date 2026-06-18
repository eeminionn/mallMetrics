# MallMetrics

Version original de Mall Metrics para revisar metricas de flujo peatonal en centros comerciales, reportes CSV y mapas de calor desde el navegador.

Branch principal de esta version: `MallMetrics`.

## Ejecutar la version Django

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py ensure_admin
python manage.py runserver
```

En esta copia local tambien puedes usar:

```bash
./scripts/run_mallmetrics_server.sh
```

Luego abre `http://127.0.0.1:8000/` e inicia sesion con:

- Usuario: `admin`
- Contrasena: `admin`

## Estado de la version

- `database.py` fue reemplazado en la version web por el sistema de usuarios de Django.
- `results_view.py` fue convertido a dashboard web con Chart.js.
- El editor Tkinter de zonas fue migrado a canvas web.
- La ejecucion YOLO fue separada en `analytics/analysis_engine.py`.
- Cada estudio guarda video, zonas, progreso y reportes en `AnalysisRun`.
- Los CSV y heatmaps se exportan por estudio en `media/analysis/<analysis_id>/`.
- El estudio de flujo UX esta en `docs/ux-flow-study.md`.
