# Laboratory metadata and comparisons

Administrators can open **Análisis de métricas** in the dashboard navigation or
follow **Analizar por altura** from the vision laboratory header. This view
uses existing results; opening it does not run inference or alter scores.

## Table height

Each laboratory analysis has a nullable integer `table_height_cm`. The known
experiment titles containing `75mm`, `100mm` or `120mm` were confirmed to mean
centimetres. An idempotent startup migration corrects those display titles while
retaining their numeric value, and infers heights from matching `cm` labels.
Ambiguous titles or titles without a known height receive `null`.

Original filenames, video files, joint observations and metric results remain
unchanged. Corrections are recorded in MongoDB `metadata_corrections`, including
the previous titles. Associated session/study labels and saved capture options
are updated. Existing ZIP exports remain independent snapshots.

The capture form supports automatic inference, 75/100/120 cm, or an explicit
unknown height. A run's viewer also accepts a manually entered whole centimetre
value between 20 and 200; clearing it stores `null`. This is a laboratory
annotation, not measured table telemetry, and does not change the ergonomic
calculation. It applies to the selected camera analysis; edit the other camera
separately if needed. Future analyses of that original inherit the annotation.

```http
PATCH /api/v1/vision/jobs/{job_id}/metadata
Content-Type: application/json

{"table_height_cm": 75}
```

`POST /api/v1/vision/jobs` and capture `analysis_options` accept the same optional
field. Omitting it enables title inference; explicitly sending `null` overrides
title inference. ROS/production metadata is outside the scope of this migration
and endpoint.

## Filters and grouping

The analysis page supports operator, table height (including unknown), camera,
robot condition, context revision and inclusive UTC calendar dates. Robot
condition is inferred only from explicit experiment title wording such as
`Sin Robot`, `Robot` or `Con UR`; it is an annotation rather than measured robot
activity. Group by any combination of height, operator, camera, robot condition
and UTC day, then select **Aplicar filtros**.

By default, the latest completed analysis of each retained video is selected
before applying filters. This avoids counting reanalysis of the same original
twice. Disable that option to inspect historical analyses as well. Both cameras
remain independent analyses, while their shared capture ID counts as one
capture. Deleted jobs, assets and sessions, production jobs, and incomplete or
failed jobs are excluded. The query is not limited to the latest 100 jobs shown
by the laboratory history list.

Results with different context snapshots/revisions, algorithm versions,
geometries, estimators, sampling frequencies or confidence settings are always
separate comparison groups, even if their visible group labels match.

Charts show score distributions across evaluable sampled frames, the lower
observed median, the observed maximum, and the fraction of evaluable frames
with RULA >= 5 or REBA >= 8. Each sampled frame has equal weight. Percentages
are not percentages of elapsed time, workers or clinical risk. Missing scores
are excluded from each metric's denominator and evaluable counts are shown.
Longer recordings contribute more observations; grouping does not establish
statistical independence between frames or cameras. Scores remain preliminary
and dependent on the stored task assumptions and monocular pose limitations.

**Exportar comparación CSV** downloads the filtered per-analysis summaries,
including operator, height, camera/capture, calculation settings and full score
histograms. **Ver vídeo** opens the original viewer with its pose overlay and
time series. Full videos, skeleton videos and frame-level series remain
available through the laboratory ZIP export.

```http
GET /api/v1/vision/analysis?group_by=table_height_cm,operator_id&camera_index=1&latest=true
```

Other query parameters: `operator_id`, `table_height_cm` (whole cm or `none`),
`condition` (`with_robot`, `without_robot`, `unknown`), `context_revision`,
`since` and `until` (`YYYY-MM-DD`, UTC). All routes require administrator access
under the project's existing authentication mode; they are documented in the
local OpenAPI UI at `/api/docs`.
