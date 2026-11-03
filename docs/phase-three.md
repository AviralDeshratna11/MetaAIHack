# Phase 3: Franka compiler, replay, and dataset export

Phase 3 consumes an immutable Phase 2 ITR. It produces a versioned robot trajectory,
an actual MuJoCo replay, quality decisions, diagnostic LeRobot datasets when commands
are known, and a final manifest. Contract version is `0.3.0`; existing `0.1.0` and
`0.2.0` contracts remain available. Pydantic defines the JSON Schema and TypeScript.

## What the implementation does

`packages/robot/retarget.py` selects one shot, hand, object, and interval. Missing
or duplicate poses remain unsupported. It rejects intervals crossing identity
changes, world-frame changes, or excessive geometry gaps. It uses hand positions
during free motion and object translation plus a contact-onset hand offset during
coupled contact. Object/wrist orientation is not invented: TCP orientation is an
explicit configured task constraint. The TCP offset is in robot-base axes.

Two calibration modes make ordinary footage usable without claiming nonexistent
measurements:

- `workspace_adaptation` centers and rescales the observed motion into a configured
  robot workspace. It retains the input center and derived scale and explicitly
  reports that original physical dimensions are unknown.
- `measured` uses a supplied positive scale and proper `base_from_world` SE(3)
  transform, requiring evidence and a residual. This is a calibration input, not
  an automatic assertion that its measurements or grasp are independently valid.

The official Franka Panda MJCF and meshes are downloaded separately from MuJoCo
Menagerie. The downloaded manifest pins upstream commit and hashes every file.
Submission freezes its manifest hash; execution verifies individual asset hashes.
MuJoCo supplies actual model FK and collision detection. SciPy bounded least-squares
IK uses the previous solution, task-space residuals, continuity regularization,
and a collision penalty. Unreachable targets retain residuals and invalid reasons.
This is local numerical optimization, not a globally complete motion planner.

Stop-to-stop quintic joint segments are retimed using analytic velocity and
acceleration maxima. Segments end on a fixed control-rate grid. Every row keeps
source time and execution time, achieved FK, target pose, derivatives, gripper,
collision names, and validity. Interpolated rows are labeled. The interpolated path
is checked again for task-space error and collisions.

Contact inference preserves unknown observations. Persistent CONTACT plus compatible
motion can infer closed/hold; sampled NO_CONTACT can infer open. Missing geometry
does not emit a release. Gripper width transitions have a speed bound. An explicit
initial gripper setting is an assumption, not measured state; unknown intervals
remain invalid. The exporter refuses to replace unknown width with zero.

## Runtimes

The default CPU backend intentionally excludes robot, dataset, and GPU dependencies.
The tested native runtime is Python 3.11, MuJoCo 3.3.7, SciPy 1.15.3. LeRobot 0.4.1
uses a separate environment because its datasets dependency requires Arrow >=21,
while the backend pins Arrow 20.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-robot.txt
.\.venv\Scripts\python.exe -m scripts.robot_assets
py -3.11 -m venv .venv-lerobot
.\.venv-lerobot\Scripts\python.exe -m pip install lerobot==0.4.1 --no-deps
.\.venv-lerobot\Scripts\python.exe -m pip install -r requirements-lerobot.txt
.\.venv\Scripts\python.exe -m scripts.smoke_robotization --lerobot-python .venv-lerobot/Scripts/python.exe
```

The native smoke was actually run; the environment used for this session also
inherited installed system packages. The clean-environment commands above are a
reproduction recipe, not a claim that every optional LeRobot policy/driver package
was exercised. The dataset code checks `lerobot==0.4.1` before writing.

For Docker workers, an optional separate runtime is supplied:

```powershell
docker compose build api
docker compose -f compose.yaml -f compose.robot.yaml -f compose.geometry.yaml up --build -d
```

That override installs CPU robot/dataset dependencies and EGL libraries, sets
`LEROBOT_PYTHON=/opt/lerobot/bin/python`, and leaves the base runtime unchanged.
The image build, headless EGL rendering, 32-frame physics replay and official
dataset writer/reader have now passed in Linux as well as in the native runtime.
The actual RQ queue path also passed with the packaged worker. Interpreter paths
preserve the virtual-environment executable rather than resolving its symlink to
the base Python, a compatibility bug found by the Linux test.
Download robot assets into the shared `data/robots/` directory first. GPU geometry
still needs the separate runtime described in `phase-two.md`.

Server configuration:

| Variable | Meaning |
| --- | --- |
| `ROBOT_ASSETS` | Official asset directory with `asset_manifest.json` |
| `ROBOT_PYTHON` | Optional isolated Python on the executing worker; empty runs in-process |
| `LEROBOT_PYTHON` | Python with pinned official LeRobot and dataset dependencies |

Paths must exist on the executing worker. A Windows executable cannot run inside
a Linux container. Native Windows smoke invokes the existing leased `run_job`
entry point against Docker PostgreSQL/S3 after stopping the Docker queue consumer;
the RQ fork worker itself is not supported on Windows. For continuous operation,
use the Linux robot worker override or a compatible Linux worker environment.
PostgreSQL connection establishment now has a ten-second timeout. The native
test explicitly uses IPv4 and local `sslmode=disable` because this local Docker
port is bound to IPv4; do not copy that TLS setting to a remote database.

## API and orchestration

`POST /v1/videos/{id}/robotize` accepts:

```json
{
  "source_job_id": "FINISHED_PHASE_TWO_JOB",
  "idempotency_key": "robot-v1",
  "allow_review_source": true,
  "config": {
    "hand_id": "HAND_A",
    "object_id": "GLASS",
    "shot_id": "shot_000",
    "start_s": 0,
    "end_s": 5,
    "calibration": {
      "mode": "workspace_adaptation",
      "evidence": "Robot workspace adaptation; original object dimensions unknown"
    },
    "initial_gripper": "unknown"
  }
}
```

Entity IDs, shot, and interval must match the selected reconstruction. The example
is a request shape, not a promise that the existing live clip has valid geometry.
The review override retains source reasons and does not change readiness.
Repeated identical requests reuse a job; conflicting inputs return 409.
Perception corrections/reconstruction reject Phase 3 jobs as invalid sources.

Existing outbox, leases, heartbeat, cancellation fencing, events, and artifact APIs
are reused. Source artifacts are inherited immutably. Phase 3 has one resumable
`robotization` stage after an input snapshot; a retry can recompute local IK/replay
and export within a new attempt. It does not issue new Muse/SAM requests.
Cancellation fences publication; an isolated local subprocess may continue until
completion/timeout. Cross-run Phase 3 cache reuse is disabled by run-specific keys,
so manifests and dataset lineage cannot reference another run accidentally.

| Result endpoint | Output |
| --- | --- |
| `/robot-trajectory?run_id=...` | Typed targets, joints, gripper, timing, diagnostics |
| `/simulation-report?run_id=...` | Physics states, violations, scene and replay details |
| `/robot-quality?run_id=...` | Gold/Silver/Reject and per-check evidence |
| `/phase3-handoff?run_id=...` | Typed immutable artifact references and quality |

All result endpoints are under `/v1/videos/{id}`. Pending outputs return the
existing result-pending error. Export failure can preserve an inspectable
trajectory/replay but must fail export quality; it is not a successful export.

## Simulation and export semantics

MuJoCo advances physics using the official position actuators, linear interpolation
between control ticks, and one explicitly reported second of initial equilibration.
Joint position/velocity/acceleration checks run at every physics substep after
equilibration. TCP tracking and collision diagnostics are also recorded at control
frames. Time quantization between the physics and control grids is reported.

The current scene is an assumed ground plane and a free 0.1 kg box with declared
dimensions/friction. It is not a reconstruction of the source task. The box is never
attached to the gripper. Actual simulated object motion, robot states and rendered
video are retained. Intentional task-contact allowances, a reconstructed table/object
scene, force/torque certification, jerk certification, fluid dynamics, and physical
task-success validation are not implemented. Consequently `task_scene_validated`
is false and `task_success` remains null for this proxy scene.

LeRobot's actual `LeRobotDataset.create/add_frame/save_episode/finalize` writes
v3 files. Its official reader iterates every exported sample and decodes simulator
video. Features are absolute seven-joint targets plus gripper width as `action`,
and measured simulated joints/width at the command interval start as
`observation.state`. Units are radians/meters, with explicit joint names. Images
are simulator observations, never relabeled human camera frames. Episode metadata
provides boundaries; no unsupported terminal field is fabricated.

The round-trip validates lengths, timestamps, action values/order, finite feature
shapes and image decoding. Provenance includes source/execution mapping, robot
hashes and adaptation. Datasets are local diagnostic output and explicitly outside
the accepted training subset. No dataset is uploaded to a hub.

`baseline-v1` quality is a hard-gate rubric, not an empirically calibrated score.
Gold requires every mandatory check, including live inputs, resolved review,
measured scale, valid trajectory, physics limits, official-reader export,
validated task scene, and task success. Silver requires a valid live trajectory,
physics and export but has explicit remaining evidence gaps. Unusable or failed
mandatory software outputs are Reject. Synthetic diagnostics are never Gold.
Because the implemented proxy scene cannot validate task success, current compiled
runs cannot become Gold merely by setting a review override. Quality tests exercise
all rubric branches without fabricating a Gold real-video result.

## Verification tools

- `python -m scripts.smoke_robotization`: synthetic, known reachable motion through
  real Panda IK, MuJoCo physics/rendering, and official LeRobot writer/reader.
- `python -m scripts.smoke_robotization_api`: fixture ITR through HTTP, idempotency,
  local leased worker, immutable storage, hash checks, quality and invalid-source gates.
  Stop the Docker worker first for its native mode; start it afterward. With the
  robot image running, pass `--worker-mode queue` to exercise normal RQ delivery.
- `python -m scripts.baseline_ablations`: frozen-input contact-channel removal,
  semantic-only scoring, refinement toggle, basic/constrained IK. No provider calls.
- `python -m scripts.baseline_acceptance`: one real-video lineage through all phases;
  exits nonzero for missing mandatory stages or quality evidence. Pass
  `--run-perception` only to intentionally make fresh bounded API calls. Select a
  task using `--robot-config path.json`. Existing expensive artifacts are reusable.
- `python -m scripts.runtime_preflight`: sanitized dependency/checkpoint inventory.

The UI adds Phase 3 submission, configuration, source/retimed command scrubbing,
target/achieved TCP and joint diagnostics, quality reasons, physics replay and
artifact downloads. Source and replay timelines use the retained time map.
Browser interaction verification is currently blocked by Windows URL detection;
TypeScript and production builds are independent checks.

## Official references

- [MuJoCo Menagerie Panda assets](https://github.com/google-deepmind/mujoco_menagerie/tree/98a70c569c4c1b6da467a20012f766ee1f8dc521/franka_emika_panda), Apache-2.0.
- [Franka robot control requirements](https://frankarobotics.github.io/docs/robot_specifications.html).
- [Official LeRobot v3 format](https://huggingface.co/docs/lerobot/lerobot-dataset-v3)
  and [0.4.1 source](https://github.com/huggingface/lerobot/tree/v0.4.1).
- [VGGT model](https://huggingface.co/facebook/VGGT-1B), CC-BY-NC-4.0;
  [SAM 3D Body installation](https://github.com/facebookresearch/sam-3d-body/blob/main/INSTALL.md).

Dependencies, checkpoint access, licenses and calibration evidence are separate
from software correctness. The current live baseline status is in
`docs/baseline-acceptance.md` and `eval/reports/baseline-live.json`.
