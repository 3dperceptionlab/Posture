# Motor ergonómico preliminar

Implementación: `backend/metrics.py`, versión `posture-ergonomics-0.1.0`. Se han implementado tablas A/B/C de RULA y REBA y factores contextuales, además de geometría sobre los puntos recibidos. Se conservan ambos lados y se muestra la mayor puntuación disponible por método; no se promedian puntuaciones ordinales para asignar una categoría.

Fuentes de los métodos y tablas:

- McAtamney y Corlett, 1993; [ficha RULA de Cornell](https://www.ergo.human.cornell.edu/Pub/AHquest/RULAworksheet.pdf).
- Hignett y McAtamney, 2000; [material REBA de Cornell](https://www.ergo.human.cornell.edu/Pub/AHquest/Cornell_REBA.pdf).

## Procedencia

Cada resultado conserva versión del algoritmo, revisión y copia completa del contexto, tiempos de observación/procesamiento, ángulos, componentes, lado, cobertura y lista de supuestos. El contexto inicial está en `examples/task-context.provisional.json` y puede editarse desde Sistema. La edición se aplica a nuevas observaciones; no sobrescribe resultados existentes.

La masa aproximada de 2 kg y las dimensiones 0,30×0,60 m proceden del usuario. Trabajo de pie, apoyos, agarre regular, giro de muñeca, repetición y cargas por fase son provisionales. El esfuerzo de retirada de rebaba no se deduce de la masa de la pieza. Los 2 kg están en un umbral relevante de RULA; el motor no redondea la carga antes de elegir la rama.

El inicio de fase reportado se asocia por tiempo a la muestra para seleccionar el proxy de carga. Si no hay eventos, se utiliza el contexto de acabado y se deja constancia de esa fase/supuestos. La incorporación tardía de eventos no recalcula silenciosamente resultados ya emitidos.

## Geometría de esta versión

- Se usan puntos por encima de confianza 0,5, o sin confianza declarada pero identificados por el origen como utilizables.
- Preferencia por 3D de cámara óptica cuando existe y su interpretación está declarada; en caso contrario, coordenadas de imagen en píxeles.
- Tronco: dirección entre centro de caderas y hombros respecto a la vertical de imagen/cámara. Umbral de 5° como zona neutral de procesamiento para reducir ruido; no representa una medida validada de extensión/flexión.
- Cuello: aproximación desde centro de hombros a cabeza respecto al tronco; no mide por sí sola la orientación anatómica craneocervical.
- Brazo: relación con dirección del tronco; codo: flexión geométrica; muñeca: aproximación desde antebrazo y punto índice.
- Elevación/abducción de hombro, desviación/giro de muñeca, rotación corporal y otros modificadores no observados se consideran supuestos explícitos, no hechos medidos.
- Con el encuadre desde rodillas no se observan por completo piernas, pies ni apoyos. Los valores correspondientes se configuran como provisionales.

La proyección 2D oblicua puede sesgar los ángulos. Las puntuaciones resultantes tienen estado `preliminary_assumed`; si faltan puntos necesarios, el lado queda no evaluable. Si ninguno se puede calcular, el resultado es `not_evaluable`, con puntuaciones nulas. La cobertura de 33 puntos se muestra por separado de la disponibilidad de segmentos para puntuación.

Los tests comprueban tablas, límites, ausencia de puntos, geometría degenerada y procedencia. Son validación de software, no validación científica ni de precisión de visión.

## Ventanas y avisos

La API de resumen recibe ventanas de 10–3.600 s, por defecto 60 s. Integra intervalos entre muestras válidas de hasta 2 s; no prolonga la última observación a través de huecos. Devuelve tiempo observado, tiempo sin cobertura, distribución de puntuaciones y medias de ángulos ponderadas por tiempo.

La regla inicial revisable requiere RULA ≥5 o REBA ≥8 durante al menos 10 s observados en la ventana. La señal de actualidad se desactiva si la captura más reciente supera 120 s de antigüedad o si el reloj está en el futuro más de 2 s. El trabajador también conserva observaciones históricas de muestras elevadas para revisión administrativa; no equivalen a un aviso actual de la HMI.

El formulario `posture.end_shift.v1` es propio del piloto: fatiga, carga percibida, comodidad y molestias 0–10. No se etiqueta como NASA-TLX o SUS. Sus respuestas se conservan como autoinforme y no sustituyen automáticamente los factores de RULA/REBA.

## Reconstrucción futura

El [laboratorio de visión](LABORATORIO_VISION.md) detecta pose 2D de vídeos y cámara mediante YOLOX/RTMW en CUDA, conserva los 133 puntos originales y adapta los equivalentes al esquema de 33 puntos para este mismo cálculo. El contexto se congela por trabajo. Los puntos no equivalentes, ocultos o de baja confianza quedan ausentes; no se rellenan posiciones para conseguir una puntuación.

SMPL y la reconstrucción monocular 3D no están instalados en esta fase. Una integración posterior podrá generar resultados nuevos vinculados a los originales y comparar su error frente a referencia experta. La fidelidad del avatar y la precisión de medida deben evaluarse por separado.
