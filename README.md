# mallMetrics

Aplicacion migrada a Django para revisar metricas de flujo peatonal, reportes CSV y mapas de calor desde el navegador.

## Ejecutar la version Django

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py ensure_admin
python manage.py runserver
```

Luego abre `http://127.0.0.1:8000/` e inicia sesion con:

- Usuario: `admin`
- Contrasena: `admin`

## Estado de la migracion

- `database.py` fue reemplazado en la version web por el sistema de usuarios de Django.
- `results_view.py` fue convertido a dashboard web con Chart.js.
- El editor Tkinter de zonas fue migrado a canvas web.
- La ejecucion YOLO fue separada en `analytics/analysis_engine.py`.
- Cada estudio guarda video, zonas, progreso y reportes en `AnalysisRun`.
- Los CSV y heatmaps se exportan por estudio en `media/analysis/<analysis_id>/`.
- El estudio de flujo UX esta en `docs/ux-flow-study.md`.
