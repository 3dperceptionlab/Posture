# API implementada · POSTURE v0.1

**Integración vigente HMI/ROS por turnos e iteraciones:** [ROS_API.md](ROS_API.md), contrato 1.0. Las rutas de esta guía v0.1 se conservan para compatibilidad y laboratorio. La HMI gestiona los perfiles en operación real; la nueva adquisición guarda datos y solo procesa bajo petición con la configuración inicial.

Base: `http://SERVIDOR:8080/api/v1`. FastAPI expone el listado de rutas y cuerpos en `/api/docs`; `GET /api/v1/schema` devuelve el JSON Schema completo del intercambio.

## Autenticación

- Web: `POST /auth/login` con `username`/`password`; cookie HttpOnly y SameSite Strict, con caducidad de 12 horas.
- ROS: `Authorization: Bearer TOKEN`, donde TOKEN se toma de `POSTURE_INGEST_TOKEN` de `.env`.
- ROS puede consultar operarios/sesiones/células/perfiles, administrar parámetros por el contrato y enviar ingestión/imágenes. No puede administrar cuentas ni leer imágenes guardadas.
- Consulta: cuenta `viewer`, sin escritura, imágenes ni diagnóstico administrativo.

Las credenciales no se incorporan al JSON de pose ni al JavaScript del navegador.

## Secuencia para el equipo ROS

1. Obtener `GET /operators`; cada elemento contiene su perfil vigente.
2. La HMI identifica/selecciona al operario y ROS solicita `POST /sessions` con `operator_id`, `cell_id`, `name`, `condition` y `study_id` opcional. El servidor devuelve `session_id`. Una célula admite una sesión activa.
3. Consultar `GET /cells/cell-lab-01/desired-profile`, cada ~2 s o con ETag. Se devuelve perfil y sesión. `If-None-Match` permite respuesta `304`.
4. Validar/aplicar la nueva revisión localmente cuando corresponda. Enviar `profile_application` con estados por componente; una confirmación parcial no se acepta como completa.
5. Enviar `POST /ingest` con el mensaje v0.1. Cada componente lleva su propio timestamp. Emplear IDs y secuencias estables en reintentos.
6. Si se envía imagen, publicar primero sus metadatos `frame` dentro de telemetría y luego `PUT /frames/{frame_id}` con JPEG 1920×1080 y `Content-Type: image/jpeg`. `X-Content-SHA256` permite verificar su hash. No se requieren headers de sesión adicionales: se toman de los metadatos validados.
7. Consultar `GET /cells/cell-lab-01/summary?window_seconds=60` aproximadamente cada 30 s para información HMI. `preliminary_alert` solo se activa con datos recientes y tiempo observado suficiente; mostrar fecha, cobertura y carácter preliminar.
8. Enviar eventos de fase/ciclo cuando el origen disponga de ellos. La orden de ventosa no confirma físicamente agarre ni fin de acabado.
9. Al final del turno, enviar `shift_assessment` y cerrar mediante `POST /sessions/{id}/close` o evento `session_ended`.

La HMI se comunica con ROS; estas llamadas pertenecen al puente ROS, no exigen acceso directo de la HMI al servidor.

## Rutas principales

| Método / ruta | Uso |
| --- | --- |
| `GET /operators` | Operarios, perfil vigente y última confirmación. |
| `GET /profile-rules/table-height` | Regla provisional, factor, versión y límites de estatura. Lectura web/ROS autenticada. |
| `POST /operators` | Crear nombre y configuración inicial; devuelve perfil e IDs. |
| `PUT /operator-profiles/{id}` | Nueva revisión. `expected_revision` o `If-Match`; conflicto devuelve `412`. |
| `GET /operator-profiles/{id}/revisions` | Histórico de configuración. |
| `DELETE /operators/{id}` | Administrador; retira perfil y solicita borrado de datos asociados. |
| `GET /cells` | Células y asignación de sesión. |
| `GET /cells/{id}/desired-profile` | Configuración deseada para ROS, con ETag. |
| `GET /cells/{id}/summary` | Distribución temporal, ángulos medios, cobertura y aviso preliminar. |
| `GET /sessions` | Filtros `operator_id`, `study_id`, `from_date`, `to_date`; `limit` hasta 500. |
| `POST /sessions` | Iniciar sesión. |
| `POST /sessions/{id}/close` | Cerrar sesión; conserva datos. |
| `DELETE /sessions/{id}` | Ocultar de inmediato y purgar originales, métricas e imágenes en segundo plano. |
| `GET /sessions/{id}/timeline` | Últimas 600 muestras por defecto; `limit` hasta 2.000, `before` para consultar anteriores. |
| `GET /sessions/{id}/export.csv` | Exportación de todos los resultados de la sesión. |
| `POST /ingest` | Mensaje individual. |
| `POST /ingest/batches` | Objeto `batch_id` y array `messages` de 1–100; estado por mensaje. |
| `POST /studies` / `GET /studies` | Crear/listar estudios. |
| `GET /studies/{id}/frames` | Administrador; metadatos de imágenes disponibles. |
| `DELETE /studies/{id}` | Administrador; estudio y datos de sus sesiones. |
| `PUT /frames/{frame_id}` | Subir JPEG, máximo 8 MiB, vinculado a metadatos anteriores. |
| `GET /frames/{frame_id}` | Administrador; original conservado de estudio. |
| `GET /assessments` | Respuestas de autoevaluación; filtro `session_id`. |
| `GET /alerts` | Observaciones históricas de indicadores elevados. |
| `POST /alerts/{id}/acknowledge` | Marcar observación revisada. |
| `GET /context` / `PUT /context` | Contexto ergonómico versionado, valores y procedencia. |
| `GET /stats` / `GET /system` | Resumen y diagnóstico administrativo. |
| `POST /demo` | Administrador; datos sintéticos de laboratorio, sin mover hardware. |

## Estatura y altura de mesa

La interfaz pide **estatura en cm** al crear un operario; la API usa metros. Ejemplo mínimo de configuración (añadir `display_name` y `presentation_pose`):

```json
{"stature_m":1.75,"table_height_mode":"automatic"}
```

El servidor calcula `table_height_m = round(stature_m × 0.60, 3)` (**1,05 m** en el ejemplo) y guarda `table_height_rule: "stature-ratio-v1"`. Es una regla provisional del proyecto, no una recomendación ergonómica validada. El factor y los límites están centralizados en `backend/profile_height.py`. Se acepta estatura de 1–2,3 m y mesa de 0,2–2 m; ROS sigue validando los límites reales y aplicando la revisión en `next_safe_state`.

En modo automático, la altura enviada por el cliente se ignora y se recalcula en cada revisión. Para ajustar manualmente: `table_height_mode: "manual"` y `table_height_m`; se conserva la estatura y `table_height_rule` pasa a `null`. Cambiar la estatura manteniendo el modo manual no altera la mesa. Las revisiones históricas no se modifican.

Compatibilidad: los campos nuevos son opcionales en el contrato. Un cliente antiguo que envíe `table_height_m` sin indicar modo se interpreta como ajuste **manual**, conservando la estatura conocida; no se inventa la estatura de perfiles existentes. Si no se envían ni modo ni altura explícita, se mantiene el modo vigente; en perfiles nuevos con estatura se usa automático. `PUT` conserva la concurrencia mediante `expected_revision`/`If-Match` y requiere la pose como antes.

## Laboratorio de visión (administradores)

Todas las rutas de `/vision` requieren cookie de administrador; el token de ROS y las cuentas de consulta no dan acceso a vídeos ni a su administración.

| Método / ruta (bajo `/api/v1`) | Uso |
| --- | --- |
| `GET /vision/status` | Salud real del trabajador, CUDA/modelos, límites y URL HTTPS. |
| `GET /vision/certificate` | Raíz TLS pública para instalar en el cliente. |
| `GET /vision/files?root=examples&path=videos&recursive=false` | Vídeos/carpetas bajo `examples` o `root=project` para la raíz POSTURE; excluye carpetas privadas. |
| `POST /vision/import` | `{root:"examples",path:"videos/clip.mp4"}`; referencia al archivo del servidor. |
| `GET /vision/assets` | Biblioteca de originales y subidas incompletas. |
| `POST /vision/uploads` | `{name,size_bytes?,capture?}`; crea una subida y devuelve `asset_id`. No inicia inferencia. |
| `PUT /vision/uploads/{asset_id}?offset=0` | Cuerpo binario por bloques de hasta 8 MiB; desplazamiento exacto, máximo total 2 GiB. |
| `POST /vision/uploads/{asset_id}/complete` | Confirma la longitud y cierra la subida. |
| `DELETE /vision/assets/{asset_id}` | Borra los análisis asociados y el original si era una subida; exige trabajos terminados/cancelados. No elimina archivos de examples. |
| `POST /vision/jobs` | `{asset_id,name?,operator_id?,sample_fps:5,confidence:0.5,mode:"file"}`. Cada trabajo tiene sesión/estudio y contexto propios. |
| `GET /vision/jobs` / `GET /vision/jobs/{id}` | Listado y progreso, configuración y resumen. |
| `POST /vision/jobs/{id}/cancel` | Solicita cancelación conservando resultados parciales. |
| `DELETE /vision/jobs/{id}` | Retirada de análisis/sesión/estudio; mantiene el original. |
| `PUT /vision/jobs/{id}/frames/{sequence}?offset_s=0.2` | Solo en modo `live`: JPEG 1920×1080, hasta 8 MiB. Cola limitada, respuesta 429 si tiene 15 capturas pendientes. |
| `POST /vision/jobs/{id}/finish` | Termina captura `live` cuando el original ya está guardado. |
| `GET /vision/jobs/{id}/results?after=-1&limit=5000` | Muestras ordenadas por desplazamiento, paginación incremental; hasta 20.000 por petición. |
| `GET /vision/jobs/{id}/video?format=mp4` | MP4 de reproducción; `format=webm` para VP9. Ambos admiten Range. |
| `GET /vision/jobs/{id}/original` | Descarga del original. |
| `GET /vision/jobs/{id}/export.csv` / `export.json` | Resultados completos; JSON conserva puntos nativos, métricas y contexto. |

Para una cámara en directo se abre primero una subida de tamaño desconocido, se crea el trabajo con `mode:"live"` y se envían vídeo por bloques y JPEG por separado. Al detener, se espera el último bloque/captura, se completa la subida y se llama a `finish`. Los tiempos son relativos al inicio de la grabación. Puede indicarse `capture_fps` negociado por el dispositivo.

Para guardar sin analizar, enviar `capture: {mode:"manual", analysis_options:{name,operator_id,sample_fps,confidence,capture_fps}}` al abrir la subida; completar el vídeo y **no crear ningún trabajo**. Se guarda la intención y los parámetros, no una tarea pendiente en la GPU. `GET /vision/assets` conserva estos metadatos entre sesiones. Cuando el administrador decida procesar, `POST /vision/jobs` con `asset_id` hereda esas opciones; los parámetros explícitos de la petición tienen prioridad. `analysis_requested_at` marca los originales que ya han tenido una solicitud de análisis. Los otros modos de captura (`record`, `live`) documentan la intención; la interfaz inicia el trabajo al terminar o durante la captura, respectivamente. `/complete` nunca inicia análisis por sí solo.

Los clips offline admiten otras frecuencias además de 25 fps. El contrato ROS existente conserva 1920×1080 y ahora permite `frame.capture_fps` entre >0 y 240; los valores actuales de 25 siguen siendo válidos.

## Perfiles (detalle)

Alta: cuerpo con `display_name`, `cell_id` opcional, `presentation_pose` y configuración de mesa: `stature_m`/`table_height_mode: "automatic"`, o `table_height_m` para ajuste manual. La API asigna IDs/revisión. Los campos de perfil devuelto siguen el esquema `operator-profile.schema.json`.

Edición: mismos valores y `expected_revision` actual. Alternativamente `If-Match: "profile-id:revision"`. La API crea una revisión; no acepta elegir arbitrariamente su número. `table_height_m` es altura de superficie respecto al suelo.

La confirmación `applied` representa la configuración adoptada por la lógica ROS. No declara que el robot haya terminado de moverse o que la mesa haya llegado a la altura: eso se observa con telemetría y eventos.

## Persistencia y errores

- `202 accepted`: original guardado de forma duradera; otros pasos pendientes.
- `200 duplicate`: misma identidad y contenido ya recibidos.
- `409`: identidad, secuencia o imagen reutilizadas de forma incompatible.
- `412`: perfil/contexto editado concurrentemente.
- `422`: contrato, coordenadas, referencia o factores inválidos.
- `401/403`: autenticación/permiso.
- `413`: límites de tamaño.

El límite global de JSON es 2 MiB por petición y 256 KiB por mensaje. La API conserva originales; el trabajador realiza las etapas restantes con reintentos. Las incidencias permanecen consultables en Sistema. Los mensajes sobre una sesión eliminada no vuelven a crear sus datos.

Para pruebas con la configuración de ejemplo: crear IDs reales de operario/estudio/sesión y sustituirlos antes de enviar `examples/telemetry.json`. Si no hay estudio, `study_id` es nulo y `frame.retention_mode` es `transient`. Puntos no disponibles se envían como `missing` con coordenadas nulas.
