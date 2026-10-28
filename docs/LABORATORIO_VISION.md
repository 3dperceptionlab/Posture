# Laboratorio de visión

## Uso

Inicia sesión como administrador y abre **Laboratorio de visión**. Elige nombre, operario opcional, frecuencia de análisis (5 fps por defecto, configurable 1–25) y confianza mínima (0,5–0,9). Los vídeos breves pueden analizarse a su frecuencia completa.

### Vídeo o carpeta desde el cliente

**Subir vídeos** permite uno o varios archivos; **Seleccionar carpeta** selecciona los vídeos de esa carpeta. Cada vídeo genera un trabajo independiente. Se aceptan MP4, MOV, MKV, AVI, WebM y M4V, hasta 2 GiB; la decodificación se comprueba durante el trabajo, no solo por la extensión. El límite de duración es una hora.

Las subidas se envían por bloques de hasta 4 MiB y se guardan en **`POSTURE/data/vision/uploads/<asset_id>/`** mediante un bind mount persistente. No forman parte de la imagen Docker. Una subida interrumpida aparece en la biblioteca y puede eliminarse; los endpoints de subida conservan el desplazamiento de bytes para clientes que implementen reanudación.

### Vídeo o carpeta del servidor

Copia los clips a **`POSTURE/examples/videos/`**, o a otra carpeta del proyecto. **Vídeos del servidor → Ubicación del servidor** permite elegir `POSTURE/examples` o la raíz `POSTURE`, importar un vídeo o analizar todos los vídeos de la carpeta y sus subcarpetas. El listado está limitado a 500 entradas por petición y 5.000 elementos explorados. El importador nunca elimina ni modifica estos originales.

Se habilitan exclusivamente estas dos raíces del proyecto en modo de solo lectura: rutas externas, escapes `..` y enlaces simbólicos que salgan de la raíz se rechazan. Las carpetas privadas (`.runtime`, `.git`, `backups`, `data`, archivos ocultos y dependencias) no se listan ni se admiten como origen. No se ofrece un explorador del sistema de archivos completo.

### Cámara del cliente

Consulta [CAMARA_HTTPS.md](CAMARA_HTTPS.md) para HTTPS o acceso por túnel SSH/localhost.

1. Elige **Cámara USB → Abrir cámara** y concede permiso.
2. Selecciona el dispositivo y uno de los modos:
   - **Solo capturar · procesar cuando lo indique** (**predeterminado**): guarda únicamente el vídeo original. No envía JPEG, no crea trabajos de inferencia, sesiones ni métricas, y no transcodifica el vídeo. Al terminar aparece en **Capturas pendientes de análisis**, con **Procesar secuencia**. Se conserva tras recargar o cerrar sesión. El botón utiliza el nombre, operario, fps de análisis y confianza elegidos al grabar.
   - **Procesar mientras se captura**: sube el vídeo original por bloques y JPEG normalizados en paralelo. La GPU procesa una cola limitada; la vista muestra el último frame procesado con sus métricas y su propio tiempo, evitando dibujar una pose antigua sobre la imagen actual.
   - **Procesar al finalizar la captura**: guarda la grabación original y la incorpora a la cola al detenerla.
3. Pulsa **Grabar** y luego **Detener y guardar**. La grabación no incluye audio. El navegador solicita 1080p/25 fps y puede negociar otra resolución según el dispositivo.

La captura requiere mantener la pestaña abierta. La interfaz impide salir durante la grabación y avisa al cerrar la pestaña. Si el navegador o la red se interrumpen, se conservan los bytes ya enviados; no se promete reparar automáticamente un contenedor de vídeo incompleto. Un trabajo de cámara que deje de enviar imágenes durante dos minutos se cierra con incidencia.

El modo vuelve a **Solo capturar** al recargar la página; durante la misma visita conserva tu selección. La biblioteca permite volver a analizar cualquier original guardado. El servicio de visión mantiene sus modelos cargados y realiza su calentamiento al arrancar, pero las capturas manuales no generan cómputo de pose ni métricas. El almacenamiento y la transferencia del vídeo siguen consumiendo los recursos necesarios para grabar.

## Resultados

- Cola, progreso, cancelación, errores y reanálisis con nuevos parámetros.
- Vídeos MP4/H.264 y WebM/VP9 de reproducción (sin audio), selección según los códecs del navegador, esqueleto superpuesto, ángulos y RULA/REBA por fotograma analizado.
- Evolución temporal, número de frames evaluables y máximos de puntuación. No se usa la media de puntuaciones ordinales para asignar una categoría.
- Descarga de original, CSV y JSON con los 133 puntos originales, confianza, selección de persona, métricas, versión y contexto.
- Estudio y sesión propios, integrados en MongoDB, CrateDB y Orion-LD/QuantumLeap por el mismo contrato interno que la telemetría. Robot y mesa quedan nulos: no se inventan estados de ROS.

Los originales, frames y resultados del laboratorio solo se obtienen desde los endpoints de visión con una cuenta administradora. Las métricas de las sesiones siguen siendo consultables según los permisos habituales del dashboard. El laboratorio usa `cell-vision-01`, nunca modifica la sesión activa ni los perfiles de `cell-lab-01`.

**Eliminar análisis** retira su sesión, resultados, fotogramas y reproducción; conserva el vídeo original en la biblioteca. **Eliminar vídeo** retira también sus análisis y el archivo si procedía del cliente. Los archivos importados de `examples` se conservan en disco. La retirada del histórico se completa de forma asíncrona como en las sesiones existentes. Se puede cancelar antes de borrar un vídeo con análisis activos.

## Motor y procedencia

Servicio Docker `vision`, imagen `Dockerfile.vision`. RTMLib **0.0.16**, detector **YOLOX-m** y estimador **RTMW-x** (familia RTMPose), salida COCO-WholeBody de 133 puntos. ONNX Runtime GPU **1.23.2**, CUDA 12/cuDNN 9. El arranque comprueba que ambas sesiones activan `CUDAExecutionProvider` y hace una inferencia de calentamiento; si CUDA falla, el servicio indica incidencia en lugar de ocultarlo usando CPU.

`POSTURE_GPU_DEVICE=0` selecciona actualmente la RTX 4090 de Clarke; puede configurarse por índice o UUID para otro equipo. Solo hay un trabajador de visión; no debe escalarse sin añadir arrendamientos distribuidos. Se reserva hasta 6 GiB de RAM de host y seis CPU; el modelo utiliza memoria de GPU adicional. El ajuste de fps permite adaptar el trabajo a una GPU menor.

Los dos modelos se descargan durante la construcción de imagen, desde las URLs versionadas de OpenMMLab indicadas en `scripts/download_vision_models.py`. Sus SHA-256 y versiones se conservan en `/opt/vision-models/manifest.json` y en los trabajos, por lo que una imagen ya construida puede analizar sin Internet. Para reproducir exactamente un despliegue debe conservarse también esa imagen o su digest; una URL versionada por sí sola no garantiza contenido inmutable.

Fuentes de los componentes y sus condiciones de distribución: [RTMLib](https://github.com/Tau-J/rtmlib), [RTMPose / RTMW](https://github.com/open-mmlab/mmpose/tree/main/projects/rtmpose), [ONNX Runtime](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html). El código de las herramientas y los modelos/datasets tienen procedencias distintas; el manifiesto identifica los pesos concretos utilizados.

## Geometría y límites

Cada imagen se redimensiona uniformemente y se centra con bandas negras en 1920×1080; el vídeo de reproducción emplea la misma transformación. No se deforma el cuerpo para ajustar la relación de aspecto. El contrato existente mantiene esas dimensiones normalizadas y ahora admite otras frecuencias de captura además de 25 fps.

Se adapta la detección al esquema `posture.body33.v1`. Los puntos de ojo interior/exterior no equivalentes quedan ausentes; no se rellenan con duplicados. Se conservan todos los puntos nativos aparte. Manos u otras articulaciones con baja confianza o fuera de imagen quedan ausentes para el cálculo; puede haber detección de persona sin RULA/REBA evaluables.

Si aparecen varias personas, se selecciona la caja de mayor área entre detecciones con confianza corporal suficiente; la confianza resuelve empates. No identifica a una persona por nombre ni asegura su identidad si alguien mayor se cruza en primer plano.

Los resultados siguen siendo **proyecciones 2D preliminares con supuestos explícitos**, especialmente en tomas diagonales y encuadres parciales. No hay profundidad medida, calibración gravitatoria ni SMPL en esta fase. El contexto ergonómico se congela al crear el trabajo y se reutiliza en todos sus frames, incluso si después se cambia la configuración global.

El tiempo mostrado es el desplazamiento dentro del vídeo. Las fechas de la sesión son las del análisis/captura iniciada en POSTURE, no una afirmación de cuándo se grabó un archivo importado. La selección automática no representa seguimiento de identidad.

### Sincronización temporal (`source-pts-v1`)

Los vídeos de cámara pueden declarar 29,97 fps y contener realmente unos 25 fotogramas por segundo, con intervalos variables. Por ello no se calcula la fecha de un frame como `índice / fps`: se utiliza su tiempo de presentación real, leído del decodificador después de obtener ese mismo frame. El primer tiempo se lleva a cero. Cada muestra conserva `source_frame_index`, `source_pts_s`, `offset_s` y la versión del reloj; el trabajo distingue los fps nominales de la media observada.

El muestreo usa intervalos del tiempo real del vídeo y salta los huecos de una pausa, sin intentar recuperar intervalos vacíos procesando muchos frames posteriores. Los MP4/WebM de reproducción conservan los tiempos originales y el número de fotogramas; no fuerzan una cadencia constante. La representación en el navegador sigue `requestVideoFrameCallback.mediaTime`, el tiempo del frame enviado al compositor, y no selecciona poses posteriores a ese instante.

Con análisis a 5 fps se conserva la última pose disponible entre muestras: puede verse un movimiento por pasos de unos 0,2 s, sin acumular adelanto por la duración del clip. Para mayor fluidez puede aumentarse la frecuencia de análisis. Las muestras de un análisis anterior a esta corrección se conservan como resultados anteriores; volver a analizar el original genera una sesión con el reloj corregido.

## Ejemplo público incluido

`examples/videos/mmpose-demo.mp4` es el clip de demostración público de [MMPose](https://github.com/open-mmlab/mmpose/blob/main/demo/resources/demo.mp4), descargado para verificar el flujo. Dura un segundo y contiene cinco frames de 960×540. No representa la tarea industrial ni la precisión ergonómica del piloto. Puede eliminarse desde el sistema de archivos cuando se disponga de material propio.
