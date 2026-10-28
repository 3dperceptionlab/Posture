"""Provisional project rule; this is not an ergonomic assessment."""
import math

from fastapi import HTTPException


TABLE_HEIGHT_RULE = {
    'version': 'stature-ratio-v1', 'factor': 0.60,
    'stature_min_m': 1.0, 'stature_max_m': 2.3,
    'description': 'Estimación provisional: altura de mesa = estatura × 0,60. Ajustable manualmente.',
}


def height_values(body, current=None):
    current = current or {}
    stature = body.get('stature_m', current.get('stature_m'))
    if stature is not None and (type(stature) not in (int, float) or not math.isfinite(stature)
                               or not TABLE_HEIGHT_RULE['stature_min_m'] <= stature <= TABLE_HEIGHT_RULE['stature_max_m']):
        raise HTTPException(422, 'Estatura entre 100 y 230 cm.')
    # Legacy clients supplying a table height retain their explicit manual setting.
    default_mode = ('manual' if 'table_height_m' in body
                    else current.get('table_height_mode', 'automatic' if 'stature_m' in body else 'manual'))
    mode = body.get('table_height_mode', default_mode)
    if mode not in ('automatic', 'manual'):
        raise HTTPException(422, 'Elige altura de mesa automática o manual.')
    if mode == 'automatic':
        if stature is None:
            raise HTTPException(422, 'Introduce la estatura para calcular la altura de mesa.')
        height = round(stature * TABLE_HEIGHT_RULE['factor'], 3)
    else:
        height = body.get('table_height_m', current.get('table_height_m'))
    if type(height) not in (int, float) or not math.isfinite(height) or not .2 <= height <= 2:
        raise HTTPException(422, 'Altura de mesa entre 20 y 200 cm.')
    return {'stature_m': stature, 'table_height_m': height, 'table_height_mode': mode,
            'table_height_rule': TABLE_HEIGHT_RULE['version'] if mode == 'automatic' else None}
