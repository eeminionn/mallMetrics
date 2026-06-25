# Estudio analitico de resultados - PIPOLMETRICS

## Enfoque

El panel de resultados se orienta a responder preguntas operativas sobre comportamiento de personas en zonas definidas por el analista. El producto deja de asumir tiendas o locales y trata cada poligono como una zona semantica libre: cajas, filas, mesas, accesos, pasillos, salas, puntos de espera o sectores criticos.

## Preguntas que debe responder

- Donde se concentra la actividad del espacio.
- Que zonas reciben mas cruces o permanencia.
- Como cambia el flujo durante el tiempo del video.
- Si existen zonas con sobrecarga, baja actividad o permanencia anomala.
- Que tan consistente es la lectura visual del heatmap con los eventos exportados.
- Que evidencia descargable existe para auditar o defender el analisis.

## Metricas priorizadas

- Personas validadas: volumen de tracks confirmados.
- Entradas a zonas: intensidad operacional por poligono.
- Actividad focal: resumen de interacciones relevantes en las zonas demarcadas.
- Permanencia promedio: senal de espera, friccion o interes.
- Ranking operativo: zonas con mayor actividad para priorizar revision.
- Flujo temporal: cambios por tramo del video.
- Mapa 3D de zonas: distribucion espacial interactiva de actividad en el frame.
- Detalle por zona: tabla auditable para analisis fino.

## Visualizaciones

- Heatmap: lectura rapida de concentracion espacial.
- Video analizado: contexto visual directo para interpretar resultados.
- Barras horizontales: ranking escaneable de zonas.
- Serie temporal: evolucion del comportamiento.
- Plotly 3D: exploracion espacial manipulable por el analista.
- Tabla de detalle: respaldo operativo y trazabilidad.

## Criterio UX

La interfaz debe separar estado, evidencia y decision. El estado ya aparece como overline; las acciones principales son ver resultado y descargar reporte. La descarga se expresa como "reporte", aunque tecnicamente sea un paquete ZIP, porque el usuario piensa en entregables y no en formato de compresion.
