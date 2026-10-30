# First-layer verification — 2026-10-30

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
