# Video and camera laboratory

The laboratory (`/#vision`) tests pose estimation and ergonomic calculations independently of HMI/ROS acquisition. In strict mode it requires an administrator session. See [Authentication](ROS_API.md#authentication) for development mode.

## Analysis settings

Choose a name, optional operator, analysis rate (default 5 FPS, range 1–25) and minimum confidence (0.5–0.9). Short clips may be analysed at their full frame rate.

### Files/folders from the client

Upload one or more videos, or select a folder. Each video gets an independent job. Supported extensions: MP4, MOV, MKV, AVI, WebM, M4V; maximum 2 GiB and one hour. Actual decoding is checked during processing, not inferred from the extension.

The browser uploads blocks up to 4 MiB. Originals persist under `data/vision/uploads/<asset_id>/` by default, outside the Docker image. Incomplete uploads remain visible/removable; API byte offsets support clients that implement resumption.

### Files/folders already on the server

Place clips in `examples/videos/` or another suitable project folder. Server import supports the `examples` root or project root and optional recursive folder analysis. Listings are limited to 500 entries per request and 5,000 explored items. Import never modifies/deletes source files.

Only these read-only roots are exposed. External paths, parent traversal and escaping symlinks are rejected. Private/hidden directories, `.runtime`, `.git`, `backups`, `data` and dependencies are excluded.

### Browser camera

See [Camera and HTTPS](CAMERA_HTTPS.md) for local CA trust or an SSH tunnel.

1. Open the camera and grant browser permission.
2. Select a device and processing mode:
   - **Capture only, process manually** (default): save the original only. No JPEG inference uploads, jobs, sessions, metrics or transcoding are created. The retained asset appears in pending captures; processing can be requested later using its saved name/operator/FPS/confidence options.
   - **Process while capturing**: upload original video blocks and normalised JPEGs in parallel. A bounded GPU queue processes frames. Live results use their own frame time rather than overlaying stale pose on the current camera image.
   - **Process after capture**: save the original and enqueue processing when recording stops.
3. Start recording, then stop/save. No audio is recorded. The browser requests 1080p/25 FPS but may negotiate another resolution/rate.

Keep the tab open. Navigation is blocked while recording and closing the tab triggers a warning. Browser/network interruption preserves received bytes but does not guarantee automatic repair of an incomplete recording. A live job without frames for two minutes closes with an incident.

Reloading resets camera mode to capture-only; a single visit preserves the selected mode. Manual captures remain across reload/login and do not run pose inference. Storage/transfer still consume recording resources; the vision service keeps its models loaded/warmed.

## Results and deletion

- Queue/progress, cancellation, errors and reanalysis with new settings.
- Silent MP4/H.264 and WebM/VP9 playback, chosen by browser codec support; pose overlay, angles and per-sample RULA/REBA.
- Timeline, evaluable frame counts and maxima. Mean ordinal scores are not converted into a risk category.
- Original, CSV and JSON downloads; JSON retains native landmarks, confidence, selected person, versions and task context.
- Independent session/study records integrated with MongoDB, CrateDB and FIWARE. Robot/table remain null rather than invented ROS states.

Laboratory originals/frames/results use administrator vision endpoints. Session metrics follow dashboard permissions. Laboratory cell `cell-vision-01` does not replace the active ROS laboratory cell/session or profiles.

Deleting an analysis removes its session, results, frames and previews but keeps the original video. Deleting an uploaded video also removes its analyses/original; jobs must finish or be cancelled first. Imported source files stay on disk. Historical purge completes asynchronously.

## Engine and provenance

The `vision` service uses `Dockerfile.vision`, RTMLib **0.0.16**, **YOLOX-m**, **RTMW-x** (RTMPose family) and COCO-WholeBody **133 landmarks**. ONNX Runtime GPU **1.23.2** uses CUDA 12/cuDNN 9. Startup checks both sessions use `CUDAExecutionProvider` and runs warm-up; CUDA failure is reported rather than hidden behind CPU fallback.

`POSTURE_GPU_DEVICE` selects a GPU by index/UUID. One worker is supported; distributed leases are needed before scaling it. Compose limits host resources to 6 GiB RAM/six CPU cores, with additional GPU memory required. Lower analysis FPS can reduce work on smaller GPUs; benchmark the target device.

Models download at image build from versioned OpenMMLab URLs in `scripts/download_vision_models.py`. Checksums/versions are recorded in the container's `/opt/vision-models/manifest.json` and job metadata. An already built image can analyse offline. Preserve that image/digest for exact reproduction; a versioned URL alone does not guarantee immutable weights.

Component references: [RTMLib](https://github.com/Tau-J/rtmlib), [RTMPose/RTMW](https://github.com/open-mmlab/mmpose/tree/main/projects/rtmpose), [ONNX Runtime CUDA provider](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html). Code, weights and datasets have separate provenance/terms; the manifest identifies the actual weights used.

## Geometry and limitations

Images are uniformly scaled and letterboxed to 1920×1080; previews use the same transform without stretching the body. Compatible joints map to `posture.body33.v1`. Non-equivalent inner/outer eye points remain missing rather than duplicated. All 133 native landmarks are stored separately. Low-confidence/out-of-frame joints are excluded; detecting a person does not guarantee evaluable RULA/REBA.

For multiple people, the largest bounding box among sufficiently confident detections is selected, with confidence breaking ties. This is not identity recognition/tracking and can switch when a larger person crosses the foreground.

Results are preliminary 2D projections with explicit assumptions, particularly for diagonal views and partial framing. No measured depth, gravity calibration or SMPL is provided. Task context freezes per job.

Displayed time is relative to the video. Analysis session dates describe when POSTURE started analysis/capture, not a claim about when an imported file was recorded.

## Temporal synchronisation: source-pts-v1

Camera videos may declare 29.97 FPS but contain about 25 frames/second at variable intervals. Frame time therefore comes from that decoded frame's actual presentation timestamp, not index/nominal FPS. The first timestamp is normalised to zero. Samples retain `source_frame_index`, `source_pts_s`, `offset_s` and clock version; nominal and observed FPS are distinguished.

Sampling follows presentation-time intervals and skips empty intervals across pauses. MP4/WebM previews preserve source frame count/timing rather than forcing constant FPS. The browser follows `requestVideoFrameCallback.mediaTime` and does not select a future pose.

At 5 FPS the latest available pose is held between samples, giving roughly 0.2-second steps without accumulating drift. Increase analysis FPS for smoother overlays. Older analyses are retained; reanalyse the original for the corrected clock.

## Optional public demonstration clip

The development verification used [MMPose's public demo video](https://github.com/open-mmlab/mmpose/blob/main/demo/resources/demo.mp4): five 960×540 frames over one second. Recordings are excluded from Git, so a fresh clone may not include it. To obtain it deliberately:

```bash
mkdir -p examples/videos
curl --fail --location \
  https://raw.githubusercontent.com/open-mmlab/mmpose/main/demo/resources/demo.mp4 \
  --output examples/videos/mmpose-demo.mp4
```

Check upstream terms for your use. The clip verifies the software flow, not the industrial task or ergonomic accuracy.
