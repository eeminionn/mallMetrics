# Estudio de flujo UX - People Metrics

## Objetivo del producto

People Metrics se reorganiza como una herramienta web para analistas de datos operativos. El foco no es solo ejecutar YOLO, sino convertir un video en un estudio auditable: zonas, eventos, metricas, heatmap y reportes.

## Usuario principal

Analista de datos u operaciones de espacios fisicos que necesita:

- Cargar videos por sector, fecha u horario.
- Definir zonas de interes: puerta, acceso, escalera, salida y zona general.
- Ejecutar analisis reproducibles.
- Revisar metricas accionables.
- Auditar CSV y eventos cuando un resultado requiere explicacion.

## Flujo propuesto

1. Nuevo estudio
   - El usuario registra nombre y video.
   - La app extrae metadatos y frame base.

2. Zonas
   - El usuario dibuja rectangulos sobre el frame.
   - Cada zona tiene tipo, color semantico y nombre.
   - La app valida tamano minimo y coordenadas.

3. Analisis
   - El usuario ejecuta YOLO.
   - La interfaz muestra progreso, frames procesados y personas validadas.
   - El proceso escribe salidas por estudio, no como archivos globales.

4. Resultados
   - El usuario ve KPIs, heatmap, ranking, serie temporal, tiendas y escaleras.
   - Las tablas permiten trazabilidad por zona/evento.

5. Reportes
   - El usuario audita disponibilidad de CSV y eventos exportados.

## Casos de uso cubiertos

- Crear estudio desde cero.
- Retomar un estudio y editar zonas.
- Ejecutar analisis desde web.
- Cancelar un analisis en curso.
- Consultar resultados de estudios completados.
- Auditar reportes generados.
- Usar Django Admin para inspeccion interna.

## Criterios visuales

- Paleta base neutra para largas sesiones de analisis.
- Acentos por semantica: azul accion, cian validacion, ambar oportunidad, rosa alerta y azul claro distribucion.
- Iconografia Lucide para acciones y estados.
- Chart.js para graficos consistentes y responsivos.
- Layout denso y escaneable, sin composicion de landing page.

## Decisiones tecnicas

- `AnalysisRun` encapsula video, zonas, estado, progreso y resultados.
- Los reportes viven en `media/analysis/<analysis_id>/`.
- OpenCV y Ultralytics se cargan de forma diferida para no romper el sitio si faltan dependencias.
- El editor de zonas usa canvas web, reemplazando la interaccion Tkinter.
- El motor YOLO fue separado en `analytics/analysis_engine.py`.
