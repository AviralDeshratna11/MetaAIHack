# Perception and interaction verification - 2026-11-01

## Real-video live test: completed with review required

Fetched Pexels video 6901293 (Mikhail Nilov), a 22.88-second, 1920x1080/25fps
human pouring/stirring clip. The Pexels source/license URLs and SHA-256 are recorded
in the golden manifest. The clip passed real FFmpeg decoding, normalized to
343 frames at 1280x720/15fps in one shot, and passed public API upload completion
with checksum/media verification. It is uploaded as
`vid_0e0d03d1a36d4484a43af4c55dcce3c5`.

Account capability checking listed both configured models. A real live run completed
as `NEEDS_REVIEW`, using Muse Spark 1.3 and SAM 3.1. No fixtures were used for the
real video. Credentials remain only in the ignored local `.env`; services are now
in live mode. GPU reconstruction still requires its separate runtime/checkpoints.

| Live check | Result |
| --- | --- |
| Semantic plan | Valid: pour water from glass into bowl, then stir; two hand actors and three objects; six action segments |
| Hosted model calls in completed run | One Muse request and four SAM requests; two Files uploads |
| Muse latency | 42.940 seconds |
| SAM latencies | 17.219, 15.749, 16.717 and 15.463 seconds; 343 processed frames reported per request |
| Artifacts | 27 downloaded and SHA-256 verified |
| Tracks and masks | 3,087 candidate/missing rows validated; 2,474 mask references decoded |
| Processing duration | 582.063 seconds; CPU mask decoding dominates beyond hosted request time |
| Readiness | `ready_for_geometry=false`; associations and continuity require review |
| Quantitative accuracy | Not evaluated: no independent human mask/action/identity annotations |
| Regression suite after live fix | 76 tests passed in Docker |

Completed job: `job_fe7954f243854e62b4ade49c16fab484`.
Completed run: `run_5f85134e8d5a41afb8e03dee1e0ac277`.
Evidence: `eval/reports/live-smoke.json`; earlier stopped attempt:
`eval/reports/live-smoke-first-attempt.json`.

The initial live Muse output used a whole-person actor. It was stopped after the
first SAM response, retaining raw results. The prompt and validator now require
visible hand actors or an explicitly unknown/null actor. The revised live pass
returned `HAND_A`, `HAND_B`, `GLASS`, `BOWL`, and `SPOON`. Across both attempts there
were seven inference requests and four Files uploads, within the 16-request test
budget. No cost estimate is asserted; provider usage/request IDs are retained.

Spot inspection at 0, 5, 10, 15 and 20 seconds showed two hand masks following the
visible hands. Glass, bowl and spoon masks at 10 seconds also align qualitatively
with the visible objects. Inspection images are in `data/live-tests/` and are not
independent ground-truth annotations.

The generic hand concept returns both hands; the glass and bowl concepts also
produce secondary candidates in some frames. The current conservative association
policy leaves these semantic identities ambiguous, despite full observed coverage
of their main candidate tracks. Spoon masks are present in 341/343 frames, but two
gaps split its identity, leaving only 49.6% associated coverage. Other review reasons
include area/motion anomalies, coarse timing and approximating stirring with the
existing primitive vocabulary. Automatic semantic/candidate disambiguation and
mask-decoder performance remain follow-up work. No physical/robot readiness claim
is made by this successful live infrastructure test.

## Phase 2 acceptance

Module B is implemented as a separate queued pipeline consuming immutable
layer-one outputs. It includes versioned contracts, scene/hand geometry adapters,
object-relative motion, independent contact fusion, candidate events, bounded
action refinement, typed ITR, diagnostic APIs and an inspection panel.

| Check | Result |
| --- | --- |
| Complete backend suite in Docker | 74 passed, including real FFmpeg and generated-video geometry/contact processing |
| Native CPU suite | 70 passed, four FFmpeg-dependent tests skipped; all four ran in Docker |
| Schema generation | JSON Schema and generated TypeScript freshness passed |
| Frontend | TypeScript checking and optimized production build passed |
| Full HTTP/queue/storage phase 2 smoke | Passed with fixture inference and real services |
| Output integrity | 34 artifacts downloaded and SHA-256 checked; typed ITR validated |
| Geometry sampling | 16 camera frames, 16 hand surface estimates, 32 object estimates; 180 canonical ITR frames with explicit missing geometry |
| Contact output | Zero positive contact frames on this generated shape clip; positive/persistent and unknown contact cases tested separately |
| Durability | Idempotent submission, config conflict rejection, inherited inputs, cached geometry/contact, run-specific ITR and immutable prior handoff passed |
| Phase 2 smoke duration | 9.891 seconds for reconstruction plus a second cache/lineage run, excluding source upload/perception |
| Real GPU inference | Not run: Torch, VGGT, SAM 3D Body and checkpoints are absent from the project runtime |
| UI visual verification | Blocked: browser host unavailable; native Windows automation stopped because the current browser URL could not be established reliably |

Evidence: `eval/reports/phase2-smoke.json`. This was generated video with synthetic
geometry, not a human reconstruction or an accuracy benchmark. No paid model calls
were made. The machine reports an RTX 3050 Ti with 4096 MiB; GPU performance and
model compatibility were not established. Browser visual QA remains outstanding.

The live VGGT and optional SAM 3D Body adapters use local configured checkpoints
and an isolated GPU Python process. They do not download weights or substitute
fixtures on failure. Current object geometry is a visible-surface centroid and PCA
orientation hypothesis, not a reconstructed object mesh. Hand centroids are labeled
separately from anatomical wrists. Contact/grasp/release and timing refinements are
explicit hypotheses; object support, metric scale and physical feasibility remain
unverified. See [phase 2 setup and limitations](phase-two.md).

## First-layer acceptance

The current review found and fixed failures that the earlier offline suite did not
exercise. The pipeline passes the checks below, but real Muse/SAM correctness and
golden-video accuracy remain unverified. It is not justified to call it perfect.

| Boundary | Current result |
| --- | --- |
| Backend suite in Docker | 59 passed, including real FFmpeg normalization and an actual generated video with missing object observations |
| JSON Schema / generated TypeScript | Both freshness checks passed |
| Frontend | TypeScript check and production build passed |
| Upload-to-handoff smoke | Passed against real PostgreSQL, Redis/RQ, MinIO and FFmpeg, using fixture inference |
| Smoke outputs | 19 hash-checked artifacts, 540 track rows, three synthetic entities; 21.844 seconds including correction checks |
| Golden assets | Manifest valid; all three real demonstrations and four challenges remain missing_source |
| Live credentials / inference | No key configured; zero paid calls made |
| Real-video model metrics | Not evaluated; no annotated real golden sources |

Machine-readable evidence from this review is
`eval/reports/offline-smoke-2026-11-01.json`. Services were started with Docker
Desktop and left running in fixture mode. The generated shape clip exercises
infrastructure, not human-video semantic or segmentation accuracy.

## Fixes and regression coverage from this review

- Missing observations crashed Parquet serialization with nullable fixed-size list
  columns. Coordinate columns now use typed variable-length lists; Pydantic still
  enforces coordinate lengths. Null boxes and centroids round-trip correctly.
- Plain-text SAM output was silently accepted as zero detections. It now fails
  parsing; genuinely empty segmentation output remains valid.
- Wire media dimensions were discarded by the parser and could be misinterpreted
  as normalized-video coordinates. Dimensions are now checked before parsing, and
  mask decode quotas are enforced before the official decoder allocates rasters.
- Empty masks incorrectly changed reappearance state. Only nonempty measured
  masks can start a reappearance tracklet. Any observation gap now starts an
  unverified continuation rather than assuming provider identity survived.
- High overall coverage could hide unresolved identities or area/motion anomalies.
  These now independently require review. Motion checks use measured centroids;
  area checks use foreground mask pixels rather than bounding-box area.
- Identical concept prompts on different semantic entities could claim the same
  candidate with certainty. Such associations now remain ambiguous until corrected.
- Decimal point/box coordinates were rejected by the integer-only official prompt
  builder. They are now converted explicitly; same-frame point/box prompts merge.
  New visual prompts invalidate prior ordinal associations and preserve anchors on
  other frames.
- A crash after writing the immutable handoff but before committing its DB record
  could make retries fail permanently. Handoff publication can now reuse verified
  identical bytes while rejecting content conflicts and preserving immutability.

The adapter request formats were compared with current official Muse video-input
and SAM segmentation documentation. Synthetic transport tests and public grammar
examples verify contracts; they do not prove account access or live model behavior.
The supplied blueprint's semantic-first flow is represented, with the documented
hosted compromise of one concept call per entity per shot rather than local joint
multiplex tracking. Automatic appearance-based identity recovery is not implemented.

First live acceptance still needs an authorized, annotated 20-30 second pouring
clip and a server-side Meta key. It must measure actual action labels/timing,
selected-frame mask IoU, visible identity correctness and occlusion recovery.
Browser visual behavior and production-scale load were not assessed in this review.

## Previous verification - 2026-10-30

The user story is: upload a short video, inspect a canonical source timeline,
receive a semantic plan and persistent 2D entity tracks, and obtain a versioned
handoff for later reconstruction.

## Completed checks

| Boundary | Result | Evidence |
| --- | --- | --- |
| Backend regression suite | Passed | 43 tests passed in the CPU container, including actual FFmpeg tests |
| Shared contracts | Passed | Pydantic JSON Schema and generated TypeScript freshness checks |
| Frontend compile | Passed | TypeScript check and optimized Next.js production build |
| UI HTTP response | Passed | HTTP 200 at `http://127.0.0.1:53000` with the Video2Robot title |
| Client-origin access to API | Passed | CORS preflight 200 for `http://127.0.0.1:53000` |
| Client-origin access to S3 | Passed | CORS preflight 204 for conditional PUT from the same origin |
| Upload through processing | Passed | Public HTTP API, real PostgreSQL, Redis/RQ, MinIO and FFmpeg |
| Duplicate submissions | Passed | Same video/idempotency key returns the same processing job |
| Artifact integrity | Passed | All 19 published artifacts downloaded and SHA-256 checked |
| Track and mask outputs | Passed | 540 rows across three fixture entities; mask references decoded |
| Persisted events | Passed | Terminal event stream returned sequence IDs and NEEDS_REVIEW |
| Corrections | Passed | New linked run; preprocessing/semantics reused; tracking invalidated |
| Source preservation | Passed | Original handoff unchanged after correction; uploaded source rejects overwrite |
| Cancellation | Passed | Public cancellation endpoint revokes execution and records CANCELLED |
| Handoff gate | Passed | Synthetic output remains NEEDS_REVIEW and ready_for_geometry=false |
| Real-model inference | Not run | No credentials supplied; zero paid model calls |
| Browser interaction/visual layout | Unverified | Browser automation host unavailable; native fallback could not establish URL confidently |
| Real golden-video evaluation | Not evaluated | Three real demonstrations and four challenge clips remain missing_source |

The final offline smoke report records a generated 12-second shape video, three
synthetic entities, seven fixed semantic actions, 540 track rows and 19 artifacts.
The measured smoke sequence, including correction checks, took 26.11 seconds.
This is infrastructure evidence, not a Muse/SAM accuracy or latency benchmark.
The detailed machine-readable report is `eval/reports/offline-smoke.json`.

## Fixes confirmed during integration

- MinIO is built from pinned official source because the previous published images
  could not be pulled. Its CORS is configured using its supported environment setting.
- Dedicated API/database/queue/storage ports coexist with other local projects.
- The inspection UI uses IPv4 address `127.0.0.1:53000` because `localhost:3000`
  resolved to an unrelated app on this machine. No other project's service was stopped.
- SAM box-local mask payloads are decoded with the official parser and expanded
  into normalized frame coordinates. A public wire-format example tests the conversion.
- The initial Alembic migration is frozen rather than importing mutable model metadata.
- Queued live jobs retain their submitted model identifiers. Code-version changes
  before execution require a new processing run instead of misleading provenance.

One upstream Starlette/AnyIO deprecation warning remains in the test-client path;
all tests pass. There are no claims of authentication, multi-tenant isolation,
physical contact measurement, 3D reconstruction or robot feasibility in this layer.

## Next inputs for live acceptance

Architecture and offline verification do not require the hackathon credits. The
next phase needs an authorized 20–30 second pouring video and a server-side Meta
API key entered in local `.env`. The owner should retain the key locally.
The first live run should confirm account access, exact SAM model identifier,
video input compatibility, semantic schema behavior, masks and identities before
running a larger batch. A model-list capability check makes no inference request.
