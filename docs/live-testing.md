# Test the local live workflow

Run commands from `C:\Users\AVIRAL PC\Downloads\MetaAIHack`.

## Start the app

Docker Desktop must be running. The existing ignored `.env` already selects
`INFERENCE_MODE=live` and contains the server-side Meta key. Do not overwrite it
with `.env.example` or put the key in browser configuration.

```powershell
docker compose -f compose.yaml -f compose.robot.yaml -f compose.geometry.yaml up -d
npm.cmd start
```

Open **http://127.0.0.1:53000**. API documentation is at
**http://localhost:58000/docs**. Leave the terminal running for the frontend.
If you changed frontend code, run `npm.cmd run build` before `npm.cmd start`.
The robot image was already built and tested. A fresh machine must build the base
and robot image and download robot assets as described in `phase-three.md`.

## What is live now

| Component | Current state |
| --- | --- |
| Upload, FFmpeg, database, queue, storage | Running real services |
| Muse semantics and SAM video tracking | Real Meta API calls; live mode |
| VGGT scene / SAM 3D Body reconstruction | Configured; real queued inference verified on the local 4 GiB GPU |
| Franka IK, physics replay, LeRobot | Installed and tested in the running robot worker |

Live mode does not fill missing 3D outputs with fixtures. The current source still
needs semantic-to-track identity correction and continuous geometry before Phase 3
can pass. A review override retains these uncertainties.

## 1. Upload and verify real perception

1. Check that the workspace says **LIVE**.
2. Click **Upload video** and choose an authorized 2–120 second MP4 (set by `MIN_DURATION`/`MAX_DURATION`). The existing
   `data/golden/pouring.mp4` is a licensed 22.88-second test source. Prefer a fixed
   camera, visible hand/object, a simple rigid task, and few occlusions.
3. Selecting a file starts upload and processing automatically; there is no
   separate submit step. Upload and checksum validation precede model inference.
   The browser labels uploads `user_supplied`. Use the CLI below for the registered
   licensed clip so its existing source/license provenance is retained.
4. Wait for preprocessing → Muse → SAM. The last measured live run took about ten
   minutes; mask decoding adds substantial CPU time after the API calls.
5. Scrub the video. Inspect entity masks, candidate IDs, action intervals, missing
   observations, and the tracking report in **Artifacts**. `NEEDS_REVIEW` preserves
   useful outputs but is not an accuracy or readiness pass.
6. Correct ambiguous grounding using the correction controls when needed.
   Corrections create another immutable run and can cause new tracking requests.

For a repeatable CLI test that intentionally makes fresh bounded API calls:

```powershell
.\.venv\Scripts\python.exe -m scripts.live_smoke `
  --source data/golden/pouring.mp4 `
  --idempotency-key local-live-test-001 `
  --report eval/reports/local-live-test.json
```

Reuse the key to resume the same request. Use a new key only when you intentionally
want a new run. Inspect report status, completed/failed inference counts, request
IDs, artifact hashes, and review reasons. Provider cost can remain unknown.

## 2. Enable and test actual reconstruction

The active runtime and approved checkpoints are already installed. See
[geometry runtime](geometry-runtime.md) for versions, hashes, setup and evidence.
The geometry Compose override mounts the external model directory and exposes CUDA.

Configure paths on the **executing Linux worker**, for example:

```text
GEOMETRY_PYTHON=/models/runtime/bin/python
VGGT_CHECKPOINT=/models/vggt/model.pt
SAM3D_BODY_CHECKPOINT=/models/body/model.ckpt
SAM3D_MHR_PATH=/models/body/assets/mhr_model.pt
```

These are the installed paths inside the Linux worker. The host directory defaults
to `E:/MetaAIHack-models`. Keep **Limited-memory preview** enabled on this 4 GiB GPU:
real inference was verified with four sampled frames at 224-pixel input resolution.
Sparse previews can leave gaps; standard dense inference remains unverified here.

Recreate affected services after configuration changes:

```powershell
docker compose -f compose.yaml -f compose.robot.yaml -f compose.geometry.yaml up -d --force-recreate api worker dispatcher
```

In the UI, select the finished perception run, choose the body option if its
runtime is installed, keep **Limited-memory preview** enabled, and click **Run phase 2**. If perception needs review, the
explicit exploratory override allows inspection while retaining all reasons.
Inspect sampled 3D tracks, projection diagnostics, contacts, timing candidates,
`reconstruction_report.json`, and `phase2_handoff.json`. Missing frames must stay
visible as missing; projected consistency is not independent ground truth.

## 3. Robotize, replay, and inspect export

On a finished reconstruction:

1. Choose the manipulating hand and object in **Phase 3**.
2. Enter the correct shot and a continuous source interval containing at least two
   associated geometry samples. Do not span identity changes or long missing gaps.
3. Use `workspace_adaptation` when original dimensions are unknown. This explicitly
   rescales the motion into the robot workspace. Measured calibration is a separate
   mode requiring real evidence; it must not be fabricated.
4. Keep initial gripper state unknown unless you can justify an explicit assumption.
   Contact evidence determines subsequent state. Unknown commands block accepted export.
5. Enable exploratory review only if you intend to inspect unresolved input, then
   click **Run phase 3**.
6. Inspect target/achieved TCP, joint values and errors. Scrub source time and the
   retimed robot timeline. Play the physics replay and read `quality_report.json`,
   `simulation_report.json`, and `export_report.json`.
7. When export succeeds, inspect the `export/dataset/` artifacts. The pinned official
   LeRobot reader is run automatically; `roundtrip_passed=true` must be recorded.
   A dataset folder alone is not evidence that export passed.

Current simulation uses a declared proxy scene and does not establish physical
task success or validated grasps. Consequently current real outputs may remain
Silver/Reject or fail export. Gold and accepted training data must not be forced
by an override. See `phase-three.md` for the exact implemented rubric and limits.

## 4. One command to check the complete real lineage

After geometry is configured and a suitable real perception run exists:

```powershell
.\.venv\Scripts\python.exe -m scripts.baseline_acceptance `
  --phase1-report eval/reports/local-live-test.json `
  --low-vram `
  --robot-config configs/robotization-example.json `
  --idempotency-key local-full-test-001 `
  --report eval/reports/local-full-test.json
```

Edit the example config's hand/object/shot/interval to match that run. The command
reuses Phase 1, runs real reconstruction and Phase 3, records the lineage, and
exits nonzero if a mandatory stage or quality gate is missing. To deliberately
run fresh perception as well, add `--run-perception`. Geometry is configured;
unresolved identity, sparse coverage, contact or quality evidence can still prevent
a full-workflow pass. This command executes new local reconstruction unless cached.

## Exercise installed robot/export components now, without API charges

```powershell
docker compose -f compose.yaml -f compose.robot.yaml -f compose.geometry.yaml run --rm --no-deps worker `
  python -m scripts.smoke_robotization `
  --lerobot-python /opt/lerobot/bin/python `
  --report eval/reports/local-robot-smoke.json
```

This runs synthetic known motion through the real Panda model, MuJoCo physics and
rendering, and official LeRobot writer/reader. Expect 32 valid commands, a rendered
replay, no checked simulation violations, and a successful reader round-trip.
Its quality is intentionally outside the accepted real training subset.
The report's `output` directory contains the replay and local dataset.

To verify Phase 1/2 orchestration and Phase 3 rejection gates using only synthetic
inference, start a separate fixture API without changing the live API:

```powershell
# Start once. If video2robot-fixture-api already exists and is running, reuse it.
docker compose run -d --name video2robot-fixture-api `
  -p 127.0.0.1:58001:8000 -e INFERENCE_MODE=fixture api

.\.venv\Scripts\python.exe -m scripts.smoke_reconstruction `
  --api http://localhost:58001 --report eval/reports/local-phase2-fixture.json
.\.venv\Scripts\python.exe -m scripts.smoke_robotization_api `
  --api http://localhost:58001 --worker-mode queue `
  --source-report eval/reports/local-phase2-fixture.json `
  --report eval/reports/local-phase3-fixture.json
```

The generated-video case checks the complete service path and intentionally
rejects unsupported gripper/quality evidence. It does not validate the human-video
geometry models. The independent robot smoke above exercises successful export.

Stop the frontend with Ctrl+C. `docker compose down` stops the backend while
preserving its volumes. Keep these development services on loopback.
