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
- Zona mas transitada: primera respuesta ejecutiva para redistribuir recursos o revisar layout.
- Maximo de personas: punto de mayor carga operativa visible.
- Horario peak y horario minimo: ventanas estimadas para comparar saturacion, baja actividad y posibles turnos.
- Flujo temporal: cambios por tramo del video usando etiquetas horarias estimadas desde el inicio del analisis o la carga.
- Superficie 3D zona-tiempo-eventos: exploracion manipulable de intensidad por zona y tramo horario.
- Detalle por zona: tabla auditable para analisis fino.

## Visualizaciones

- Heatmap: lectura rapida de concentracion espacial, con la misma jerarquia visual que el video.
- Video analizado: contexto visual directo para interpretar resultados y contrastar detecciones.
- Barras horizontales: ranking escaneable de zonas.
- Serie temporal: evolucion del comportamiento.
- Plotly 3D: superficie de actividad por zona y horario, util para detectar concentraciones y valles.
- Tabla de detalle: respaldo operativo y trazabilidad.

## Fuentes revisadas

- AWS for Industries describe casos de vision computacional en tiendas para heatmaps, patrones de trafico, gestion de colas, tiempos de espera, optimizacion de layout y dotacion.
  Fuente: https://aws.amazon.com/blogs/industries/transforming-stores-through-computer-vision-a-business-leaders-guide/
- Chart.js recomienda el eje temporal para mostrar fechas u horas distribuidas segun tiempo real y soporta timestamps, lo que calza con tramos de video convertidos a horarios estimados.
  Fuente: https://www.chartjs.org/docs/latest/axes/cartesian/time.html
- Plotly.js soporta graficos 3D y superficies manipulables, por eso se usa para una matriz zona-tiempo-eventos en vez de un grafico de coordenadas por frame.
  Fuente: https://plotly.com/javascript/ y https://plotly.com/javascript/3d-surface-plots/

## Criterio UX

La interfaz debe separar estado, evidencia y decision. El estado ya aparece como overline; las acciones principales son ver resultado y descargar reporte. La descarga se expresa como "reporte", aunque tecnicamente sea un paquete ZIP, porque el usuario piensa en entregables y no en formato de compresion.
