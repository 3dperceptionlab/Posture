# Laboratory and legacy API — v0.1

For production HMI/ROS acquisition use [ROS_API.md](ROS_API.md), contract 1.0. The endpoints below remain available for laboratory profiles, sessions and compatibility. Production profiles are owned by HMI; production acquisition initially stores data without processing.

Base URL: `http://localhost:8080/api/v1`; replace the host for remote use. Swagger UI is at `/api/docs`; `GET /schema` returns the legacy message JSON Schema.

## Authentication

In default strict mode:

- Web: `POST /auth/login` with `username`/`password`; 12-hour HttpOnly, SameSite Strict session cookie.
- ROS: `Authorization: Bearer <POSTURE_INGEST_TOKEN>`.
- ROS can query operators/sessions/cells/profiles, manage legacy parameters and submit telemetry/images. It cannot administer web accounts or retrieve retained images.
- Viewer accounts have read-only access without original images or administrative diagnostics.

Development mode permits anonymous administrator requests with warnings. See [Authentication](ROS_API.md#authentication). Credentials are never embedded in pose JSON or browser JavaScript.

## Legacy ROS sequence

1. `GET /operators`: read operators and current profiles.
2. `POST /sessions`: supply `operator_id`, optional `cell_id`, `name`, `condition`, `study_id`. The returned `session_id` identifies the cell's one active session.
3. Poll `GET /cells/{id}/desired-profile` about every two seconds, optionally using ETag/`If-None-Match`.
4. Validate/apply the revision locally at a safe state; send `profile_application` with per-component status.
5. `POST /ingest`: submit v0.1 messages, preserving each component's timestamp and stable retry identity.
6. For images, first submit `frame` metadata in telemetry, then `PUT /frames/{frame_id}` with 1920×1080 JPEG and `Content-Type:image/jpeg`. Optional `X-Content-SHA256` verifies content. Session/study association comes from validated metadata, not extra session headers.
7. Poll `GET /cells/{id}/summary?window_seconds=60` about every 30 seconds; display capture age, coverage and preliminary status.
8. Send available phase/cycle events. A suction command does not confirm physical grip or completion.
9. Send `shift_assessment` and close with `POST /sessions/{id}/close` or `session_ended`.

These legacy calls belong to the ROS bridge acting for HMI, rather than requiring HMI-to-server connectivity.

## Main endpoints

Paths below are relative to `/api/v1`.

| Method/path | Purpose |
| --- | --- |
| `GET /operators` | Operators, current profile and last application acknowledgement |
| `GET /profile-rules/table-height` | Provisional factor, version and stature limits |
| `POST /operators` | Create operator/initial profile; return IDs and revision |
| `PUT /operator-profiles/{id}` | New revision using `expected_revision` or If-Match; conflict `412` |
| `GET /operator-profiles/{id}/revisions` | Profile history |
| `DELETE /operators/{id}` | Administrator: remove operator and request associated-data purge |
| `GET /cells` | Cells and session assignment |
| `GET /cells/{id}/desired-profile` | Desired configuration with ETag |
| `GET /cells/{id}/summary` | Time distribution, mean angles, coverage and preliminary signal |
| `GET /sessions` | Filters: operator/study/from_date/to_date; limit up to 500 |
| `POST /sessions`, `POST /sessions/{id}/close` | Start/close a session |
| `DELETE /sessions/{id}` | Hide immediately and purge asynchronously |
| `GET /sessions/{id}/timeline` | Latest 600 samples by default; max 2,000, `before` pagination |
| `GET /sessions/{id}/export.csv` | All session results |
| `POST /ingest` | One message |
| `POST /ingest/batches` | `batch_id` and 1–100 messages; per-message status |
| `POST /studies`, `GET /studies` | Create/list studies |
| `GET /studies/{id}/frames` | Administrator image metadata |
| `DELETE /studies/{id}` | Administrator study/session deletion |
| `PUT /frames/{frame_id}` | JPEG upload, max 8 MiB, after metadata |
| `GET /frames/{frame_id}` | Administrator retained study original |
| `GET /assessments` | Questionnaire responses; optional session filter |
| `GET /alerts`, `POST /alerts/{id}/acknowledge` | Historical observations and review acknowledgement |
| `GET /context`, `PUT /context` | Versioned ergonomic context and provenance |
| `GET /stats`, `GET /system` | Summary and administrative diagnostics |
| `POST /demo` | Administrator synthetic laboratory data; no hardware movement |

## Stature and table height

The browser requests stature in centimetres; the API uses metres. Alongside `display_name` and `presentation_pose`, an automatic profile can specify:

```json
{"stature_m":1.75,"table_height_mode":"automatic"}
```

The server computes `table_height_m = round(stature_m × 0.60, 3)` (1.05 m here), recording `table_height_rule:"stature-ratio-v1"`. This is a provisional project rule, not a validated ergonomic prescription. Factor/bounds are in `backend/profile_height.py`: stature 1–2.3 m, table 0.2–2 m. ROS still validates hardware limits and applies the revision at `next_safe_state`.

Automatic mode ignores supplied table height and recalculates at each revision. Manual mode uses `table_height_mode:"manual"` and `table_height_m`, preserves stature and sets the rule to null. Changing stature in manual mode does not move the target height. History remains unchanged.

Compatibility: an explicit height without mode means manual, preserving known stature. Omitted mode/height retains the current mode; a new profile with stature defaults to automatic. Existing profiles are not assigned invented stature. Updates still require the pose and concurrency revision.

Profile acknowledgement `applied` means adopted by local ROS logic, not proof the robot/table physically reached the target. Telemetry/events provide that observation.

## Vision endpoints

In strict mode all `/vision` routes require an administrator cookie. ROS tokens/viewers cannot retrieve or administer laboratory videos.

| Method/path | Purpose |
| --- | --- |
| `GET /vision/status` | Worker/CUDA/models, limits and HTTPS URL |
| `GET /vision/certificate` | Public TLS root |
| `GET /vision/files?root=examples&path=videos&recursive=false` | Read-only import listing; `root=project` selects the repository root |
| `POST /vision/import` | `{root:"examples",path:"videos/clip.mp4"}` |
| `GET /vision/assets` | Original library and incomplete uploads |
| `POST /vision/uploads` | `{name,size_bytes?,capture?}`; creates asset, not inference |
| `PUT /vision/uploads/{id}?offset=0` | Binary blocks up to 8 MiB; max total 2 GiB |
| `POST /vision/uploads/{id}/complete` | Verify length and complete transfer |
| `DELETE /vision/assets/{id}` | Delete associated analyses and uploaded original; jobs must stop first; imported files stay |
| `POST /vision/jobs` | `{asset_id,name?,operator_id?,sample_fps:5,confidence:0.5,mode:"file"}` |
| `GET /vision/jobs`, `GET /vision/jobs/{id}` | Progress, settings and summary |
| `POST /vision/jobs/{id}/cancel` | Cancel, preserving partial results |
| `DELETE /vision/jobs/{id}` | Remove analysis/session/study; preserve original |
| `PUT /vision/jobs/{id}/frames/{sequence}?offset_s=0.2` | Live JPEG 1920×1080, max 8 MiB; `429` at 15 pending frames |
| `POST /vision/jobs/{id}/finish` | End live capture after original is stored |
| `GET /vision/jobs/{id}/results?after=-1&limit=5000` | Ordered incremental samples; max 20,000 |
| `GET /vision/jobs/{id}/video?format=mp4` | Playback MP4 or `format=webm`; Range support |
| `GET /vision/jobs/{id}/original` | Original download |
| `GET /vision/jobs/{id}/export.csv`, `export.json` | Full results; JSON retains native joints and context |

Live camera: create an unknown-size upload, create a `mode:"live"` job, send binary recording blocks and JPEGs separately. After stopping, wait for the final transfers, complete the upload and call `finish`. Frame offsets are relative to recording start. Optional `capture_fps` records negotiated device FPS.

Manual capture: create an upload with `capture:{mode:"manual",analysis_options:{name,operator_id,sample_fps,confidence,capture_fps}}`, complete the recording and create no job. This persists options, not a queued GPU task. Later `POST /vision/jobs` with `asset_id` inherits them unless overridden. `analysis_requested_at` identifies previously requested assets. `record` and `live` capture modes document after-capture and concurrent processing intent; the browser creates jobs accordingly. Upload completion alone never starts inference.

Files can have other FPS values. The legacy normalised-frame contract retains 1920×1080 and permits `frame.capture_fps` greater than zero and at most 240.

## Persistence and errors

| Status | Meaning |
| --- | --- |
| `202` | Durably stored; downstream work may remain |
| `200 duplicate` | Same identity/content already received |
| `409` | Incompatible identity/sequence/image reuse |
| `412` | Concurrent profile/context edit |
| `422` | Invalid contract, coordinates, references or factors |
| `401/403` | Authentication/permission failure |
| `413` | Size limit exceeded |

JSON requests are limited to 2 MiB and individual messages to 256 KiB. Workers retry downstream processing; diagnostics expose failures. Late messages cannot recreate a deleted session.

Fixtures use synthetic identities. Create real operator/study/session IDs and update references before using them. Without a study, `study_id` is null and image retention is `transient`. Missing joints use `missing` with null coordinates.
