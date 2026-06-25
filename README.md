# PIPOLMETRICS

Version generica de PIPOLMETRICS para revisar flujo de personas, reportes CSV y mapas de calor desde el navegador.

Branch principal de esta version: `PeopleMetrics`.

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
./scripts/run_peoplemetrics_server.sh
```

Luego abre `http://127.0.0.1:8001/` e inicia sesion con:

- Usuario: `admin`
- Contrasena: `admin`

## Estado de la version

- `database.py` fue reemplazado en la version web por el sistema de usuarios de Django.
- `results_view.py` fue convertido a dashboard web con Chart.js.
- El editor Tkinter de zonas fue migrado a canvas web.
- La ejecucion YOLO fue separada en `analytics/analysis_engine.py`.
- Cada analisis guarda video, zonas, progreso y reportes en `AnalysisRun`.
- Los CSV y heatmaps se exportan por analisis en `media/analysis/<analysis_id>/`.
- El estudio de flujo UX esta en `docs/ux-flow-study.md`.
