# Test the workflow and understand full-clip replication

The existing successful real-video sample covers only 17.0–17.2 seconds of the
pouring/stirring source. Its task is an adapted endpoint reach. It does not contain
the entire approximately 22.87-second manipulation. Increasing playback duration
or slowing that short segment does not reproduce the full source action.

## Start the local app

1. Start Docker Desktop and wait for the Linux engine to be running. Keep the
   existing ignored `.env` and approved model checkpoints.
2. Open a PowerShell terminal in this repository:

```powershell
docker compose -f compose.yaml -f compose.robot.yaml -f compose.geometry.yaml up -d
npm.cmd run build
npm.cmd run start
```

3. Open `http://127.0.0.1:53000`. API status and interactive contracts are at
   `http://localhost:58000/docs`. The current host uses the already configured
   external geometry/RLDS runtimes. See `SUBMISSION.md` for portable installation.

## Phase 1: semantics and tracking

1. Click **Upload video**, select the authorized original clip, and wait for the
   queued job to finish. A real-model run must show **LIVE** rather than fixture.
2. Scrub the beginning, pour, glass placement, spoon grasp and stirring intervals.
   Inspect the action plan and the hand/glass/bowl/spoon masks at each interval.
3. If identities are uncertain, select a finished **Phase 1 — perception** run
   from **Selected run** and expand **Correct an entity grounding**. Select the
   entity and an observed SAM candidate at the paused frame, then save the reviewed
   association. Confirm the mask visually; candidate ordinals alone do not prove
   identity across gaps. Corrections create a new human-assisted source run.
4. Continue from the corrected run. A review override does not repair identities.

## Phase 2: sample the entire clip

1. In **Reconstruct the interaction**, click **Use whole clip**. The start becomes
   zero and the end uses the clip duration. This enables aligned windowed sampling.
2. Keep the low-memory option for this 4 GiB GPU. Its description refers to the
   four-image inference window; windowed mode can now sample a larger total interval.
3. Enable **Use SAM 3D Body for anatomical wrists** if the approved runtime is
   configured. Enable exploratory review only when unresolved evidence is intended.
4. Click **Run phase 2**. This is substantially more expensive than seven sampled
   frames: sampling is at 5 FPS with extra action-boundary samples and bounded GPU
   windows. No reliable full-clip runtime estimate has yet been measured here.
5. Check nonzero hand/object counts and use **Sample time** to inspect samples
   throughout the beginning, middle and end. Camera count alone is insufficient.
   Inspect missing data, alignment failures and identity changes.

The previous UI's 32-sample cap has been replaced with an explicit interval-based
budget; the schema permits up to 512 samples per shot. This removes a software
budget obstacle, but does not guarantee successful reconstruction or association.

## Phase 3: test compilation and export

For the previously supported short endpoint test:

1. Select a finished reconstruction, then scroll to **Compile a robot
   demonstration**. Choose the robot.
2. Click **Suggest supported interval and endpoint task**, then inspect the
   proposed hand, object, interval and task. The suggestion is a reach adaptation.
3. Retain workspace adaptation if no dimensions are measured. Inspect gripper
   evidence; an explicit initial assumption cannot validate a later grasp.
4. Enable **Explore unresolved source** only for a diagnostic run. Optionally
   select **Include official TFDS/RLDS export**.
5. Click **Run phase 3**, inspect the quality reasons and play the replay. Download
   **robot learning bundle**, or visit **Robot learning datasets** at `/datasets`.

For an attempted full-clip compilation, click **Use whole clip interval** after
configuring the task. This sets the complete source interval, speed scale 1,
no extra final hold, strict paired-geometry coverage and full-recording RL export.
The paired-geometry preflight will reject missing boundaries, unsupported gaps,
world changes and identity changes. Do not disable coverage to present a short
interval as a complete result. Simulation execution may exceed source duration
when joint limits require retiming; the source/execution map records this.

The checkbox **Retain the entire trajectory in RL data, including after endpoint
success** prevents early reach success from discarding subsequent transitions.
In this mode recording end is truncation, and endpoint success does not certify
the full action. It changes export episode boundaries, not the reward into a
validated pouring/stirring objective.

## What must be added/resolved for the actual complete action

This source changes manipulated objects and uses two hands. The current compiler
selects one hand, one object, one shot/world and a configured constant tool
orientation per run. It cannot yet reproduce the entire glass-pour-place-spoon-
grasp-stir sequence as a validated single continuous episode.

That requires continuous reviewed geometry, task-stage composition with explicit
object switching, measured or declared changing tool orientations for pouring,
validated grasp/release and collision-compatible object/support behavior. The
supporting hand must be reproduced or replaced by a declared valid fixture.
Fluid-transfer success needs a suitable task model and cannot be inferred from
box-proxy reach success. These are remaining implementation/data-validation
requirements, not settings that the new full-clip buttons solve.

## Check the downloaded ZIP

Extract the ZIP first. New bundles additionally include the standalone
`simulation/simulation_replay.mp4`. The LeRobot video stream remains under
`export/dataset/videos/observation.images.simulator/`.

Verify these reports:

- `robot_trajectory.json`: requested interval, actual source coverage and execution
  times. Coverage must span the complete desired interval within sampling tolerance.
- `rl/rl_report.json`: `episode_end: trajectory_end`, the complete `source_interval_s`,
  execution duration and the expected transition count. At 30 Hz, 22 seconds gives
  roughly 660 transitions; exact counts depend on retiming and the actual duration.
- `simulation_report.json`: actual physics, tracking/limit/collision checks and task
  scope. It must describe the intended task, not just a convenient endpoint.
- `quality_report.json`: outstanding evidence and training eligibility.
- `learning_manifest.json`: checksums and lineage. Never infer acceptance from ZIP
  availability or video duration alone.

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_learning_bundle PATH_TO_ZIP --output data/verified-new-bundle
```

Training and evaluation are separate from the replay video. Follow
`robot-learning.md` for TD3+BC commands. A successful optimizer run does not prove
replication of a task missing from the reconstructed episode.

## Verification of this update

Focused coverage, RL-export and robotization tests passed (12 tests). TypeScript
checks passed. The host regression suite passed 95 tests with four skips for
unavailable optional runtime checks. Docker Desktop was stopped during this update, so no new live
full-clip reconstruction, compiled 22-second source-action replay or policy
training result is claimed. Existing ZIPs and historical runs remain unchanged;
the new controls and files apply to newly submitted runs.
