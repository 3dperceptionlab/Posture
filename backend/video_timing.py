"""Presentation timestamps, not frame number / nominal FPS, define video time."""
import math

TIMING_VERSION = 'source-pts-v1'


class PresentationClock:
    def __init__(self, sample_fps):
        if not math.isfinite(sample_fps) or sample_fps <= 0:
            raise ValueError('Frecuencia de muestreo inválida.')
        self.sample_fps = sample_fps
        self.origin_s = None
        self.previous_s = None
        self.next_sample_s = 0.

    def observe(self, timestamp_ms):
        if not math.isfinite(timestamp_ms):
            raise ValueError('El decodificador no proporciona tiempos de presentación válidos.')
        pts = timestamp_ms / 1000
        if self.previous_s is not None and pts <= self.previous_s:
            raise ValueError('Los tiempos del vídeo no avanzan; no se puede sincronizar usando sus fps nominales.')
        if self.origin_s is None:
            self.origin_s = pts
        self.previous_s = pts
        offset = pts - self.origin_s
        selected = offset + 1e-6 >= self.next_sample_s
        if selected:
            # Skip empty time bins after a recording pause; never "catch up"
            # by analysing every frame following a timestamp gap.
            self.next_sample_s = (math.floor((offset + 1e-6) * self.sample_fps) + 1) / self.sample_fps
        return offset, selected
