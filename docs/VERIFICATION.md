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

## Laboratory ZIP export — 11 November 2026

Added an administrator export queue, CPU-only `exports` service and laboratory
dashboard controls. Source videos/analyses are read without repeating inference.

- Five unit tests cover variable-rate frame selection, no future poses, clearing
  missing detections, complete metric columns, safe archive folder names and
  strict anonymous/viewer denial.
- A synthetic variable-frame-rate render preserved every frame timestamp and
  verified overlay pixels before/after each sample, including a missing detection.
- A real single-run ZIP passed integrity checks: the original SHA-256 matched,
  CSV/JSON contained all 143 samples, and all 711 skeleton-video timestamps matched
  the source preview. HTTP Range download, active-request deduplication and ZIP
  deletion without source-run deletion passed.
- Browser checks created a full 19-run export using the button, preserved progress
  after reload, and found no JavaScript errors or horizontal overflow at 390 px.
  The full export continues independently in the worker; this check did not wait
  for all 19 runs to finish.

Evidence: `.runtime/vision-exports-qa/unit.log`, `timing.log`, `archive.log`,
`browser.log`, and desktop/mobile captures in the same private directory.

## Stable angle layout and display smoothing — 11 November 2026

The vision laboratory retains all four angle cells across missing detections,
showing em dashes for unavailable measurements. Display-only causal smoothing
defaults to a one-second window, with raw/0.5-second/two-second alternatives.

Browser verification at 1440 px and 390 px checked 20 repeated dropouts per
viewport: the same cell nodes and layout dimensions were retained. Fixtures
verified the trailing mean, future-sample exclusion, long-gap expiry, missing
joint handling and unchanged source metrics. The selector worked and a seek in
a real variable-rate clip retained a non-future pose. No JavaScript errors or
mobile overflow were observed. Stored results and exports were not rewritten.

Tool: `scripts/browser_angle_smoothing_qa.cjs`. Private report/screenshots:
`.runtime/angle-smoothing-qa/`. API rebuilt/deployed and HTTPS health verified.

## Paired USB capture — 12 November 2026

Checkpoint commit `021fac4` was created before the change. The browser can select
two different camera devices and start/stop their independent recordings in one
event turn. Paired originals retain a shared capture group and camera index.

Chromium verification used two simulated camera streams drawn from a public
MMPose clip, with distinct per-camera markers. Both recordings were saved and
produced separate completed GPU analyses with sample results. Measured start
delta was 0 ms and stop delta approximately 0.8 ms in this simulation. Dual manual
capture produced no inference jobs; single-camera capture remained functional.
No JavaScript errors or mobile overflow were observed. QA uploads were removed.

Tool: `scripts/browser_dual_camera_qa.cjs`; private report and mobile screenshot:
`.runtime/dual-camera-qa/`. This verifies software coordination, not hardware
frame synchronisation or bandwidth of two physical USB devices on the client.

## Paired playback and browser WebM metadata — 12 November 2026

Reviewed failed paired recordings with zero processed frames. Their original
files decoded successfully but advertised 1000 nominal FPS; the former metadata
range check rejected them before inference. The worker now retains that declared
value and samples by presentation timestamps without imposing that range check
on otherwise decodable videos. Five affected jobs were requeued in place with
recovery history; original files and prior completed results were preserved.

The requested two-camera trial's name/operator assignment was corrected across
jobs, assets, sessions, studies, observation associations and archived records,
with a metadata correction audit entry. Numerical metrics were not recalculated
for the already completed camera.

Chromium decoded both actual camera videos, played them together (approximately
22 ms difference at the observation), paused both, switched the selected camera,
and rendered a 390 px layout without overflow or JavaScript errors. Private
evidence: `.runtime/paired-review-qa/`.

## Compact laboratory readout and camera curves — 12 November 2026

Added a red capture indicator with a monotonic elapsed clock for single/paired
recording. The current-score readout places compact RULA/REBA cards and blocks
beside a 2×2 angle grid. The chart follows immediately, with independent toggles
for each camera's RULA and REBA; physical camera labels remain stable on switching
the selected video.

Chromium checks exercised all four curve toggles, including hiding all curves,
correct camera/sample mapping after changing selection, a progressing recording
clock and unchanged source metrics. Desktop card order and the 2×2 angle grid
were checked, along with a 390 px layout without overflow or JavaScript errors.
These display checks do not imply hardware capture synchronisation.

Private report/screenshots: `.runtime/lab-design-qa/`. Stored metrics and export
contents are unchanged by these display controls.

## Scoring-context audit and current-frame marker — 12 November 2026

An audit recomputed 316 evaluable samples with their original frozen context and
found no RULA/REBA mismatches. The high RULA baseline was sensitive to the assumed
2 kg repeated finishing load: one stored sample changed from RULA 6 / REBA 2 to
RULA 3 / REBA 2 when only that proxy was removed in memory. This sensitivity
calculation did not rewrite samples.

After the user confirmed table support, the running context advanced from
revision 1 to 2: finishing excludes the supported part's weight, while transfer
retains 2 kg. Cutter force remains unmeasured and scores remain preliminary.
Existing jobs/results keep their frozen context. The public example uses the
updated revision. Reanalysis retains the original operator association.

All 47 unit tests passed with the updated finishing assumption. Browser checks
verified that the subtle SVG marker follows actual presented frame timestamps
during playback, pause, forward/backward seeks, hidden curves and missing pose,
without horizontal overflow at 390 px or JavaScript errors. The marker updates
attributes rather than redrawing curves for every video frame.

Private evidence: `.runtime/metric-audit/` and `.runtime/playhead-qa/`.

## Scope

Software checks do not establish clinical/occupational validity, calibration, physical camera operation, target-device performance or scientific superiority of an estimator. Synthetic fixtures are labelled accordingly. New deployments must validate their own hardware, task context and field measurements.
## Laboratory height annotations and grouped analysis — 2026-11-12

- All 53 Python unit tests passed, including known unit-typo inference, explicit
  unknown/manual heights, invalid numeric inputs, missing score denominators,
  ordinal distributions, paired-capture counts, and separation of incompatible
  contexts, algorithms and sampling settings.
- The deployed migration corrected 15 laboratory titles and annotated 55 retained
  analysis jobs: 19 at 75 cm, 20 at 100 cm, 12 at 120 cm and 4 unknown. Repeating
  the migration added no audit records. Raw videos and score documents were not
  rewritten.
- The default comparison selected 54 latest completed video analyses across 36
  captures, with 28,342 sampled frames and 10 compatible groups. One historical
  reanalysis was excluded by the latest-per-video default. The local query took
  approximately 0.28 seconds; this is a local observation, not a performance SLA.
- Chromium exercised combined height/operator grouping, operator/height/camera/
  context filters, unknown-height groups, empty results, reset, CSV download,
  capture height options, invalid-height API rejection, and navigation back to
  both-camera playback. Desktop (1440 px) and mobile (390 px) had no document
  overflow or JavaScript errors. Evidence is private under
  `.runtime/lab-analysis-qa/` and is not distributed with the public module.

## Selected laboratory ZIP exports — 2026-11-12

- All 59 Python unit tests passed. Selection checks cover exact ID snapshots,
  deduplication, empty/invalid lists, unavailable or unfinished runs, active
  archive conflicts, legacy export-all behavior, deleted associations and
  administrator access.
- Chromium tested search, bulk selection of search matches, clearing, selection
  and input focus across polling, navigation away/back, collapsed picker state,
  empty selection rejection, the unchanged export-all request format, and
  390 px mobile layout without document overflow or JavaScript errors.
- A real selected export used two existing analyses out of 81 candidates.
  Its ZIP contained exactly two run folders, two originals, two rendered
  skeleton videos, two metric CSV series, two complete pose/result JSON files,
  `manifest.json` and `runs.csv`, with no export warnings. The same active
  selection was reused; a different active selection returned HTTP 409.
- Only the QA archive was deleted after verification; source recordings and
  analyses were preserved. Private evidence is in `.runtime/selected-export-qa/`.
