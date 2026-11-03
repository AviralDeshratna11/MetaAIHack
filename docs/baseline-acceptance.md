# Baseline verification: 2026-11-03

Software through Phase 3 has been implemented and exercised in separate live and
synthetic acceptance paths. **The complete real-video baseline has not passed.**
The live geometry runtime/checkpoints are now configured and tested. Identity
review remains unresolved, and the simulator scene does not validate physical task success.

## Latest geometry verification

Approved SAM 3D Body weights and official VGGT weights were downloaded and hash
verified. Both models executed on the local 4 GiB GPU through API, RQ and storage:
job `job_516f37c50dcf4eb2b803cb94a416b079`, run
`run_74e3d6a66320412aacae442400f22d5b`. Four sampled cameras and four raw body
hypotheses were produced; all 53 artifact hashes verified. Model runtime was
183.213 seconds with peak CUDA allocation 3,637,203,456 bytes. The final regression
suite passed 85 tests in the worker image.

This run remains `NEEDS_REVIEW`: zero associated hand-pose rows and two object-pose
rows resulted from unresolved source identities. Robotization readiness and metric
scale validity remain false. The missing-runtime blocker is resolved; end-to-end
baseline acceptance remains incomplete. See [runtime setup](geometry-runtime.md)
and `eval/reports/live-phase2-geometry.json`. Earlier evidence below remains historical;
`baseline-live.json` records the earlier unified attempt, not this later geometry run.

## Evidence produced in this session

| Check | Result |
| --- | --- |
| Fresh live Muse/SAM on real human video | Completed with review; no fixture substitution |
| Live model responses | One completed Muse request, four completed SAM requests; two connect failures recovered; two Files uploads |
| Semantic output | Pour from glass into white bowl and stir; five entities, four actions |
| Live media/tracking integrity | 343 canonical frames, 3,087 candidate/missing rows, 2,474 decoded mask references, 27 verified artifacts |
| Live processing duration | 604.188 seconds, including CPU mask decoding; not real time |
| Phase 1/2 fixture HTTP + queue + storage | Passed; 34 hashed artifacts, 16 sampled cameras, 180 ITR frames |
| Real Panda FK/IK | Passed reachable round-trip and unreachable-target rejection |
| Synthetic motion through actual MuJoCo | 32/32 valid commands, physics advanced and replay rendered; no checked joint-limit/collision violations |
| Diagnostic replay TCP error | Maximum approximately 4.98 mm; consistency metric, not human-motion accuracy |
| Official LeRobot 0.4.1/v3 round-trip | Passed all 32 rows, action values/order, timestamps, image decoding |
| Packaged Linux robot image | Built; headless rendering, physics checks and official dataset round-trip passed |
| Full backend suite in robot image | 83 passed, no skips |
| Native regression suite | 79 passed, four FFmpeg-dependent tests skipped; those ran in the robot image |
| Frontend and schemas | TypeScript, optimized build, JSON Schema and generated TypeScript freshness passed |
| Phase 3 HTTP + leased native worker + storage | Passed; 45 verified artifacts; review/idempotency/config/source gates exercised |
| Phase 3 through RQ and Linux robot worker | Passed; 45 verified artifacts, review/identity/source/export gates retained |
| Quality enforcement | Synthetic diagnostic and unknown-gripper API case correctly excluded from accepted training data |
| Ablations | Nine variants executed on frozen fixture artifacts; no additional model calls |
| Browser interaction | Not verified: browser host unavailable; native Windows URL detection stopped UI automation |

Reports: `eval/reports/baseline-phase1-live.json`, `phase2-reverification.json`,
`phase3-smoke.json`, `phase3-api-smoke.json`, `baseline-ablations.json`,
`runtime-preflight.json`, `runtime-worker-preflight.json`, `phase3-container-smoke.json`,
`phase3-queue-smoke.json`, and the unified `baseline-live.json`.

The new real run is `run_15df7936724445a88f030103a93a3611`, job
`job_922277ea40db42038ebf7a91ea08eae1`, video
`vid_689eeec47c9640bcb92d89fcb17406a4`. Source is the registered licensed Pexels
pouring/stirring clip, SHA-256
`c0e17bc6032da748510265ae402a6e70b0f49a3fac68e0c4b1becf23b5a2ff38`.
Muse request ID `4ab2db0d-b9ae-449d-9e49-439fff27b392` and SAM IDs are retained in
the report. Actual monetary cost is unknown; do not estimate it from zero SAM
token counts. Failed connect attempts are distinguished from completed inference.

## Remaining acceptance requirements

1. Runtime setup is complete for limited-memory real inference. Dense reconstruction
   on this GPU remains unverified; select a continuous task and obtain sufficient
   samples for downstream processing. Four-frame previews establish execution,
   not adequate trajectory coverage or model accuracy.
2. Review semantic-to-candidate identities and spoon discontinuities on real video.
   The live main masks can cover frames while semantic identity remains ambiguous.
   Hand/glass/bowl associated coverage is currently zero; spoon is 49.6%.
   Corrections must retain provenance and cannot be claimed autonomous.
3. Select a continuous single-arm task/interval. The current clip includes two
   hands, stirring and liquid behavior. Unknown primitives/contact remain review
   reasons. A simpler authorized rigid-object clip may be needed for task success.
4. Use workspace adaptation for exploratory ordinary footage, or supply measured
   scale/registration for physical metric claims. The user has no measured object
   dimensions; none have been fabricated.
5. Replace the simulator's assumed proxy scene with an evidence-backed task scene,
   implement/verify applicable intentional-contact and task-success checks, and
   resolve unknown gripper intervals before accepted export. Current proxy replay
   does not validate grasps, placement, support reconstruction or fluid transfer.
6. Complete the real-video lineage through geometry, robotization, simulation and
   official-reader export, then inspect the debugger in a working browser.

The optional robot Docker image/override was built and validated after the native
checks, including rendering and the official dataset reader. It is now the running
queue worker. Its dataset Python is separate from the backend, so the worker's
outer-environment inventory does not list Torch/LeRobot even though its dataset
interpreter has them and the round-trip executed successfully.
No cloud compute was purchased, no model checkpoint or dataset was published,
and no robot hardware was commanded.

An additional licensed Pexels cup-manipulation source (7658235, Cup of Couple) was
downloaded as a candidate. FFprobe measured 9.92 seconds, below the configured
ten-second minimum. It was excluded rather than padded or counted as an accepted
case; no inference was submitted for it. `additional-source.json` records its
source/license/checksum. The main real acceptance source remains the pouring clip.

## Reproduce and continue

See `docs/phase-three.md` for dependency installation, assets, runtime configuration,
API request format and quality semantics. The task runner now exposes
`robot-assets`, `phase3-smoke`, `ablations`, and `baseline-live`.

```powershell
# Current fresh Phase 1 report is reusable; no new inference is submitted here.
.\.venv\Scripts\python.exe -m scripts.runtime_preflight
.\.venv\Scripts\python.exe -m scripts.baseline_acceptance --low-vram --robot-config configs/robotization-example.json

# Explicitly request fresh paid perception only when needed:
# python -m scripts.baseline_acceptance --run-perception --idempotency-key NEW_KEY --robot-config YOUR_CONFIG.json
```

The baseline command must still exit nonzero when source/quality requirements fail.
The historical unified attempt stopped at missing geometry configuration; use the
later geometry report for current runtime evidence. Independent fixture/simulator/export successes are included as
separate evidence, never as substitutes for a shared real-video lineage. Quality
thresholds were not loosened to turn an unsuccessful result into an accepted one.
