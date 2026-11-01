# Video2Robot — perception and interaction compiler

**Phase 2 is available:** hand/scene 3D, object-relative trajectories, contact
evidence and a versioned interaction trajectory. After a perception run finishes,
click **Run phase 2** in the inspection workspace. The fixture path runs on CPU;
the live path uses separately configured VGGT and optional SAM 3D Body weights.
See [phase 2 architecture and setup](docs/phase-two.md) and run
`python -m scripts.smoke_reconstruction` for the complete offline acceptance flow.

Upload short manipulation footage, normalize its timeline, parse semantic actions
with Muse and ground/track entities with SAM. Inspect the source, action intervals,
masks, identities and provenance, then run the reconstruction layer for relative
geometry and interaction hypotheses. Neither layer generates robot actions or
physically validates data.

The default **fixture mode** is entirely offline with respect to Meta. It uses a
generated shape video, fixed synthetic semantics and deterministic fixture-color
masks. It exercises the real database, queue, object store and FFmpeg. It is not a
claim about model performance. No API key or hackathon credit is needed yet.

## Start locally on Windows

Requirements: Docker Desktop running with Linux containers, Python 3.11+, Node
22.9+ (Node 24 tested), and npm. Docker includes FFmpeg/ffprobe, so native FFmpeg is
not required for the normal startup path. Run from this directory:

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
npm.cmd ci
docker compose up --build -d
npm.cmd run dev
```

Open **http://127.0.0.1:53000**. Choose **Run synthetic demo** for the complete fixture
flow. The first build compiles pinned MinIO upstream source because its public images
have been withdrawn; subsequent builds use Docker's cache. Containers mount the
workspace for local development. API code changes require `docker compose restart
api worker dispatcher`. Infrastructure uses separate loopback ports to coexist with
other local projects:

| Service | Address |
| --- | --- |
| Inspection UI | http://127.0.0.1:53000 |
| FastAPI / OpenAPI | http://localhost:58000/docs |
| PostgreSQL | localhost:55432 |
| Redis | localhost:56379 |
| S3 API | http://localhost:59000 |
| MinIO console | http://localhost:59001 |

This is a single-project local service without user authentication. Keep ports on
loopback. Example MinIO/database credentials are for this local environment only.
Uploaded media and generated arrays are stored outside Git in Docker volumes.

## Architecture and contracts

Read [the architecture](docs/architecture.md), [provider contract](docs/provider-contract.md),
the [verification results](docs/verification.md), and [golden-video instructions](docs/golden-videos.md). The canonical models live in
`packages/schemas/models.py`; JSON Schema and generated TypeScript are derived from
them. Every run records configuration/code hashes, model names, raw outputs and
artifact references. Stages use PostgreSQL leases, a transactional dispatch outbox,
Redis/RQ execution, immutable S3 objects and reconnectable persisted SSE events.

```text
apps/api           FastAPI, metadata, orchestration, Alembic
apps/web           Next.js inspection workspace
workers            preprocessing -> semantics -> perception
packages/schemas   Pydantic -> JSON Schema -> TypeScript
packages/meta_client live and fixture provider implementations
packages/video     FFmpeg, source PTS mapping, masks, shot detection
eval               independent human annotation and evaluation tools
```

Stage results include `manifest.json`, `frame_map.parquet`, `shots.json`, keyframes,
`semantic_plan.json`, `action_graph.json`, `tracks.parquet`, compressed RLE mask
bundles, `tracking_report.json`, and `handoff_manifest.json`. Missing observations
and uncertain associations stay explicit. A fixture run ends in `NEEDS_REVIEW` and
never claims `ready_for_geometry=true`. Hard cuts produce shot-local tracklets.

## Checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.export_schemas --check
npm.cmd run schemas:check
npm.cmd run typecheck
npm.cmd run build
docker compose run --rm api python -m pytest -q tests/test_media.py
.\.venv\Scripts\python.exe -m scripts.smoke
```

The smoke script requires the running Compose stack. It obtains real generated
video from the API, performs a conditional presigned upload, validates the checksum,
submits duplicate idempotency keys, waits for the RQ worker, decodes masks, validates
artifact hashes and reads the persisted event stream. It refuses to run in live
mode, so it cannot consume Meta credits. Its report is `eval/reports/offline-smoke.json`.
Native media tests skip when FFmpeg is absent; the container command runs them.

To regenerate types after changing contracts:

```powershell
.\.venv\Scripts\python.exe -m scripts.export_schemas
npm.cmd run schemas
```

`python -m scripts.tasks` provides matching `up`, `down`, `api`, `worker`, `dispatch`,
`web`, `test`, `media-tests`, `smoke`, `schemas`, `check` and `golden` task names.
Use the Linux Docker RQ worker on Windows (RQ's default worker forks).

## Later live phase — credits are not needed for architecture

Wait until the offline flow passes and real golden clips have been recorded. At
that point, enter `MODEL_API_KEY` in local `.env`, never in chat or browser code.
Run `python -m scripts.capabilities` to check model listing without inference.
Confirm whether the account accepts `sam-3.1` or the blueprint's `sam-3-1` spelling.
Set `INFERENCE_MODE=live`, then recreate API, worker and dispatcher with `docker
compose up -d --force-recreate api worker dispatcher`. One 20–30 second real golden
clip is the first bounded live test; the default budget is 16 requests including
uploads/retries. Usage is recorded, while cost is null until known. Do not run a
benchmark batch before the first live test is inspected.

A real pouring/stirring clip is registered and a live Muse/SAM test completed with
association review required; see `docs/verification.md`. Six other sources remain
`missing_source`. No annotated real benchmark metrics are claimed. Optional DINO
re-identification, local GPU SAM segmentation, robotization and dataset export
remain outside this implementation. Geometry, contact hypotheses and ITR are
implemented in [phase 2](docs/phase-two.md), with GPU model execution awaiting
runtime/checkpoint configuration and real-video acceptance.

## Stop

```powershell
docker compose down
```

Stop the UI with Ctrl+C. Volumes remain so jobs and artifacts can be inspected later.
