# Blueprint completion audit

The supplied 83-page blueprint is a design reference. Its priority matrix separates
P0/P1 baseline features from P2/P3 research extensions. The user now requests a usable
robot-learning output, so completion requires model evidence, valid trajectories,
task-aware simulation, explicit training eligibility and reproducible tests.

## Audit at the start of this implementation

| Area | Existing evidence | Gap to resolve |
| --- | --- | --- |
| Muse and SAM | Actual hosted inference and stored outputs | Semantic candidate identities unresolved in pouring source |
| VGGT and SAM 3D Body | Actual local inference on four frames | Sparse sampling cannot supply continuous manipulation trajectories |
| ITR novelty | Versioned robot-agnostic relative motion/contact/provenance | Broader interval and uncertainty diagnostics needed |
| Semantic/physical fusion novelty | Contact candidates refine grasp/release boundaries | Independent accuracy remains unannotated |
| Self-validation novelty | Projection, IK, physics, export and tier gates | Task scene and success checks absent |
| Compile once, robotize many | ITR separate from Franka adapter | Second embodiment not yet implemented |
| LeRobot | Official 0.4.1 reader round-trip | Current real-video source cannot pass valid-action gates |
| RL use | Demonstration actions only | Need explicit transitions, reward definitions, terminal/time-limit semantics and runnable environment |
| RLDS / RLBench / SAM 3D Objects / DINO re-ID | Not implemented | P2 extensions; report explicitly rather than claim completion |
| Bimanual / dexterous / policy training | Not implemented | Research extensions, not implied by successful dataset formatting |

No training data is accepted solely because it has valid file structure. Physical
scale, source identity, simulated success and source-to-robot adaptation are separate
facts. A simulated task may be trainable while its human-video provenance remains
review-gated. Generated simulation demonstrations must retain that distinction.

## Implemented and executed during this update

- Reviewed stored-mask association without hosted calls; unique visual-anchor
  selection and explicit re-verification of a segment after a missing observation.
- Bounded four-frame GPU windows with shared-image Sim(3) alignment checks and
  explicit interval selection. Actual seven-frame VGGT/body execution passed.
- Reach/pick-place task definitions, causal next-tick action alignment, explicit
  slower retiming/final hold, and task-aware actual MuJoCo replay.
- Official LeRobot state/action round-trip checks, typed offline RL transitions,
  hash-verified downloadable bundles and full source/correction/model provenance.
- Gymnasium environment checker, offline TD3+BC learner, saved-policy reload and
  fixed-state evaluation. A separate PPO entry point exists; PPO learning is not
  part of the acceptance claim.
- A source-specific endpoint adaptation passed physics, export and RL round-trip
  as Silver. Its learned endpoint policy passed three identical-initial-state
  evaluations without checked violations. This does not validate the source task.
- Nine ablations ran on frozen actual-model source artifacts. Accuracy remains
  unevaluated without independent annotations.

The user-requested complete project is **not fully accepted**: full source stirring/
pouring, validated grasp/support/scale, a learned pick-place task, second embodiment,
SAM 3D Objects, DINO re-ID, RLDS/RLBench, bimanual and dexterous paths remain unverified
or unimplemented. These must not be hidden behind a successful endpoint example.
See [robot-learning guide](robot-learning.md) and the acceptance report.

## Submission functionality update

The earlier gap inventory above is historical. A second adapter (official FR3 arm
with explicitly composed Panda hand) now passed actual FK/IK, physics, rendering,
LeRobot and RL-transition checks. Official TFDS/RLDS export now passed a complete
reader round-trip on video-derived transitions. Measured correspondence fitting,
advisory interval/task selection and a downloadable dataset catalog are integrated
in the API and UI. See [submission guide](SUBMISSION.md) for reproduction and
remaining research extensions; these changes do not validate the full source task.
