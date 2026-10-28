# POSTURE

Servidor Docker para datos de pose humana, UR3, mesa de trabajo, perfiles, sesiones, estudios, autoevaluaciones y ergonomía preliminar.

## Inicio

```bash
cd /home/dmulero/workspace/POSTURE
./launch_docker
```

Web y API: **http://localhost:8080**. Desde otro equipo, sustituir localhost por la dirección del servidor. En este despliegue: **http://172.19.33.30:8080**. Documentación interactiva: `/api/docs`.

**Vídeos y cámara:** abre **Laboratorio de visión**. Puedes subir vídeos/carpetas desde el cliente, analizar los de `examples/videos/` o grabar la cámara USB del cliente. Acceso seguro: **https://172.19.33.30:8443/#vision**. Para la cámara, instala la raíz local indicada en [Cámara y HTTPS](docs/CAMARA_HTTPS.md), o utiliza el túnel SSH/localhost descrito allí.

**HMI / ROS en producción:** abre **Trabajo en entorno real** (`/#real`). Turnos y piezas tienen IDs correlativos, etiquetas y formularios previos/posteriores. Se reciben pose + JPEG y MP4 completo; por defecto solo se guardan. Las opciones de análisis de producción son independientes del laboratorio. Guía vigente para el equipo ROS: **[ROS_API.md](docs/ROS_API.md)**, con OpenAPI 3.1, ejemplos y cliente Python. Los perfiles gestionados por la HMI se muestran como datos recibidos; las herramientas locales de perfiles y simulación siguen disponibles.

**Autenticación configurable:** `POSTURE_AUTH_MODE=development` en `.env` permite usar la API sin token ni sesión, con permisos de administrador de pruebas y advertencias en las respuestas, los logs de arranque y el dashboard. Los tokens y cuentas existentes siguen funcionando; las credenciales incorrectas se rechazan. Para el despliegue, usar `POSTURE_AUTH_MODE=strict` (valor predeterminado) y recrear el contenedor API. Véase [autenticación de desarrollo](docs/ROS_API.md#autenticación-durante-el-desarrollo).

En el primer inicio se generan credenciales aleatorias:

- Administrador: usuario `admin`; contraseña en `.runtime/admin-credentials.txt`.
- Credencial del puente ROS: `POSTURE_INGEST_TOKEN` en `.env`.

Estos archivos tienen permisos `600`, están excluidos del Git y de la imagen. No hay contraseña predeterminada compartida. Puedes cambiar la contraseña desde **Sistema**; la variable inicial solo crea la cuenta si todavía no existe.

No se necesita instalar Python o Node en el host. El script reconoce el wrapper Docker autorizado de este servidor; en otros equipos utiliza Docker normalmente.

El servicio de visión necesita una GPU NVIDIA, su controlador y NVIDIA Container Toolkit. En Clarke se ha comprobado la RTX 4090. `POSTURE_GPU_DEVICE` permite seleccionar otra GPU. Las primeras construcciones descargan las dependencias CUDA y los modelos; los análisis posteriores no necesitan Internet. Para usar solo la ingestión ROS sin visión, arranca los servicios `api worker mongo orion crate quantumleap https` con Compose, omitiendo `vision`.

```bash
./launch_docker status
./launch_docker logs worker
./launch_docker stop
./launch_docker up
./launch_docker down
./launch_docker test
```

`stop` y `down` conservan los volúmenes. Cambiar `POSTURE_PORT`/`POSTURE_BIND` en `.env` y ejecutar `up` permite modificar la escucha. Para publicar detrás de un proxy HTTPS, configurar `POSTURE_COOKIE_SECURE=true` y reenviar el host original. Las bases de datos no publican puertos en el host.

## Aplicación disponible

- Inicio de sesión, cuentas de administración/consulta y cambio de contraseña.
- Vista general, selección de sesión, gráficos de RULA/REBA y cobertura de detección.
- Reproducción de esqueleto 2D; vista de TCP en XY/XZ y rotaciones articulares.
- Operarios y perfiles versionados; control de ediciones concurrentes y confirmación de aplicación por robot/mesa.
- Inicio/cierre de sesiones, filtros, eventos de ciclo, exportación CSV y borrado administrativo.
- Estudios con conservación manual de imágenes; originales JPEG de estudio solo para administradores.
- Autoevaluación propia al final de turno, recibida por API y consultable en web. Incluye formulario web de laboratorio.
- Contexto de tarea editable/versionado con factores provisionales autorizados y procedencia de cada dato.
- Indicadores RULA/REBA preliminares con componentes, calidad, supuestos y versión. Nunca se presentan como una evaluación validada.
- Resumen temporal para ROS/HMI con distribución de puntuaciones, duración observada, huecos y señal de revisión.
- Datos sintéticos mediante **Simulación de laboratorio**, identificados como simulación. Las imágenes generadas son dibujos sintéticos, no fotografías de personas.
- Diagnóstico de servicios, trabajador, archivos pendientes y errores de entrega.
- Laboratorio de visión con RTMW/RTMPose en GPU, subida de vídeos por bloques, importación de carpetas del servidor, cámara inmediata/diferida y reproducción de pose sobre vídeo sincronizada con RULA/REBA. [Uso y límites](docs/LABORATORIO_VISION.md).

## Componentes

| Servicio | Función | Persistencia |
| --- | --- | --- |
| `api` | FastAPI, autenticación, ingestión y web estática | MongoDB y volumen de imágenes |
| `worker` | Métricas, archivo y publicación con reintentos; purga solicitada | Estados duraderos en MongoDB |
| `vision` | Detección YOLOX/RTMW en RTX 4090, trabajos de vídeo y cámara | MongoDB, imágenes y `data/vision` |
| `https` | Caddy, acceso TLS local para la cámara del navegador | Autoridad/certificados en `posture_caddy_data` y `posture_caddy_config` |
| `mongo` | Base `posture_app` y bases internas del broker separadas | `posture_mongo` |
| `orion` | Orion-LD 1.12.0, contexto NGSI-LD de ergonomía/robot/mesa | MongoDB |
| `quantumleap` | QuantumLeap 1.0.0, histórico de notificaciones de ergonomía | Tablas propias en CrateDB |
| `crate` | CrateDB 5.10.16, originales canónicos y series FIWARE | `posture_crate` |

La web se sirve desde la misma API y origen, sin CDN para sus recursos. Todos los contenedores pertenecen a la red `posture_posture`. Se exponen `8080` (HTTP) y `8443` (HTTPS); las bases de datos y la GPU no publican puertos. Las imágenes de los servicios y el intérprete están fijadas por digest; las dependencias de la API están fijadas en `requirements.lock`, y las principales de visión en `requirements-vision.txt` y `Dockerfile.vision`.

Orion arranca con `-mongocOnly`: la imagen publicada utiliza de otro modo un controlador legado que falla con MongoDB 7. Se ha verificado la creación de suscripción, publicación y recuperación de contexto, así como filas reales de QuantumLeap en CrateDB.

La aplicación confirma recepción después de persistir en MongoDB con journal. El trabajador archiva JSON original en `doc.posture_raw` con ID único y publica contexto reciente hacia Orion-LD; la suscripción envía métricas a QuantumLeap. Datos atrasados permanecen en el histórico original sin sustituir un contexto más nuevo.

La consulta detallada de la web usa MongoDB para preservar tipos y procedencia exacta; CrateDB conserva el archivo canónico y el histórico FIWARE. Un `202` de ingestión no significa que las otras etapas hayan terminado. **Sistema** muestra pendientes y confirmaciones de archivo.

Los reenvíos son idempotentes para los originales. Una repetición de notificación FIWARE puede producir otra fila temporal de QuantumLeap; para análisis reproducible usar el original identificado por `message_id`, no contar notificaciones como muestras independientes.

## Integración ROS/HMI

Recorrido: **HMI → PC ROS → API**. El equipo ROS integra el envío JSON y los endpoints de sesiones/perfiles; el servidor no ejecuta ROS ni envía trayectorias de control.

- [Guía de integración implementada](docs/API.md).
- [Contrato v0.1 y convenciones](docs/CONTRATO_ROS_API.md).
- [Esquema de mensajes](schemas/messages.schema.json).
- [Ejemplo completo de 33 puntos + robot + mesa](examples/telemetry.json).
- [Perfil](examples/operator-profile.json), [confirmación](examples/profile-application.json), [formulario](examples/shift-assessment.json).

Los IDs de `examples/` son ficticios. Para utilizarlos, crear operario/estudio/sesión por API y sustituir referencias. La pose del robot del ejemplo no es una consigna aprobada para movimiento.

## Métricas y procesamiento de imágenes

Ver [métodos y límites](docs/METRICAS.md). Se calculan métricas desde puntos recibidos por ROS o detectados en el [laboratorio de visión](docs/LABORATORIO_VISION.md). Esta entrega incorpora detección 2D YOLOX/RTMW en CUDA; **SMPL y la reconstrucción 3D monocular siguen pendientes**.

Objetivo de despliegue: 8 núcleos, 32 GB de RAM, una GPU del nivel de RTX 4050. La ingestión y las métricas desde ROS no necesitan GPU; el nuevo servicio de visión utiliza CUDA. Clarke tiene actualmente una RTX 4090 y una TITAN V; se usa la 4090. El rendimiento debe medirse también en el equipo objetivo.

Los resúmenes para HMI se pueden consultar cada 30 s. Las métricas individuales se procesan al recibir datos. El resumen no prolonga una postura a través de huecos superiores a 2 s y no genera aviso de actualidad con datos de más de 120 s. Los registros de alerta en la web se presentan como observaciones históricas con su fecha.

## Copia, traslado y restauración

```bash
./backup_docker
```

Genera `backups/FECHA_UTC/`: volúmenes MongoDB/CrateDB/imágenes, autoridad TLS, archivos de `data/vision`, código, configuración y sumas SHA-256. Detiene brevemente los servicios del proyecto para tomar una copia consistente y vuelve a arrancar los que estaban activos. El directorio es privado porque contiene credenciales y datos. Los vídeos importados de `examples` se incluyen en el archivo de código; los vídeos subidos y sus derivados se incluyen en `vision.tar.gz`.

En otro servidor con Docker Compose:

1. Extraer `source.tar.gz` en una carpeta vacía y copiar el directorio de backup.
2. Ejecutar `./restore_docker /ruta/al/backup --replace`.
3. Acceder con las credenciales de la copia; ajustar dirección/puerto antes de abrir el acceso a ROS.

`--replace` sustituye los datos del proyecto destino. Para ensayo aislado en el mismo host:

```bash
POSTURE_PROJECT=posture-restore POSTURE_PORT=18081 POSTURE_TLS_PORT=18443 ./restore_docker /ruta/al/backup --replace
```

`restore_docker` verifica SHA-256 antes de reemplazar volúmenes. Las copias antiguas permanecen hasta que se eliminen manualmente; un borrado desde web afecta al despliegue activo, no a copias guardadas fuera de él.

Un proyecto de restauración con nombre distinto utiliza `data/<proyecto>/vision` para separar el bind mount del original. `POSTURE_VISION_DIR` permite elegir una ruta explícita. Las copias v1, previas a visión/HTTPS, siguen siendo aceptadas; no contienen vídeos ni autoridad TLS de esta ampliación.

## Pruebas

```bash
./launch_docker test
docker compose exec -T api python -m tests.integration
```

La integración usa registros QA identificados y elimina sus propios operarios/cuentas/sesiones. Necesita una célula sin sesión activa; no ejecutarla sobre una prueba industrial en curso. Las pruebas de interfaz usan un contenedor Playwright independiente; sus capturas locales están en `.runtime/qa`.

Ver [registro de verificación](docs/VERIFICACION.md). La validación de tablas y contrato no sustituye la calibración de la cámara ni la validación ergonómica de campo.
