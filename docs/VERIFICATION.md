# Verification history and reproduction

This document records development checks; it is not a certification or a claim that the checks were rerun on every host. Detailed logs, recordings and screenshots remain in the originating deployment's private `.runtime/` directory and are not distributed in Git or Docker images. Dates and counts below refer to historical runs.

## Reproduce software checks

Run from the repository root:

```bash
./launch_docker test
```

For integration checks use a dedicated test deployment in strict authentication mode, with no industrial session in progress:

```bash
docker compose exec -T api python -m tests.integration
docker compose exec -T api python -m tests.real_integration
```

The suites create identified QA fixtures and remove their own records. They exercise storage, processing and deletion; do not run them during a live industrial trial. Browser checks are in `scripts/browser_*_qa.cjs` and require their documented development environment/fixtures; historical scripts can need deployment-specific URL/path adaptation. Private historical evidence is not a dataset bundled with a fresh clone.

## Core server — 16 October 2026

- **15 unit tests**: Draft 2020-12 schemas/examples, missing/wrong frames, quaternion validation, unsensed suction, non-finite values, partial profile application, RULA/REBA tables, 2 kg threshold and degenerate geometry.
- **33 integration checks**: login, durable/idempotent ingestion, conflicts, sessions, revisions/ETag, images, administrator/viewer/ROS permissions, metrics, CrateDB archival, CSV, deletion and rejection of late data for deleted sessions.
- Chromium flows: login, synthetic data, charts/playback, robot view, profiles, images, questionnaires, diagnostics and 390 px mobile layout, without JavaScript exceptions/overflow.
- FIWARE subscription, retrievable NGSI-LD entities and real QuantumLeap rows in `doc.etergonomicobservation`.
- CrateDB outage/recovery: originals accepted and CPU metrics produced while archival was unavailable; pending archival resumed after recovery.
- Pinned images/dependencies; Orion-LD `-mongocOnly` compatibility with MongoDB 7.

### Backup/restore

A backup was restored into an isolated `posture-restore` Compose project on a separate port/network/volumes. Checks recovered login, 2 sessions, 262 messages, 6 retained images, metrics, image download, 262 CrateDB originals and QuantumLeap rows. The isolated instance was removed afterwards.

Evidence: `.runtime/restore-validation.json`, `.runtime/backup-report.log`, `.runtime/restore-report.log`. This was a same-host/same-architecture restore, not a physical migration to another machine.

## Vision and HTTPS — 22 October 2026

- **20 unit tests** including import path/symlink confinement, private-directory exclusions, limits, landmark adaptation, no detection and low confidence.
- **33 API regression checks**.
- GPU flow on the public MMPose clip: five detected/evaluable frames, preliminary results, original/export access, HTTP Range and independence from the active ROS cell.
- **10 browser flows**: HTTP camera warning, upload/overlay, mobile, server-folder import and private exclusions, HTTPS/Secure cookie, virtual live/deferred camera, read permissions and invalid upload/video handling. Video decoding was checked.
- TLS chain/address verified separately using the deployment's exported public root.
- Model CUDA sessions and warm-up checked at startup.

Evidence: `.runtime/vision-unit.log`, `.runtime/vision-regression.log`, `.runtime/vision-api-report.json`, `.runtime/vision-qa/`; browser tool: `scripts/browser_vision_qa.cjs`.

The camera was virtual Chromium input, not a physical USB device. RTX 4090 results do not establish RTX 4050 performance. No SMPL, field ergonomic accuracy or cross-host v2 vision/TLS backup restore was validated.

## Variable-frame-rate synchronisation — 22 October 2026

A development clip declared 29.9700 FPS but contained 711 frames ending at PTS 28.566 s (observed mean 24.8547 FPS). Index/nominal-FPS timing placed the last frame at 23.6903 s, producing 4.875667 s of accumulated drift.

The fix uses decoded source presentation timestamps, zero-based origin, interval sampling across pauses, variable-time MP4/WebM previews and browser `requestVideoFrameCallback`. Reanalysis produced 143 samples at 5 FPS through 28.433 s; the previous analysis was preserved.

- **25 unit tests**, including variable/constant clocks, nonzero origins, pauses and invalid timestamps.
- All 711 preview frame timestamps matched the original with maximum reported difference 0 s at file precision; sample timestamps matched source frame PTS.
- Browser: nine seeks and continuous 1.5× playback, at least 30 frames, pose visible on at least 95%, no future samples or JavaScript errors.

Evidence: `.runtime/timing-unit.log`, `.runtime/con-robot-timing-report.json`, `.runtime/sync-qa/`. Tools: `scripts/check_video_timing.py`, `scripts/browser_video_timing_qa.cjs`.

This validates temporal association, not pose accuracy. At 5 FPS, holding the last pose gives roughly 0.2-second steps.

## Stature and manual capture — 26 October 2026

- **30 unit tests**: prior contract/metrics/timing plus automatic/manual height, legacy compatibility and invalid bounds.
- Browser: required stature, 175 cm → 105 cm preview, 180 cm → 108 cm revision, manual preservation and concurrent edit conflict.
- Default capture-only: zero analysis creation/JPEG uploads during or after recording; original retained with no associated job. Manual processing after reload used the saved settings.
- After-capture and live modes both completed analysed frames.
- Five browser groups, no JavaScript errors/390 px overflow, virtual camera only.

Evidence: `.runtime/height-capture-unit.log`, `.runtime/height-capture-qa/`; tool: `scripts/browser_height_capture_qa.cjs`.

## Production shifts/iterations — 26 October 2026

- **36 unit tests**, including Body33, canonical UTC, non-finite input, unknown geometry without invented scores, declared ROS/optical/millimetre conversion and versioned forms.
- **58 integration checks**: permissions, retries/identity, numeric IDs, automatic predecessor closure, Quality Check/error summaries, labels, pre/post forms, resumable MP4/SHA-256, original permissions, CrateDB and associated ROS/GPU results.
- Default manual policy produced no metric/job on receipt or video completion; live, after-iteration and ready-video policies were tested on isolated fixtures.
- **7 browser groups**: HMI snapshots, tags/filters, manual analysis by both sources, non-future playback samples, forms/settings, retained legacy features and mobile layout.
- OpenAPI 3.1 reference: 17 production paths, resolved internal references, explicit administrative security and five validated JSON fixtures.

Evidence: `.runtime/real-unit.log`, `.runtime/real-integration.log`, `.runtime/real-browser-qa/`. Tools: `tests/real_integration.py`, `scripts/browser_real_qa.cjs`.

Data came from isolated QA sources, synthetic joints/JPEGs and the public MMPose video, not physical ROS/robot integration. Numeric counters were retained after cleanup. Final production questionnaire content and producer 3D conventions remained undecided.

## Offline API documentation — 26 October 2026

Swagger's external stylesheet was blocked by the content security policy. Swagger UI 5.34.0 is now served locally with its licence and favicon.

HTTP/HTTPS browser checks blocked external connections: styles applied, 85 operations rendered, authorization dialog worked, with no external requests, JavaScript errors or failed HTTP responses. TLS was also checked against the exported root.

Evidence: `.runtime/api-docs-qa/`.

## Optional development authentication — 28 October 2026

- **6 authentication tests**: strict default, invalid configuration, identified anonymous administrator, invalid/expired credential rejection, retained viewer/device limits, response warnings and mode-specific OpenAPI.
- **21 deployed API checks** without credentials: configuration, shift/iteration creation, multipart pose/JPEG, administrative image retrieval, labels and completion; incorrect token/cookie rejected.
- Python client without a token: successful form query and warning without JSON contract changes.
- HTTPS browser: anonymous dashboard, visible warning, 390 px layout, Swagger warning and no JavaScript errors.
- Startup warning, health and certificate checks passed; fixtures and their historical files/records were removed.

Evidence: `.runtime/auth-mode-unit.log`, `.runtime/auth-mode-qa/`.

Development mode was explicitly enabled for that integration deployment. The code/example/new-install default remains `strict`. To restore enforcement set `POSTURE_AUTH_MODE=strict` and recreate the API container.

## Public module documentation — 28 October 2026

The README and documentation were translated into English and reorganised around
the reusable Data Processing and Dashboard module. Host-specific addresses and
workspace paths were replaced with local/configurable examples. API metadata was
translated at source and the strict-mode reference regenerated.

- Checked 11 Markdown documents and 47 local links/anchors.
- Resolved all 46 internal references across 17 production OpenAPI paths.
- Compared the exported contract with the previous reference after excluding
  documentation metadata: no endpoint, field, constraint or security changes.
- Six authentication tests passed after the metadata update.
- HTTP/HTTPS Swagger browser checks passed with external connections blocked:
  local styles, 85 operations, authorization dialog and no JavaScript errors.
- Caddy accepted the localhost/loopback TLS settings from the public example.

Evidence: `.runtime/public-docs-check.log`, `.runtime/public-docs-auth-tests.log`,
`.runtime/public-docs-browser.log`, `.runtime/public-docs-caddy-example.log`.

## Scope

Software checks do not establish clinical/occupational validity, calibration, physical camera operation, target-device performance or scientific superiority of an estimator. Synthetic fixtures are labelled accordingly. New deployments must validate their own hardware, task context and field measurements.
