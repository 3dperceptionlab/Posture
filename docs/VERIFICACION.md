# Verificación del despliegue

16 de octubre de 2026. Los resultados detallados y capturas se guardan localmente en `.runtime/` y no se incorporan a la imagen ni a Git.

## Comprobaciones realizadas

- **15 pruebas unitarias**: esquemas Draft 2020-12, ejemplos, coordenadas ausentes, frame equivocado, cuaternión, ventosa sin sensor, NaN, aplicación parcial, casos manuales de tablas RULA/REBA, umbral de carga de 2 kg y geometría degenerada.
- **33 comprobaciones de integración** contra el stack real: login, recepción duradera, idempotencia/conflictos, sesiones, revisiones y ETag, imágenes, separación admin/viewer, acceso ROS, métricas, archivo CrateDB, CSV, borrado y rechazo de captura tardía sobre una sesión eliminada.
- **Navegador Chromium**: login, generación sintética, lectura de métricas, reproducción, vista robot, edición de perfil, imágenes, autoevaluaciones, sistema y móvil. Sin excepciones JavaScript ni desbordamiento horizontal a 390 px.
- **Cadena FIWARE real**: suscripción NGSI-LD creada, entidades de ergonomía/robot/mesa recuperables y filas de QuantumLeap consultadas en `doc.etergonomicobservation`.
- **Caída y recuperación de CrateDB**: la API acepta un original de forma duradera y se obtienen métricas mientras el histórico está parado; tras arrancarlo se confirma el archivo del mensaje pendiente.
- Se han fijado imágenes por digest, dependencias Python y configuración del controlador `-mongocOnly` de Orion-LD para MongoDB 7.

## Copia/restauración

Se ha ejecutado `backup_docker` y restaurado su resultado en el proyecto aislado `posture-restore`, puerto 18081, con otros volúmenes y otra red. Se comprobaron login, 2 sesiones, 262 mensajes, 6 imágenes conservadas, métricas recuperadas, descarga de imagen, 262 originales en CrateDB y filas QuantumLeap, con todos los servicios disponibles. La instancia de prueba y sus volúmenes se eliminaron después; el despliegue principal permanece activo en 8080.

Evidencia: `.runtime/restore-validation.json`, `.runtime/backup-report.log` y `.runtime/restore-report.log`. La copia de respaldo se conserva bajo `backups/20261016T092553Z`. La restauración es una prueba en el mismo host y arquitectura; aún no se ha ensayado una migración física a otro equipo.

## Alcance de la evidencia

Estas comprobaciones validan comportamiento de software con datos sintéticos. No validan precisión clínica/ergonómica, no prueban integración con el ROS real y no instalan un modelo SMPL. La versión no depende de GPU y todavía no se ha medido una reconstrucción en RTX 4050. Las imágenes de laboratorio son dibujos generados, claramente identificados como sintéticos.
# Ampliación de visión y HTTPS · 22/10/2026

Se añadió **Laboratorio de visión** con vídeos subidos por bloques, carpetas del cliente, vídeos/carpetas de `examples` y cámara del navegador en modos directo y diferido. RTMW/YOLOX se ejecuta en un contenedor con acceso exclusivo a la RTX 4090 seleccionada. El arranque verifica sesiones CUDA y calentamiento; los modelos están incluidos en la imagen.

Verificación realizada:

- **20 pruebas unitarias**: las 15 anteriores y cinco nuevas de confinamiento de rutas/enlaces y carpetas privadas, límites/opciones, adaptación de manos/ojos al contrato, ausencia de detección y baja confianza. Registro: `.runtime/vision-unit.log`.
- **33 comprobaciones de regresión de la API** anteriores, incluidas ingestión, perfiles, permisos, archivo CrateDB y borrado. Registro: `.runtime/vision-regression.log`.
- **API de visión en GPU** con el clip público de MMPose: cinco frames reales detectados/evaluables, resultados preliminares, originales, exportación, Range HTTP 206 y comprobación de que no cambia la célula activa de ROS. Registro: `.runtime/vision-api-report.json`.
- **Diez flujos de navegador**: aviso de cámara bajo HTTP/certificado, subida y sincronización de vídeo/pose/métricas, móvil, carpeta del servidor, importación desde la raíz POSTURE con exclusión de carpetas privadas, HTTPS/cookie Secure, cámara directa, cámara diferida, permisos de consulta y errores de subida/vídeo corrupto. Se comprobó decodificación de vídeo, no solo la presencia del elemento HTML. Informe/capturas: `.runtime/vision-qa/`; script: `scripts/browser_vision_qa.cjs`.
- **TLS validado con la raíz local**, mediante `curl --cacert .runtime/posture-root.crt https://172.19.33.30:8443/healthz`. El navegador de QA omite la validación de confianza para probar la interfaz; la comprobación TLS anterior valida la cadena y la IP por separado.
- Los trabajos/cuentas/subidas creados por QA se eliminan. Se conserva un análisis etiquetado **Ejemplo público · MMPose (1 s)** para explorar la nueva vista. No es una grabación de operarios ni demuestra precisión en la tarea del piloto.

**Límites de la prueba:** cámara virtual de Chromium alimentada por ese vídeo real; no se ha probado una cámara USB física conectada al equipo del usuario ni instalado el certificado en dicho equipo. El rendimiento observado en la 4090 no acredita rendimiento en una 4050. Se valida el flujo de software y permisos, no la precisión ergonómica clínica/de campo. SMPL/3D permanece pendiente. Las nuevas rutinas de copia/restauración incluyen el bind mount de visión y la autoridad TLS; no se ha ejecutado una restauración de copia v2 sobre otro servidor.

# Corrección de sincronización «Con Robot» · 22/10/2026

Se reprodujo un adelanto acumulado al usar `índice / fps nominales` para fechar los fotogramas. El WebM de «Con Robot» declara **29,9700 fps**, pero contiene **711 frames** cuyo último PTS es **28,566 s** (media observada **24,8547 fps**). El reloj anterior situaba el último frame en **23,6903 s**: **4,875667 s** de adelanto acumulado.

Cambios:

- Lectura del timestamp real de presentación del mismo frame decodificado (`CAP_PROP_POS_MSEC`), normalizado respecto al primer frame; procedencia `source-pts-v1` e índice original guardados por muestra.
- Muestreo por intervalos de presentación, sin recuperar artificialmente intervalos vacíos tras pausas.
- MP4 y WebM conservan los tiempos variables. El MP4 evita que una lista de edición marque como descartable el último frame de duración no declarada.
- La interfaz usa el tiempo del frame enviado al compositor mediante `requestVideoFrameCallback`; la consulta periódica y los saltos del reproductor ya no lo sustituyen por un reloj adelantado ni seleccionan poses futuras.
- Reprocesado «Con Robot» con los mismos parámetros, operario, contexto y original (SHA-256 idéntico). El análisis previo se conserva como **Con Robot · anterior (fps nominales)**. El nuevo conserva **143 muestras a 5 fps** hasta **28,433 s**.

Pruebas:

- **25 pruebas unitarias correctas**, incluidas cinco nuevas sobre reloj variable/constante, origen distinto de cero, pausas y timestamps inválidos. Registro: `.runtime/timing-unit.log`.
- Comparación de los **711 timestamps** del original contra **cada frame de ambos previews**: mismo número de frames y **diferencia máxima 0 s** con la precisión del archivo. Todas las muestras se compararon con el PTS del índice original: **diferencia máxima 0 s**. Registro `.runtime/con-robot-timing-report.json`; herramienta `scripts/check_video_timing.py`.
- Navegador sobre el vídeo real: nueve saltos entre 0 y 28,4 s y reproducción continua a velocidad 1,5× (al menos 30 frames, pose visible en al menos el 95 %), sin poses futuras ni muestras fuera del margen de la cadencia de 5 fps y sin errores JavaScript. Registro/capturas: `.runtime/sync-qa/`; herramienta `scripts/browser_video_timing_qa.cjs`.

Esta comprobación valida la asociación temporal de imagen, pose y métricas; no cambia el estimador ni la validación ergonómica. A 5 fps la última muestra se mantiene hasta la siguiente, por lo que puede verse una cadencia de unos 0,2 s durante movimientos rápidos.

## Estatura y captura manual — 26 de octubre de 2026

Desplegadas las imágenes actualizadas de API, trabajador y visión. API y GPU saludables; comprobación HTTPS con el certificado raíz local correcta.

- **30 pruebas unitarias correctas**: contrato y métricas, reloj de vídeo, validación de opciones de captura, cálculo automático, altura manual, compatibilidad con perfiles anteriores y rechazo de estaturas/alturas inválidas. Registro: `.runtime/height-capture-unit.log`.
- **Prueba de navegador sobre el despliegue** (`scripts/browser_height_capture_qa.cjs`): creación con estatura obligatoria; previsualización 175 cm → 105 cm; cálculo del servidor y nueva revisión a 180 cm → 108 cm; ajuste manual conservado tras cambiar estatura; conflicto de revisión y API antigua.
- **Solo capturar por defecto**: cero peticiones de creación de análisis y cero envíos JPEG durante y después de grabar. Original guardado y ningún trabajo asociado. Tras recargar, el botón **Procesar secuencia** inicia el análisis en GPU con el nombre, operario, frecuencia y confianza originales.
- **Procesar al finalizar**: no crea trabajo durante la grabación y genera resultados después de detenerla. **Procesar mientras se captura**: mantiene el envío de fotogramas y la inferencia durante la grabación. Los tres trabajos terminaron con fotogramas procesados.
- Sin errores JavaScript ni desbordamiento en viewport móvil de 390 px. Capturas y reporte de cinco grupos de comprobaciones: `.runtime/height-capture-qa/`.

La cámara de esta prueba es una entrada simulada de Chromium alimentada con el clip público de MMPose; no se ha probado un dispositivo USB físico. Se eliminaron únicamente los originales, trabajos y operarios creados por estas pruebas; no se cambió la sesión de la célula física.

## Trabajo en entorno real · turnos e iteraciones — 26 de octubre de 2026

API, trabajador y GPU desplegados en Docker. La adquisición de producción usa sus propias políticas y registros; el laboratorio y los perfiles locales de prueba se mantienen. Los nuevos operarios HMI se muestran como identidades recibidas, sin aplicación de perfiles por parte de los endpoints de adquisición.

- **36 pruebas unitarias correctas**, incluidas seis de contrato real: 33 joints, UTC canónico, valores no finitos, geometría desconocida sin puntuaciones, conversión explícita ROS/óptica y milímetros, y formularios versionados. Registro: `.runtime/real-unit.log`.
- **58 comprobaciones de integración** (`tests/real_integration.py`) sobre la pila desplegada: autenticación, reintentos e identidades, IDs correlativos, cierre automático por la siguiente pieza, resumen Quality Check/error, etiquetas, formularios pre/post, MP4 por bloques y SHA-256, permisos sobre originales, archivo en CrateDB y análisis ROS/GPU asociados a turno/pieza. Registro: `.runtime/real-integration.log`.
- Confirmado que la política inicial **manual** no crea trabajos ni métricas al recibir frames o completar vídeo. Verificadas las políticas ROS `live` y `after_iteration`, y análisis automático del MP4 solo cuando está completo y la pieza cerrada. Estas políticas se ejercitaron únicamente en iteraciones QA aisladas.
- **7 grupos de pruebas de navegador** (`scripts/browser_real_qa.cjs`): imágenes y perfiles HMI, etiquetas y filtros, cálculo manual por ambas fuentes, reproducción WebM con muestra no futura, formularios/turnos, configuración independiente, perfiles locales y cámara conservados, y viewport móvil de 390 px sin desbordamiento ni errores JavaScript. Reporte y capturas: `.runtime/real-browser-qa/`.
- Se corrigió una carrera al cerrar el formulario de etiquetas antes de terminar de actualizar la página; el diálogo ahora se cierra después de completar la actualización.
- OpenAPI **3.1.0**, 17 rutas de producción en el artefacto exportado, referencias internas resueltas, seguridad administrativa explícita y cinco ejemplos JSON validados contra los modelos. Entregables: `docs/ROS_API.md`, `docs/ros/openapi.json`, `docs/ros/sample.schema.json` y `examples/ros/`.

Las pruebas usaron una fuente y célula `qa-real-*`, pose/imagen sintéticas y el clip público de MMPose. No validan precisión ergonómica, convenciones de un detector ROS real ni un robot físico. El formulario definitivo y las convenciones 3D siguen pendientes de elección; los valores desconocidos se conservan sin interpretarlos. La limpieza elimina solo los registros/archivos QA asociados y conserva los contadores, por lo que pueden quedar huecos en los IDs.

## Estilos de la documentación de API — 26 de octubre de 2026

El CSS externo de Swagger estaba bloqueado por `style-src 'self'`. `/api/docs`
ahora sirve Swagger UI **5.34.0** desde `/assets/vendor/swagger-ui/`, con licencia
incluida y favicon local, sin ampliar los permisos de la política de seguridad.
Se reconstruyó y desplegó el contenedor API.

Verificación con Chromium en HTTP y HTTPS, bloqueando las conexiones externas:
CSS aplicado, 85 operaciones visibles (incluidos turnos e iteraciones), diálogo
de autorización funcional y cero peticiones externas, errores JavaScript o
respuestas HTTP fallidas. Informe y capturas: `.runtime/api-docs-qa/`.
El certificado HTTPS se comprobó además con la raíz local mediante `curl`;
API saludable. No se modificaron datos durante estas comprobaciones.

## Autenticación opcional de desarrollo — 28 de octubre de 2026

Configurado `POSTURE_AUTH_MODE=development` en este servidor. El valor
predeterminado del código, `.env.example` y nuevas instalaciones es `strict`.
API reconstruida y desplegada; tokens y cuentas existentes conservados.

- **6 pruebas de autenticación**: modo estricto por defecto, configuración
  inválida, identidad anónima administrativa identificada como `development`,
  rechazo de credenciales incorrectas/caducadas, conservación de permisos
  viewer/device, cabeceras de advertencia y cambio de seguridad OpenAPI según
  el modo. Registro: `.runtime/auth-mode-unit.log`.
- **21 comprobaciones sobre la API desplegada**: sin credenciales, lectura de
  configuración, creación de turno e iteración, envío multipart de pose/JPEG,
  descarga administrativa del JPEG, etiquetado y cierre de pieza/turno. También
  se verificó el rechazo de token/cookie incorrectos y la presencia de avisos.
  Registro: `.runtime/auth-mode-qa/api.log`. Eliminados los registros, imágenes
  y archivos FIWARE/CrateDB de esta prueba; contadores conservados.
- Cliente ROS Python ejecutado sin `POSTURE_INGEST_TOKEN`: consulta correcta de
  formularios y advertencia registrada, sin cambiar el JSON de respuesta.
  Registro: `.runtime/auth-mode-qa/client.log`.
- Navegador HTTPS sin sesión: dashboard accesible y aviso de desarrollo
  visible, viewport móvil de 390 px sin desbordamiento, aviso en Swagger y sin
  errores JavaScript. Reporte/capturas: `.runtime/auth-mode-qa/`.
- Advertencia de arranque presente en logs y `/healthz` correcto con validación
  del certificado raíz local.

Para exigir credenciales de nuevo: establecer `POSTURE_AUTH_MODE=strict` en
`.env` y ejecutar `docker compose up -d --no-build api`.

