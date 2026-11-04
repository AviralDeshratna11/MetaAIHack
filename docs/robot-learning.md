# Robot-learning output and verification

The compiler now produces a downloadable learning bundle containing official
LeRobot data and, when a task is explicitly configured, offline RL transitions.
The repository also contains a Gymnasium environment and an offline TD3+BC learner.
These paths were exercised with actual Panda physics and saved policy evaluation.

Final evidence is in `eval/reports/robot-learning-acceptance.json`. The rebuilt
worker passed 92 regression tests; generated contracts, TypeScript and production
build checks passed. All 105 artifacts of the reviewed compiled run passed hashes.
A separate fresh two-second provider probe completed Muse and SAM calls with zero
cache hits; Muse returned GRASP/STIR and SAM produced 30 frame records. It is not
part of the original compiled lineage. Actual provider cost remains unknown.
Browser interaction remains unverified: computer-use stopped because the Windows
browser URL could not be established confidently. API readiness and frontend HTTP
200 were verified independently.

## If the viewer shows no 3D sample

Check the counters first. Seven cameras with zero hand/object estimates means
depth/camera inference ran, but no observed identities could be associated with
the scene. Click **Review this run's source identities**, save the necessary
candidate corrections, then reconstruct the corrected perception run. A review
override or repeated reconstruction of the original source does not fix identity.

If estimates are nonzero, the current video time may be outside sampled frames.
Click **Jump to nearest 3D sample** or select a time from **Sample time**. The
viewer seeks the original video and shows only geometry observed at that frame.
For a 16.4-17.6 second reconstruction, time 0.00 seconds has no sampled pose.

Links can open a specific video/run directly using
`http://127.0.0.1:53000/?video=VIDEO_ID&run=RUN_ID`. This avoids confusing separate
uploads with the same filename. Corrections belong to one immutable run lineage;
they do not automatically transfer to another upload of the same clip.

## What the output means

Human RGB footage does not contain robot telemetry, measured contact forces,
metric dimensions or rewards. The compiler reconstructs interaction hypotheses,
adapts supported motion to the robot, and records **measured simulated** states.
Task rewards are configured simulator objectives. They are not inferred physical
ground truth from the original video.

The complete pouring-and-stirring task has not been validated. A reviewed source
interval, 17.0-17.2 seconds, has successfully produced an **endpoint reach adaptation**.
This is useful for testing the training pipeline, but reaching that endpoint does
not demonstrate stirring with a spoon, a stable grasp or fluid transfer.

## Bundle contents

| File/directory | Purpose |
| --- | --- |
| `export/dataset/` | Official LeRobot 0.4.1/v3 dataset and provenance sidecar |
| `rl/transitions.parquet` | Typed state/action/successor/reward transitions |
| `rl/rl_report.json` | Task, controller, reset conditions, feature meanings, checksum and eligibility |
| `robot_trajectory.json` | Targets, joints, gripper, source/execution map, retiming and residuals |
| `simulation_report.json` | Actual simulated states, task diagnostics and checked violations |
| `quality_report.json` | Gold/Silver/Reject and outstanding reasons |
| `source_provenance.json` | Source hashes, reconstruction fingerprint, correction reviewers, hosted request IDs and compiler hash |
| `learning_manifest.json` | Bundle hashes, lineage, task scope, robot assets and training eligibility |

`learning_bundle.zip` is published with Phase 3 artifacts. The UI exposes
**Download robot learning bundle**. A bundle can exist when RL output is blocked;
read its reports before training. Robot assets remain an explicitly pinned external
dependency, available through `python -m scripts.robot_assets`. Model checkpoints
are not needed to train on already compiled transitions.

## RL transition semantics

Each row contains:

- `observation`: 21 values: seven joints in radians, gripper width in meters,
  seven joint velocities, TCP xyz and object xyz in robot-base meters.
- `action`: eight values: seven absolute joint targets and gripper width for the
  **next control-tick endpoint**. The controller interpolates from the current
  command to this endpoint. This is the action that produced the measured successor.
- `next_observation`: measured simulated state after the action interval.
- `reward`: declared simulator shaping evaluated at the successor state.
- `terminated`: true only when the declared task succeeds in this exported path.
- `truncated`: end of the available recording without task termination.
- `discount`: zero for termination and one for truncation/continuation; the learner
  additionally applies its configured gamma. A time limit must not erase bootstrapping.
- Timing, lineage and `accepted_training_subset` fields.

The last command has no recorded successor and is excluded from transitions.
Unknown or invalid gripper/trajectory commands cannot silently become valid data.
The official LeRobot dataset retains its final hold row separately.

The interactive environment adds goal xyz and normalized elapsed episode time to
these 21 state values, producing a 25-value observation. Episode phase is explicit
because a finite-horizon demonstration can revisit similar physical states while
requiring different subsequent commands. Reset uses the **initial command**, then
the same equilibration as replay; resetting to an already settled measured state
would apply settling twice and change the initial distribution.

## Supported configured simulation tasks

`TaskScene` currently supports reach and rigid box pick/place. Geometry, mass,
friction, support surface, goal, tolerances and horizon are explicit configured
inputs. Reach requires persistent TCP proximity without checked violations.
Pick/place requires observed lift, goal proximity, support, open gripper and
persistence. The object is never attached to the gripper. Finger-object contact
is the named intentional-contact allowance for pick/place.

Reach has actual successful replay and learned-policy evidence. The pick/place
success-rule logic has positive/negative tests, but an end-to-end learned physical
pick/place episode has **not** been demonstrated. Neither task validates reconstructed
source dimensions or real-world deployment.

## Reproduce the implemented paths

Start the configured local services:

```powershell
docker compose -f compose.yaml -f compose.robot.yaml -f compose.geometry.yaml up -d
```

The updated robot image recipe installs `requirements-rl.txt` inside `/opt/lerobot`.
On this machine the running worker was also provisioned and checked directly.
Rebuilding a container requires rebuilding the updated image or reinstalling those
dependencies; packages installed in a container's writable layer are not a volume.

### Independent controlled learning case

```powershell
docker compose -f compose.yaml -f compose.robot.yaml -f compose.geometry.yaml exec worker `
  python -m scripts.smoke_robotization --task-reach `
  --lerobot-python /opt/lerobot/bin/python --report eval/reports/learning-smoke.json
```

Read the report's `output` path, then train using that directory's `rl` folder:

```powershell
docker compose -f compose.yaml -f compose.robot.yaml -f compose.geometry.yaml exec worker `
  /opt/lerobot/bin/python -m scripts.train_offline `
  --data data/phase3-smoke/REPORTED_RUN/rl --updates 2000 `
  --allow-review --output data/training/NEW_RUN
```

The recorded controlled case contains 32 transitions. The learner used 1,000
behavior warm-up updates and 2,000 TD3+BC updates. Three evaluations reached the
goal without checked violations. All use the same initial state: three seeds do
not demonstrate task diversity or generalization. Earlier failed learners are
retained locally, including an acceleration failure and time-limit failures.

### Reviewed real-video lineage

`scripts.repair_pouring_associations` is a **source-specific assistant-reviewed**
helper, not a generic autonomous identity solution. It uses the supplied frame and
stored candidate masks, preserves gap boundaries, and makes no hosted model calls.
Its successful report is `eval/reports/pouring-repair.json`.

The selected reconstruction used seven sampled frames in aligned, bounded windows:
246, 249, 252, 255, 258, 261 and 263. It produced 14 associated hand estimates,
17 object estimates, 34 relative rows and four contact events. Some hands remain
surface centroids because body-wrist alignment was not supported; the report
retains that fact. Window alignment consistency is not independent geometry accuracy.

Run the queued compiler against that frozen input:

```powershell
.\.venv\Scripts\python.exe -m scripts.live_learning_smoke
```

It checks input continuity, queues Phase 3, hashes every published artifact and
checks physics, official-reader export and RL transition round-trip. It exits
nonzero for those execution failures. Its success status is explicitly
`adapted_simulation_learning_passed`, not full source-task acceptance.

`configs/pouring-endpoint-adaptation.json` declares the short source interval,
workspace adaptation, task orientation, slower execution and final hold. It is
source-specific. Its endpoint goal is a configured robot adaptation, not a measured
physical destination in the original scene.

The recorded video-derived case is Silver, with 11 RL transitions before its
configured goal termination. A learner trained on those transitions also reached
that configured endpoint in three fixed-state evaluations. Metric calibration,
source-task validation and grasp validity remain unresolved.

### Verify a downloaded bundle and train

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_learning_bundle `
  data/final-training/video-derived-learning.zip `
  --output data/final-training/verified

docker compose -f compose.yaml -f compose.robot.yaml -f compose.geometry.yaml exec worker `
  /opt/lerobot/bin/python -m scripts.train_offline `
  --data data/final-training/verified/rl --updates 2000 --allow-review `
  --output data/training/NEW_VIDEO_RUN
```

The trainer validates hashes, finite features and bounds, and refuses reviewed
data unless `--allow-review` is supplied. This flag records an explicit choice;
it does not change the dataset's eligibility. It saves `policy.pt` and
`training_report.json`, reloads the policy and evaluates it in actual physics.
State normalization, bounded action support, seed, losses, reset conditions and
an explicit endpoint slew adapter are reported.

Replay the saved video-derived policy and render its measured simulated behavior:

```powershell
docker compose -f compose.yaml -f compose.robot.yaml -f compose.geometry.yaml exec worker `
  /opt/lerobot/bin/python -m scripts.evaluate_offline `
  --policy data/training/video-derived-endpoint-v1/policy.pt `
  --data data/final-training/video-derived/rl `
  --video data/final-training/learned-policy-replay.mp4
```

For separate interactive PPO experiments, use `scripts.train_simulation` with a
JSON `TaskScene` and an explicit step budget. That path trains from new simulator
experience; it does not consume a human-video dataset. PPO convergence is not
claimed by the current acceptance evidence.

## What remains outside the demonstrated result

The original blueprint includes P2/P3 extensions: SAM 3D Objects, DINO re-ID,
RLDS/RLBench adapters, a second robot, bimanual and dexterous retargeting. These
have not been implemented/verified by the current changes. The four headline
novelty ideas are represented by ITR, contact boundary fusion, explicit QC and
separation of perception from robotization; multi-robot execution remains untested.

The current source includes a stabilizing hand and liquid/utensil interaction.
Complete source-task learning needs supported hand/tool geometry, a suitable task
scene and task-specific reward/success evidence. This release does not promote
an endpoint reach test into a stirring or pouring success claim.

Official references: [Gymnasium environment API](https://gymnasium.farama.org/api/env/),
[TD3+BC author implementation](https://github.com/sfujim/TD3_BC),
[official LeRobot dataset format](https://huggingface.co/docs/lerobot/lerobot-dataset-v3).
