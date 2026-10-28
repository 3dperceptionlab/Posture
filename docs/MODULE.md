# Module specification: Data Processing and Dashboard

## Identity

| Property | Value |
| --- | --- |
| Module | POSTURE Data Processing and Dashboard |
| Branch | `Server-Dashboard` |
| Deployment unit | Docker Compose application |
| Interface | HTTP/JSON, multipart JPEG samples and binary MP4 uploads |
| Current acquisition contract | HMI/ROS 1.0: [ROS_API.md](ROS_API.md) |
| Research context | POSTURE, supported through an ARISE open call |

## Responsibilities

| Component | Ownership |
| --- | --- |
| HMI module | Operator identification, stature/profiles, questionnaires and operator commands |
| ROS/control module | Equipment control, voice handling, observations, iteration events and delivery queue |
| This module | Durable reception, IDs/associations, storage, requested processing, dashboard, exports and FIWARE |

Production identities/profiles are snapshots received from HMI/ROS, rather than equipment settings applied by this module. Legacy profile editing/application endpoints remain for laboratory tests. Hardware limits, control timing and physical application remain with ROS. HTTP belongs in a communication worker, separate from the robot control loop.

## Inputs and outputs

| Interface | Input | Output |
| --- | --- | --- |
| Shifts | Operator/source/cell, timestamps and versioned questionnaires | Numeric `shift_id`, status, labels and assessment history |
| Iterations | Piece start, assistance, actions, completion summary and final tool/table state | Numeric `iteration_id`, timing and searchable records |
| Samples | 33 joints, spatial conventions, matching JPEG and capture/video timestamps | Durable receipt, original association and processing state |
| Video | Manifest, SHA-256 and resumable MP4 blocks | Retained original associated with shift/iteration |
| Analysis | Explicit request or configured policy | Per-source jobs, metrics, provenance and derived video/frames |
| Browser laboratory | Client/server files or browser camera | Independent assets/jobs, playback and exports |
| FIWARE | Background publication from stored records | Orion-LD context and QuantumLeap/CrateDB history |

All acquisition routes use `/api/v1`. Live API documentation is at `/api/docs` and `/openapi.json`. The [ROS guide](ROS_API.md) defines chronology, idempotency, limits and recovery.

## Lifecycle and processing

1. Start a shift and freeze its operator/form snapshot.
2. Start an iteration per workpiece; the server allocates a persistent, globally increasing ID.
3. Submit matching pose/image samples at the available rate, with actual capture timestamps.
4. Close the iteration on Quality Check, error/cancellation, or next iteration start.
5. Upload the full MP4; transfer may finish after iteration/shift closure.
6. Analyse manually or according to the policy frozen at iteration start.
7. Close the shift with its post-shift questionnaire.

Initial production settings store data without calculating metrics. ROS metric modes are `manual`, `live`, `after_iteration`; video modes are `manual`, `when_ready`. Browser capture has independent manual/live/after-capture options. New analyses preserve earlier results.

## Configuration

Settings come from `.env`; see [the example](../.env.example). Relative host paths resolve from the repository root.

| Variable | Purpose |
| --- | --- |
| `POSTURE_PORT` / `POSTURE_BIND` | HTTP host port/interface; defaults `8080` / `0.0.0.0` |
| `POSTURE_ADMIN_USER` / `POSTURE_ADMIN_PASSWORD` | Initial administrator; password at least 16 characters |
| `POSTURE_INGEST_TOKEN` | Separate ROS Bearer credential |
| `POSTURE_AUTH_MODE` | `strict` by default; `development` allows anonymous administrator requests with warnings |
| `POSTURE_COOKIE_SECURE` | Force Secure cookies behind an HTTPS proxy |
| `POSTURE_TLS_HOST` / `POSTURE_TLS_EXTRA_HOST` | Certificate names/IPs; configure for the deployment |
| `POSTURE_TLS_PORT` | HTTPS host port; default `8443` |
| `POSTURE_GPU_DEVICE` | NVIDIA GPU index or UUID |
| `POSTURE_VISION_DIR` | Optional host storage override; normally `./data/vision` |

Prepare configuration before startup as described in the [README](../README.md#quick-start). Recreate affected containers after environment changes; restarting alone does not reload `.env`.

```bash
# After setting POSTURE_AUTH_MODE=strict in .env:
docker compose up -d --no-build api
```

## Persistence and retention

- MongoDB stores application records, original observations, associations and durable job state.
- CrateDB archives original JSON in `posture_raw` and `posture_real_raw`; the latter includes shift/iteration IDs. QuantumLeap owns separate time-series tables.
- Orion-LD maintains recent context; late observations remain in history without replacing newer context.
- JPEGs use the media volume. Uploaded videos/derivatives use `data/vision/` by default.
- `examples/` and the project directory are read-only import roots, excluding private directories and path escapes.
- Caddy CA material is persistent. Only its public root is distributed to clients.

Production study data remains until administrative removal. Laboratory analysis deletion preserves its original video; uploaded-video deletion also removes associated analyses. Imported source files are not deleted. Background archival and purge have their own retry/status paths.

## Backup and restore

From the repository root:

```bash
./backup_docker
```

The backup is written to `backups/<UTC-timestamp>/`. It includes MongoDB, CrateDB, media, TLS volumes, vision storage, source/configuration and SHA-256 checksums. Services stop briefly for consistency; previously active services are restarted. Backups include credentials/study data and must remain private. Imported clips under `examples/` are in the source archive; uploaded clips/derivatives are in the vision archive.

For migration, extract `source.tar.gz` into an empty destination directory, place the backup there and run:

```bash
./restore_docker ./backups/<UTC-timestamp> --replace
```

`--replace` replaces destination project data after checksum verification. Use the copied credentials and adjust host/TLS settings before clients connect. Deleting active records does not change older backups.

For an isolated restore on the same host:

```bash
POSTURE_PROJECT=posture-restore POSTURE_PORT=18081 POSTURE_TLS_PORT=18443 \
  ./restore_docker ./backups/<UTC-timestamp> --replace
```

A different project uses `data/<project>/vision/` by default; `POSTURE_VISION_DIR` overrides this. Version 1 backups remain accepted but lack later vision/TLS data.

## Extension points

A different HMI/ROS producer can reuse the HTTP contract. Unknown/model-relative spatial conventions can be retained without inventing metric geometry. New processing implementations should preserve originals, record estimator/algorithm versions and assumptions, and create traceable derived results. See [Ergonomic methods](ERGONOMICS.md).
