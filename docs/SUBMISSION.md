# Video2Robot submission guide

Video2Robot compiles human manipulation footage into traceable simulated robot
demonstrations and review-gated learning data. The baseline spans upload,
perception, reconstruction, interaction reasoning, robotization, physics replay,
dataset export and a runnable learning environment. Demonstration recording is
deferred at the user's request.

This is a local hackathon prototype. It has no multi-user authentication and its
services bind to loopback. Dataset validity and physical robot readiness are
separate from successful software execution.

## Meta models and component responsibilities

| Component | Responsibility | Evidence and limits |
| --- | --- | --- |
| Muse Spark 1.3 | Semantic objects, action intervals and dependency graph | Real hosted calls recorded; semantic grasp is not contact truth |
| SAM 3.1 | Masks and candidate tracking | Real hosted calls recorded; reviewed associations remain labeled |
| VGGT | Camera/depth reconstruction in bounded GPU windows | Actual local inference; scale is relative without measurements |
| SAM 3D Body | Supported anatomical hand/body evidence | Actual checkpoint inference; missing wrists may use labeled surface-centroid fallback |
| Interaction trajectory representation | Object-relative motion, contact evidence, refined actions and provenance | Shared across robot adapters; uncertainty stays attached |
| Panda / FR3 adapter | TCP targets, gripper inference, constrained IK and retiming | Official pinned assets; FR3 uses an explicit Panda-hand simulation composition |
| MuJoCo | Actual physics, measured simulated state, collisions and task checks | Configured proxy scene; no fluid-transfer or physical deployment validation |
| LeRobot / RLDS | Portable learning formats and official reader checks | LeRobot 0.4.1/v3 and TFDS 4.9.9 nested RLDS episodes |

The technical novelty is the interaction representation joining semantic intent
with geometric evidence, contact-conditioned refinement, and explicit
self-validation across reconstruction, IK, dynamics and dataset loading. The same
representation feeds two arm adapters. This describes the implemented system;
novelty relative to all published research has not been established.

## Implemented user workflow

1. Open `http://127.0.0.1:53000`, upload an authorized manipulation clip and wait
   for preprocessing, Muse semantics and SAM tracking.
2. Select a finished perception run. Inspect masks and candidate identities;
   **Correct an entity grounding** can save an association using existing masks.
   Corrections produce a new immutable, human-assisted run.
3. Run Phase 2 on a continuous task interval. Use bounded windows for a small GPU.
   Check the hand/object counters; cameras alone are insufficient. Seek a sampled
   time in the 3D viewer. Review flags never disappear merely because an override
   is selected.
4. In **Compile a robot demonstration**, choose Panda or FR3 and click
   **Suggest supported interval and endpoint task**. This proposes a continuous
   observed segment and an explicitly adapted reach objective. It does not infer
   that the original manipulation was solved. Inspect the hand, object, interval,
   task, initial gripper assumption, speed and workspace radius.
5. For genuine measured geometry, expand **Fit measured scene-to-robot
   calibration** and supply corresponding non-collinear scene/base points plus
   measurement evidence. Otherwise retain **workspace_adaptation**, which
   intentionally adapts motion without claiming physical scale.
6. Optionally enable **Include official TFDS/RLDS export** when that runtime is
   installed. Allow exploratory processing only if you intend to retain source
   review reasons, then click **Run phase 3**.
7. Inspect quality reasons, target/achieved poses and physics replay. Download the
   learning ZIP. **Robot learning datasets** opens `/datasets`, with quality
   filtering, run lineage, checksums and bundle downloads.
8. Verify the archive and read `rl/rl_report.json` before training. Silver data
   requires an explicit `--allow-review` in the learner. Simulated observations
   and endpoint rewards do not establish the original pouring/stirring task.

The advanced JSON configuration remains available for explicit grasp offsets,
task scene geometry, orientation constraints and solver thresholds. Unknown
gripper commands and invalid trajectories cannot silently become accepted actions.

## Reproducible startup and checks

Preserve an existing `.env`. Store credentials only in ignored configuration.
See [geometry runtime](geometry-runtime.md) for gated checkpoint setup and the
external model directory. Build the base before the optional robot image:

```powershell
docker compose build api
docker compose -f compose.yaml -f compose.robot.yaml build worker
docker compose -f compose.yaml -f compose.robot.yaml -f compose.geometry.yaml up -d
npm.cmd ci
npm.cmd run build
npm.cmd run start
```

The configured local machine also has `/models/rlds_runtime/bin/python`, isolated
from GPU inference and PyTorch learning. A new machine can build the portable
optional export image instead, applying its override last:

```powershell
docker compose -f compose.yaml -f compose.robot.yaml -f compose.geometry.yaml -f compose.rlds.yaml build worker
docker compose -f compose.yaml -f compose.robot.yaml -f compose.geometry.yaml -f compose.rlds.yaml up -d
```

The optional image also built successfully during this session. The current
long-running worker uses the external runtime; the image provides a separate
portable installation of the same pinned export dependencies.
The image's official TFDS reader also passed on the downloaded queued-run ZIP.
Tested RLDS pins are in `requirements-rlds.txt`, including Protobuf 6.33.5.

Download assets with `python -m scripts.robot_assets --robot panda`, then
`python -m scripts.robot_assets --robot fr3`. Both resolve the tested immutable
Menagerie commit by default and use separate directories. Checkpoints, media,
datasets and third-party robot assets stay outside Git.

```powershell
docker compose -f compose.yaml -f compose.robot.yaml -f compose.geometry.yaml exec worker python -m pytest -q
docker compose exec api python -m scripts.export_schemas --check
npm.cmd run schemas:check
npm.cmd run typecheck
npm.cmd run build
.\.venv\Scripts\python.exe -m scripts.submission_check
```

`submission_check` is read-only and makes zero model inference calls. Its success
means service/routes are available; it is not a substitute for regression,
simulation, model accuracy or full live acceptance. Existing scripts
`baseline_acceptance`, `live_learning_smoke`, `baseline_ablations`,
`smoke_robotization` and `verify_learning_bundle` cover those separate checks.
See [robot learning](robot-learning.md) for the TD3+BC and PPO commands.

## Evidence and remaining scope

Final software verification on 4 November 2026: 97 regression tests passed;
JSON Schema, generated types, TypeScript and the production build passed. Both
the compiler and dataset catalog returned HTTP 200. Browser interaction remains
separately unverified.

- `eval/reports/submission-check.json`: redacted runtime and route inventory.
- `eval/reports/fr3-software-smoke.json`: synthetic inputs, actual FR3 physics,
  rendered replay, valid commands and official LeRobot reader.
- `eval/reports/rlds-software-check.json`: actual TFDS reader of the previously
  compiled real-video-derived transitions; includes the final observation step.
- `eval/reports/submission-integration.json`: newly queued robotization of the
  reviewed real-video geometry, actual physics, both official readers, 43 commands,
  11 RL transitions and 111 verified published artifact hashes. The 20-file ZIP
  also passes independent manifest verification. Result: Silver, not accepted.
- `eval/reports/robot-learning-acceptance.json`: earlier live-model lineage,
  simulation/learning checks and explicit review limitations.
- `eval/reports/learning-ablations.json`: frozen-input diagnostics, not independently
  annotated accuracy.

The current real-video output is Silver, with simulated endpoint-reach rewards;
full pouring/stirring, metric grasp/support and task transfer remain unvalidated.
SAM 3D Objects, DINO re-identification, RLBench integration, bimanual and dexterous
retargeting remain outside the accepted implementation. SAM 3D Objects upstream
requires a much larger supported GPU runtime and gated assets than this 4 GiB
machine. These research extensions must not be presented as finished submission
features. No physical robot deployment has been performed. Browser interaction
verification is also outstanding; API, TypeScript and production builds are
checked separately.

The project can be presented as a functioning, evidence-aware baseline prototype.
It cannot honestly be presented as a completed implementation of every optional
feature in the blueprint or as automatically producing validated data for any
arbitrary physical manipulation task.
