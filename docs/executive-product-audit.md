# Revision ejecutiva de producto - PIPOLMETRICS

## Criterio rector

PIPOLMETRICS debe funcionar como una aplicacion profesional de inteligencia operacional para espacios fisicos: captura, segmenta, analiza, audita y comunica evidencia. La interfaz no debe competir con los datos; debe acelerar decisiones para analistas, operaciones y equipos ejecutivos.

## Ajustes aplicados en esta revision

- La confirmacion de eliminacion se convirtio en popover contextual anclado al boton que dispara la accion.
- El panel de resultados elimina el KPI "Rango estimado" porque no agrega decision inmediata frente a peak, minimo, zona mas transitada y maxima carga.
- Las acciones que llevan a la pantalla de reportes ahora dicen "Reportes", no "Datos", para evitar una promesa rota de navegacion.
- El grafico 3D usa etiquetas horarias abreviadas y mayor separacion de ejes para evitar sobreposiciones.
- La carga de video ahora ofrece selector de archivo con menor jerarquia visual y zona drag and drop como camino rapido.

## Funciones que sobran o deben bajar de jerarquia

- Metricas derivadas sin decision directa en el primer pantallazo, como rangos horarios genericos, deben pasar a detalle o tooltip.
- Acciones duplicadas que dicen "Datos" pero abren "Reportes" erosionan confianza; cada etiqueta debe describir el destino real.
- Graficos 3D deben existir solo cuando agregan exploracion real. Si no hay matriz zona-tiempo-eventos, se muestra estado vacio y no una visualizacion decorativa.
- El panel de resultados no debe convertirse en una pagina infinita. La vista principal debe tener highlights y drill-down claro.

## Funciones que faltan para nivel enterprise

- Filtros globales por establecimiento, periodo, categoria, piso, zona y estado del analisis.
- Comparador entre analisis del mismo establecimiento para ver variacion porcentual, ranking historico y tendencia.
- Alertas operativas: peak anomalo, cola persistente, zona fria, sobreocupacion y caida de deteccion.
- Exportacion ejecutiva PDF/PPTX ademas del ZIP tecnico.
- Diccionario de metricas con definicion, formula, origen y confiabilidad.
- Roles: analista, supervisor, ejecutivo, administrador y auditor.
- Auditoria: quien cargo video, quien edito zonas, quien ejecuto analisis y quien descargo reporte.
- Versionado de zonas: guardar cambios de poligonos y permitir comparar resultados antes/despues.
- Calidad del video: scoring de resolucion, FPS, iluminacion, estabilidad y porcentaje de frames analizables.
- Comentarios o notas por insight para que el analista deje interpretaciones junto a la evidencia.
- Modo presentacion: dashboard limpio a pantalla completa para comites o clientes.

## Funciones avanzadas con sentido

- Reproduccion sincronizada: al hacer click en un peak temporal, saltar el video al tramo correspondiente.
- Brushing entre graficos: seleccionar una zona en ranking y resaltar heatmap, serie temporal y tabla.
- Simulador de layout: duplicar una zona y comparar escenarios de redistribucion de flujo.
- Indice de friccion: combinar permanencia, densidad y entradas para detectar cuellos de botella.
- Clustering de trayectorias: agrupar patrones de recorrido para detectar rutas dominantes.
- Narrativa automatica: generar resumen ejecutivo editable con hallazgos, riesgos y recomendaciones.

## Principios UX/UI aplicados

- Primero la decision, despues la evidencia, despues la auditoria.
- Las acciones primarias deben ser pocas y claras; acciones destructivas siempre contextuales y con menor jerarquia.
- Los dashboards deben contar una historia de un vistazo y mandar al detalle cuando el usuario necesite investigar.
- Los controles interactivos deben ser previsibles, visibles y consistentes.
- El drag and drop es util cuando reduce friccion en escritorio, pero debe convivir con el selector nativo de archivo.

## Fuentes base

- Nielsen Norman Group define dashboards como visualizaciones en una sola vista para informacion accionable de un vistazo y recomienda usar procesamiento visual preatencional.
  https://www.nngroup.com/articles/dashboards-preattentive/
- Tableau recomienda dashboards con interacciones descubribles, predecibles, layout logico y diseno simplificado para decisiones complejas.
  https://help.tableau.com/current/blueprint/en-us/bp_visual_best_practices.htm
- Microsoft Power BI recomienda contar una historia en una pantalla, evitar clutter y mantener solo informacion esencial en el dashboard.
  https://learn.microsoft.com/en-us/power-bi/create-reports/service-dashboards-design-tips
- MDN documenta el patron tecnico para drop zones de archivos con Drag and Drop API.
  https://developer.mozilla.org/en-US/docs/Web/API/HTML_Drag_and_Drop_API/File_drag_and_drop
