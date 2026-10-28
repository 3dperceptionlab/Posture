# Preliminary ergonomic methods

Implementation: `backend/metrics.py`, version `posture-ergonomics-0.1.0`. The engine implements RULA and REBA lookup tables A/B/C, contextual factors and geometry from supplied joints. Both sides are retained; the highest available side score is displayed. Ordinal scores are not averaged to assign a risk category.

Method references:

- McAtamney and Corlett, 1993: [Cornell RULA worksheet](https://www.ergo.human.cornell.edu/Pub/AHquest/RULAworksheet.pdf).
- Hignett and McAtamney, 2000: [Cornell REBA material](https://www.ergo.human.cornell.edu/Pub/AHquest/Cornell_REBA.pdf).

## Provenance and task context

Every result preserves algorithm version, context revision/full snapshot, capture/processing timestamps, angles, components, side, coverage and assumptions. Initial task settings are in `examples/task-context.provisional.json`; editing them affects future observations rather than overwriting results.

The pilot example uses a participant-reported approximate 2 kg, 0.30×0.60 m workpiece. Standing, supports, coupling, wrist twist, repetition and per-phase effort are provisional. Deburring effort cannot be inferred from part mass. The 2 kg value is near a RULA load threshold; the engine does not round before selecting its branch. Reusers must configure task factors for their own study.

Phase events select the load proxy by observation time. Without events, the finishing context is used and recorded as an assumption. Late events do not silently recalculate existing results.

## Geometry

- Use joints above confidence 0.5, or joints explicitly usable where the source supplies no confidence.
- Prefer declared, interpretable optical-camera 3D; otherwise use image pixels. Production ingestion can convert explicitly declared ROS axes and millimetres before geometry.
- Trunk: hip-to-shoulder midpoint direction relative to image/camera vertical. A 5° neutral processing zone reduces noise; it is not validated flexion/extension measurement.
- Neck: shoulder-to-head direction relative to the trunk; this alone does not measure anatomical cranio-cervical orientation.
- Upper arm: direction relative to trunk; elbow: geometric flexion; wrist: forearm/index approximation.
- Unobserved elevation/abduction, wrist deviation/twist, body rotation and modifiers remain explicit assumptions.
- Knee-up framing does not fully observe feet, legs or supports. Related factors must be marked provisional.

Oblique 2D projection can bias angles. Results using assumptions have status `preliminary_assumed`. Missing required joints make a side non-evaluable; no evaluable side gives `not_evaluable` and null scores. Body33 coverage is distinct from segment availability.

Software tests cover tables, boundaries, missing/degenerate geometry and provenance. They do not establish scientific or vision accuracy.

## Time windows and review signals

The legacy cell-summary endpoint accepts 10–3,600 seconds, default 60. It integrates intervals between valid samples up to two seconds and does not extend the last posture through a gap. Output includes observed/uncovered time, score distributions and time-weighted mean angles.

The revisable initial review rule requires RULA ≥5 or REBA ≥8 for at least ten observed seconds in the window. Current alerts are disabled if the latest capture is over 120 seconds old or more than two seconds in the future. Stored high-score observations are historical review records, not current HMI warnings.

These thresholds describe this implementation; they are not a validated intervention policy.

## Questionnaires

Legacy `posture.end_shift.v1` is a pilot-specific 0–10 fatigue/workload/comfort/discomfort form. Current production shifts use configurable, versioned pre/post forms. Neither is labelled NASA-TLX or SUS and neither automatically replaces RULA/REBA factors.

## Vision and future reconstruction

The [vision laboratory](VISION_LAB.md) uses YOLOX/RTMW on CUDA, retains 133 native landmarks and maps compatible joints to Body33. Context freezes per analysis job. Non-equivalent, occluded or low-confidence points remain missing rather than being filled to produce a score.

SMPL and monocular 3D reconstruction are not implemented. A future estimator should create new results linked to originals and be compared against an expert/reference measurement. Avatar realism and measurement accuracy require separate evaluation.
