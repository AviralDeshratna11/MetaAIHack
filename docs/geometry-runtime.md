# Configured local VGGT and SAM 3D Body

Both models are installed, their official checkpoints have been downloaded and
SHA-256 verified, and real inference has completed through the app's API/queue.
No synthetic geometry was substituted. Heavy files are on E: because the project
drive did not have enough free space for these checkpoints.

## Active configuration

Start or recreate the services with all three Compose files:

```powershell
docker compose -f compose.yaml -f compose.robot.yaml -f compose.geometry.yaml up -d
npm.cmd start
```

`compose.geometry.yaml` exposes the NVIDIA GPU to the worker and mounts
`E:/MetaAIHack-models` read-only at `/models` in the API and worker. Set
`GEOMETRY_MODELS_DIR` to change the host directory. Keep the external model folder
and `data/vendor/` source checkouts; they are intentionally outside Git artifacts.

| Setting | Active path in the container |
| --- | --- |
| `GEOMETRY_PYTHON` | `/models/runtime/bin/python` |
| `VGGT_CHECKPOINT` | `/models/vggt/model.pt` |
| `SAM3D_BODY_CHECKPOINT` | `/models/body/model.ckpt` |
| `SAM3D_MHR_PATH` | `/models/body/assets/mhr_model.pt` |
| Body configuration | `/models/body/model_config.yaml` |
| DINOv3 source | `/models/sources/dinov3` |

The isolated runtime uses Python 3.11.13, Torch 2.5.1+cu121, torchvision
0.20.1+cu121, NumPy 1.26.4, Lightning 2.5.1, timm 1.0.15, and accelerate 1.10.1.
It is separate from backend Arrow/NumPy and the LeRobot dataset runtime.

Models:

- VGGT checkpoint revision `860abec7937da0a4c03c41d3c269c366e82abdf9`.
- SAM 3D Body DINOv3 checkpoint revision `11aaa346c7204874a1cbafe3d39a979080b2c55a`.
- VGGT source `a288dd0f14786c93483e45524328726ab7b1b4ce`.
- SAM 3D Body source `b5c765a0d89d789985e186d396315e7590887b94`.
- DINOv3 source `6876159a11b4df116f30f667f8c9888617df0751`.

The backbone constructor is routed to pinned local DINOv3 code. Online Torch Hub
loads/pretrained downloads are blocked by the adapter. Model/runtime inference
needs no Hugging Face token once these assets are present. The temporary credential
handoff used for the approved download was deleted; no token is in the repo.

## Test in the app

Open **http://127.0.0.1:53000**, select a finished live perception run, then:

1. Leave **Limited-memory preview** enabled on this 4 GiB GPU. It samples four
   frames at 224-pixel model input resolution.
2. Enable **Use SAM 3D Body for anatomical wrists**.
3. Resolve perception identity warnings, or explicitly allow exploratory processing
   while retaining review reasons.
4. Click **Run phase 2**. Inspect geometry, contact evidence, reports and artifacts.

Low-memory mode runs the real VGGT aggregator in reduced precision on CUDA and
its original camera/depth heads in FP32 on CPU. Unused point/track heads are not
loaded. Body loading uses mmap and the official model/state-loader components.
The original checkpoints are not quantized or modified.

This preview is sparse and can leave gaps that block Phase 3 retargeting. Standard
mode remains available for a suitably provisioned GPU; it has not been validated
on this 4 GiB device. A successful model execution does not establish correct
identity, calibration, contact, grasp, or physical task success.

## Verification performed

| Test | Observed result |
| --- | --- |
| VGGT on two real video frames | Completed; CUDA peak 1,867,259,904 bytes |
| VGGT + body on two real frames | Completed; two body hypotheses; 196.815 seconds; CUDA peak 3,633,549,312 bytes |
| Live Phase 2 through HTTP/RQ/storage | Completed with review; four sampled cameras and four body hypotheses; 53 artifact hashes verified |
| Queued model runtime | 183.213 seconds; CUDA peak 3,637,203,456 bytes |
| Queue submission through artifact checks | 317.156 seconds |
| Regression suite after integration | 85 passed in the worker image |

Evidence is in `eval/reports/geometry-configured.json`, `live-vggt.json`,
`live-geometry-models.json`, and `live-phase2-geometry.json`.

The live Phase 2 job is `job_516f37c50dcf4eb2b803cb94a416b079`, run
`run_74e3d6a66320412aacae442400f22d5b`. It reused the existing real Muse/SAM run
without new hosted inference calls. Its sample indices were 0, 20, 340 and 342.
It produced zero associated hand-pose rows and two object-pose rows because
upstream hand/glass/bowl identities remain ambiguous. The four raw body hypotheses
are preserved; they are not silently promoted to associated hand poses.

Thus the missing-runtime/checkpoint blocker is resolved. This source still needs
identity correction and suitable continuous geometry before robotization; do not
interpret `NEEDS_REVIEW` as a complete baseline acceptance pass.

## Recheck or repeat

Offline import/CUDA/checkpoint integrity check:

```powershell
docker compose -f compose.yaml -f compose.robot.yaml -f compose.geometry.yaml exec worker `
  /models/runtime/bin/python -m scripts.geometry_check
```

Repeat the queued live reconstruction, reusing the already uploaded/perceived video:

```powershell
.\.venv\Scripts\python.exe -m scripts.live_reconstruction_smoke --key verified-real-geometry-v1
```

The same key returns the existing job. Use a new key to intentionally execute
another local model run. No Muse/SAM requests are submitted by this command.
For the unified acceptance controller on this device, pass `--low-vram` alongside
the selected robot config. Downstream quality gates can still fail legitimately.

`requirements-geometry.txt` and `requirements-geometry-body.txt` pin the inference
dependencies. `scripts.geometry_assets` downloads official checkpoint revisions,
requires adequate disk space, checks upstream LFS SHA-256, and keeps credentials
and signed URLs out of output. `scripts.geometry_source_assets` downloads pinned
official source code. A new machine must provision its own CUDA environment and
approved checkpoint access; the external virtual environment is machine-specific.
