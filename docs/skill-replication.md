# Phase 4: skill replication

Phase 3 retargets where the hand was. Phase 4 works out **what was done to the
object** and has the robot do that again on a generated scene. The demonstrated
hand coordinates are not replayed. Contract version is `0.4.0`; earlier contracts
are unchanged apart from additive fields.

| What was demonstrated | How it is recognized | What the robot does |
| --- | --- | --- |
| Open or close a lid (laptop, box) | Hand moves on an arc about a level axis | Grasps the lid's edge and follows the hinge |
| Open or close a door | Arc about an upright axis | Grasps a bar handle and follows the hinge |
| Pull or push a drawer | Hand moves on a line | Grasps a bar handle and follows the slide |
| Pick up, carry, set down or keep holding | Object moves with the hand, plan says lift/carry/place | Top-down grasp, carry over an arch, release or hold |
| Press a button | Hand stays put, plan or name says press | Presses with closed fingertips; the button springs back |
| Turn a knob | Hand stays put, plan or name says rotate | Grasps the knob bar and turns it |

Pouring, stirring, wiping, insertion and two-handed coordination are not
supported; such intervals are refused with a pointer to trajectory mode.

## See it run

No web stack, database or model credentials are needed for the diagnostic path:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-robot.txt
.\.venv\Scripts\python.exe -m scripts.robot_assets
.\.venv\Scripts\python.exe -m scripts.replicate_demo --demo laptop_lid
```

Demonstrations: `laptop_lid`, `close_lid`, `drawer`, `close_drawer`, `door`,
`pick_place`, `pick_up`, `press_button`, `turn_knob`. Each run writes a directory
under `data/replication/` with `viewer.html` (replay video, inferred skill, progress
synced to playback, moved-scene results), the reports and the learning bundle.
`--robot fr3` uses the FR3 composition. Those demonstrations are **synthetic**
hand paths in a camera-like, relative-scale world with noise. They exercise real
IK, physics and exporters; they say nothing about real footage.

From an existing reconstruction file:

```powershell
.\.venv\Scripts\python.exe -m scripts.replicate_demo --itr path\to\interaction_trajectory.json.gz --hand HAND_A --object LAPTOP
```

From real footage through the queued stack (Docker, live models, GPU geometry):

```powershell
docker compose -f compose.yaml -f compose.robot.yaml -f compose.geometry.yaml up -d
.\.venv\Scripts\python.exe -m scripts.live_smoke --source clip.mp4 --source-uri URL --rights licensed --report eval/reports/real-skill/NAME-phase1.json --idempotency-key NAME-v1
.\.venv\Scripts\python.exe -m scripts.real_video_replication --phase1 eval/reports/real-skill/NAME-phase1.json --name NAME
```

The first command makes hosted model calls (bounded by `MAX_MODEL_CALLS`). The
second makes none: it resolves identities from stored tracks, reconstructs the
manipulation interval on the local GPU, infers the skill, queues the replication
and downloads the verified results to `data/real-skill/NAME/`.

In the web app: select a finished reconstruction, set **What to reproduce** to
**The skill**, click **Infer the skill from this reconstruction**, then **Run phase 3**.
On a perception run, **Resolve hand and object identities automatically** applies
the same identity heuristic. `npm run start` picks a bindable loopback port and
prints it (Windows sometimes reserves 53000); set `WEB_PORT` to choose one.

## How it works

1. **Identities** (`workers/perception/associate.py`). Two hands share one
   segmentation concept, so the tracker leaves them unassigned rather than guess.
   The semantic plan says which hand manipulates and which holds, and when. The
   proposer assigns candidates by how much each moves during those actions, and
   proposes nothing when the margin is small. Applied associations are stored as
   `reviewed_by: heuristic` and add a review reason. No hosted calls.
2. **Skill inference** (`packages/robot/skill.py`). The hand path while in contact
   is fitted with a resting point, a line and an arc; residuals and BIC are kept.
   - Hinge angle is scale free. Pull versus push is the cosine between the reach and
     the motion. A lid's open/close uses an up hint (default: camera up).
   - The object's name is used where geometry alone is weak: it breaks slide/hinge
     ties, and says whether a hinge is level (lid) or upright (door). With a named
     hinge the arc is fitted with its axis held to that orientation and is not
     weighed against a line. This is what made real, noisy footage usable.
   - Actions are filtered to the selected hand using the semantic plan, so one
     hand's hold is not read as the other's press.
   - A press or a twist leaves no hand translation to measure. They are recognized
     from the plan or the object's name; depth and angle are declared defaults.
3. **Scale** (`packages/robot/metric.py`). With measured calibration, sizes come from
   it. Otherwise, when SAM 3D Body aligned a skeleton, its metric scale converts
   reconstruction units to meters; failing that, the visible hand's length gives a
   coarser estimate. Both are labeled estimates and reported with their spread.
4. **Scene and plan** (`packages/robot/articulated.py`, `replicate.py`). A stand-in is
   generated with the demonstrated amount. Handles are bars the gripper straddles,
   so the part is pushed by a finger surface rather than dragged by friction; a
   carried box is held by friction alone, never attached. Each phase is a
   joint-space spline with a quintic time law at 30% of joint limits. Every tick is
   checked against the scene; colliding approaches are re-routed and unreachable
   placements fall through a short canonical list. With measured calibration the
   object is placed where the video had it, if the robot can reach it.
5. **Physics, evaluation, export, variations.** Success means the generated object
   ends in the demonstrated state after being let go (or still held, or pressed and
   released), with no checked violation. The object is then moved, rotated and
   resized (default 4 cases), and each is re-planned and re-simulated.

## What was verified

### Real footage, through the queued Docker stack

Nine Pexels stock clips and the repository's pouring clip: live Muse and SAM calls,
VGGT geometry on the local 4 GB GPU, queued Phase 3. Reports are in
`eval/reports/real-skill/` (superseded attempts in `first-attempt/`); outputs and a
`viewer.html` per run in `data/real-skill/`.

| Clip | Perception read it as | Inferred skill | Simulated result | Variations |
| --- | --- | --- | --- | --- |
| Closing a laptop (6771488) | "Close an open laptop on a desk" | Level hinge, close, 0.83 rad; radius 0.23 m from the video | Lid closed from 47° to shut | 4 of 4 |
| Opening a card-catalogue drawer (6550137) | "Open a card catalog drawer ..." | Slide, open; 0.25 m from the video | Drawer pulled 0.25 m | 4 of 4 |
| Man opening a drawer, full body (8987458) | "open cabinet drawer, adjust papers inside, then close drawer" | Slide, open (pull: reach cosine -0.96); 0.22 m from the video | Drawer pulled 0.22 m | 4 of 4 |
| Picking up a cup (7658235) | "Pick up cup from table, ..." | Carried object, still held | Box picked up, moved 0.29 m and held | 4 of 4 |
| Pouring clip, placing the glass (9.0-13.8 s) | "Pour water from glass into white bowl and stir contents" | Carried object, released | Box moved 0.07 m and set down | 4 of 4 |
| Pouring clip, the pour (1.0-7.0 s) | same | Carried object, still held | Box picked up, moved 0.15 m and held. **No pour**: tilting and liquid are not modeled | 4 of 4 |
| Lifting a gift-box lid, top-down (5900273) | "open gift box to reveal contents" | Level hinge, open, 2.57 rad limited to 1.92 | Lid opened 110°. **A poor match**: the real lid lifts off with two hands; it was replicated as a hinged lid by one | 4 of 4 |
| Opening a house door, first-person (4010079) | "Open the wooden panel door by operating the lever handle" | **Refused**: handheld moving camera; reconstructed hand positions jump between frames and only 4 contact samples exist | not run | - |
| Opening a locker by its knob, close-up (9145018) | "open wooden cabinet door by handle" | **Refused**: hand path too noisy to fit a hinge (the door swings in front of the hand; depth jumps frame to frame) | not run | - |
| Opening a laptop, close-up (7236875) | "open laptop lid and operate trackpad and keyboard" | **Refused**: the lid opens in 0.6 s and the hand leaves the frame, leaving 3 contact samples | not run | - |

Every completed run was graded Silver with no checked violation.

What these runs showed:

- **The first attempt at four of these clips failed** because the hand was never
  given an identity, so no hand geometry existed. The identity resolver was then
  extended (stitching a re-detected hand, image-side wording, hand proximity for
  look-alike objects) and a geometry bug was fixed (a stitched hand has two track
  rows per frame and was being discarded). Identities are now automatic in every
  clip except the close-up laptop opening, where both hands move alike; that one
  was reviewed on rendered frames.
- **Amounts are rough.** The laptop lid was measured as 47° where the video shows
  about 100°. Treat real-footage amounts as order-of-magnitude.
- **Sizes are coarse.** No run obtained the body-model scale (the body was out of
  frame or not aligned), so sizes come from the visible-hand estimate, with a
  spread of up to 48%.
- **The plan carries real weight.** Two drawer and lid directions, and several
  manipulation windows, came from the semantic plan because contact evidence was
  absent or geometry was inconclusive. In a top-down view the camera's "up" is not
  vertical; the plan's open/close now overrides it for lids.
- **A run that completes is not always a faithful one.** The pour became a carry and
  the lift-off lid became a hinge. Both say so in their review reasons, but the
  simulation still reports success for the task it generated.
- New clips made 3 or 4 hosted model calls each in perception and none afterwards;
  the pouring runs reused an earlier reviewed perception run. Reconstruction took 8 to
  35 minutes per interval.

### Synthetic demonstrations (Windows, Python 3.11, MuJoCo 3.3.7, CPU)

| Demonstration | Inferred | Simulated result (reached / goal) | Violations | Variations |
| --- | --- | --- | --- | --- |
| Open laptop lid (100°) | hinge, lid, open | 1.727 / 1.715 rad | none | 4 of 4 |
| Close laptop lid | hinge, lid, close | -0.001 / 0 rad | none | 4 of 4 |
| Pull drawer open | slide, drawer, open | 0.152 / 0.150 m | none | 4 of 4 |
| Push drawer shut | slide, drawer, close | 0.003 / 0 m | none | 4 of 4 |
| Open cabinet door | hinge, door, open | 1.116 / 1.134 rad | none | 4 of 4 |
| Carry a mug onto a stand | carried object, released | moved 0.156 m of 0.157 m | none | 4 of 4 |
| Pick up a cup and hold it | carried object, held | moved 0.129 m of 0.130 m | none | 4 of 4 |
| Press a button | press | pressed 16 mm (goal 12 mm), sprang back | none | 4 of 4 |
| Turn a knob | twist | 1.496 / 1.571 rad | none | 4 of 4 |

- The lid and carry runs passed the official LeRobot writer/reader round trip.
- Replaying the lid's exported actions through `PandaTaskEnv` reproduced the episode.
- A policy cloned from the drawer run's 276 transitions opened the drawer in closed-loop
  physics with no violation (`scripts.train_offline --hidden 256 --warmup-updates 8000
  --warmup-lr 0.001 --state-noise 0.5 --alpha 0.02 --updates 500`). The three
  evaluations share one start state, so this is one result, not evidence of generalization.
- Inference accuracy over 20 seeds per task: every joint type, object type and direction
  correct with positional noise up to 4% of the handle radius, and 355 of 360 correct at 8%.
  Hinge-angle error reaches about 0.5 rad at 4% noise.
- The browser UI was driven end to end with a headless Edge: mode selection, skill
  inference, submission, result panel, and playback of the replay video.
- 156 automated tests pass.

## What it does not establish

- **Real footage works on clear clips and is rough even then.** Seven of ten real
  intervals ran; three were refused for lack of usable hand geometry (fast motion,
  occlusion, a moving camera). Of the seven, two replicate a simpler task than the
  one filmed (a pour as a carry, a lift-off lid as a hinge). Measured amounts are
  order-of-magnitude: the laptop lid read 47° where the video shows about 100°.
  None of this has been compared against annotated ground truth.
- Clips that work best: a fixed camera, the hand and object in view throughout,
  a side-on view of the motion, and a motion lasting a second or more.
- The scene is a generated stand-in. Its placement is canonical unless a measured
  calibration is supplied. `task_scene_validated` stays false, so no run is Gold.
- Stand-ins are light (0.02–0.3 kg) with low joint friction because the pinned Franka
  hand model grips weakly. Forces on a real mechanism are not modeled.
- Twist angle, twist sense and press depth are never measured from the video.
- Execution is open loop per scene. Skill confidence is a heuristic.
- **No physical robot was available, so nothing was executed on hardware.**
  `scripts.export_robot_program` writes a controller-ready joint trajectory and gripper
  commands after a limit check, with an operator checklist; it is an input to a
  supervised first run, not a validation. `physical_robot_ready` stays false.

## Files

| Artifact | Content |
| --- | --- |
| `skill_model.json` | Kind, axis, displacement, direction and evidence, fits, phases, confidence |
| `replication_report.json` | Skill, generated object or carry task, scale used, placement, variations |
| `robot_trajectory.json` | Planned frames with `phase`, targets, joints, gripper, source/execution time |
| `simulation_report.json` | Simulated states, joint value or object displacement, violations, video codec |
| `simulation/simulation_replay.mp4` | H.264 when FFmpeg is available (browser playable), otherwise mp4v |
| `learning_bundle.zip` | All of the above plus LeRobot data and RL transitions, hashed |
| `robot_program.json` | Optional controller-ready export (`scripts.export_robot_program`) |

API: `config.mode = "skill"` on `POST /v1/videos/{id}/robotize`;
`GET .../robotize/proposal?mode=skill`; `POST .../robotize/check`;
`GET .../association-proposals`, `POST .../auto-associate`; results at
`/skill-model` and `/replication-report`.
