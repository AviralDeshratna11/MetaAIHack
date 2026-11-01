"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { SemanticPlan, TrackFrame, LayerOneHandoffManifest } from "../generated/contracts";
import ReconstructionPanel from "./reconstruction-panel";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:58000";
const colors = ["#ef9b55", "#74c8ba", "#b6a1dc", "#d5bf66", "#8eb6da"];
const stages = ["preprocessing", "semantic_parsing", "tracking"];
const phaseTwoStages = ["geometry", "interaction", "interaction_trajectory"];
const stageHints: Record<string, string> = {preprocessing: "Source & canonical timeline", semantic_parsing: "Muse semantic parser", tracking: "SAM identity-aware masks", geometry: "Shot-local cameras, hands & objects", interaction: "Proximity, motion & persistence", interaction_trajectory: "Object-relative poses & refined timing"};
const names: Record<string, string> = { preprocessing: "Normalize & inspect", semantic_parsing: "Understand actions", tracking: "Ground & track", geometry: "Reconstruct scene & hands", interaction: "Fuse contact evidence", interaction_trajectory: "Build interaction trajectory" };
type Job = {job_id: string; run_id: string; status: string; stage: string | null; inference_mode: string; pipeline?: string; source_job_id?: string | null; error?: {code: string; message: string}; stages?: {stage: string; status: string; attempt: number}[]};
type Video = {video_id: string; filename: string; status: string};
type Artifact = {name: string; uri: string; url: string; byte_count: number; sha256: string; inference_mode: string};
type RLE = {width: number; height: number; counts: number[]};
type Tracks = {tracks: TrackFrame[]; masks: Record<string, RLE>};

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(API + path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || data.detail?.[0]?.msg || `Request failed (${response.status})`);
  return data;
}

export default function Workspace() {
  const [videos, setVideos] = useState<Video[]>([]);
  const [selected, setSelected] = useState<Video | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [mode, setMode] = useState("connecting");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [plan, setPlan] = useState<SemanticPlan | null>(null);
  const [handoff, setHandoff] = useState<LayerOneHandoffManifest | null>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [media, setMedia] = useState("");
  const [dimensions, setDimensions] = useState({width: 640, height: 360, fps: 15});
  const [time, setTime] = useState(0);
  const [tracks, setTracks] = useState<Tracks>({tracks: [], masks: {}});
  const [projection, setProjection] = useState<{entity_id: string; frame_index: number; projected_centroid: number[] | null}[]>([]);
  const [showMasks, setShowMasks] = useState(true);
  const [hidden, setHidden] = useState<string[]>([]);
  const [events, setEvents] = useState<string[]>([]);
  const [subscriptionVersion, setSubscriptionVersion] = useState(0);
  const [panel, setPanel] = useState<"actions" | "artifacts">("actions");
  const [correctionEntity, setCorrectionEntity] = useState("");
  const [correctionKind, setCorrectionKind] = useState<"point" | "box">("point");
  const dragStart = useRef<[number, number] | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const generation = useRef(0);
  const trackCache = useRef(new Map<string, Tracks>());

  const refresh = useCallback(async () => {
    const [health, list] = await Promise.all([api<{inference_mode: string}>("/health/live"), api<{videos: Video[]}>("/v1/videos")]);
    setMode(health.inference_mode); setVideos(list.videos);
  }, []);
  useEffect(() => { refresh().catch(e => setError("Backend unavailable. Start Docker Compose, then reload. " + e.message)); }, [refresh]);

  const loadResults = useCallback(async (video: Video, run: Job) => {
    const suffix = `?run_id=${run.run_id}`;
    const [all, semantics, result] = await Promise.all([
      api<{artifacts: Artifact[]}>(`/v1/videos/${video.video_id}/artifacts${suffix}`),
      api<SemanticPlan>(`/v1/videos/${video.video_id}/actions${suffix}`),
      api<LayerOneHandoffManifest>(`/v1/videos/${video.video_id}/handoff${suffix}`),
    ]);
    setArtifacts(all.artifacts); setPlan(semantics); setHandoff(result);
    const normalized = all.artifacts.find(a => a.name === "video_720p_15fps.mp4");
    const manifest = all.artifacts.find(a => a.name === "manifest.json");
    if (normalized) setMedia(normalized.url);
    if (manifest) {
      const info = await fetch(manifest.url).then(r => r.json());
      setDimensions({width: info.width, height: info.height, fps: info.fps_num / info.fps_den});
    }
  }, []);

  const openVideo = useCallback(async (video: Video) => {
    generation.current++;
    setSelected(video); setPlan(null); setHandoff(null); setMedia(""); setArtifacts([]); setTracks({tracks: [], masks: {}}); setProjection([]);
    setTime(0); setEvents([]); setError(""); setHidden([]); setJob(null);
    const details = await api<{jobs: Job[]; source_url: string}>(`/v1/videos/${video.video_id}`);
    const run = details.jobs[0];
    if (details.source_url) setMedia(details.source_url);
    if (run) {
      setJob(run);
      if (["COMPLETED", "NEEDS_REVIEW"].includes(run.status)) await loadResults(video, run);
    }
  }, [loadResults]);

  useEffect(() => {
    if (!job || !selected || ["COMPLETED", "NEEDS_REVIEW", "FAILED", "CANCELLED"].includes(job.status)) return;
    const video = selected, current = generation.current;
    const source = new EventSource(`${API}/v1/jobs/${job.job_id}/events`);
    source.onmessage = event => {
      if (current !== generation.current) return;
      const item = JSON.parse(event.data);
      setEvents(old => [...old.slice(-5), item.detail.stage_completed ? `${names[item.detail.stage_completed]} completed` : item.status.replaceAll("_", " ")]);
      api<Job>(`/v1/jobs/${job.job_id}`).then(async run => {
        if (current !== generation.current) return;
        setJob(run);
        if (["COMPLETED", "NEEDS_REVIEW"].includes(run.status)) {
          source.close(); await loadResults(video, run);
        }
        if (["FAILED", "CANCELLED"].includes(run.status)) source.close();
      }).catch(e => setError(e.message));
    };
    return () => source.close();
    // Keep one connection per job; status updates must not reset the cursor.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.job_id, selected?.video_id, loadResults, subscriptionVersion]);

  const frame = Math.max(0, Math.min(Math.floor(time * dimensions.fps + .001), plan ? Math.round(plan.duration_s * dimensions.fps) - 1 : Infinity));
  const trackWindow = Math.floor(frame / dimensions.fps);
  useEffect(() => {
    if (!selected || !job || !handoff) return;
    const abort = new AbortController();
    const load = async (window: number) => {
      const key = `${job.run_id}/${window}`;
      const cached = trackCache.current.get(key);
      if (cached) return cached;
      const result = await api<Tracks>(`/v1/videos/${selected.video_id}/tracks?run_id=${job.run_id}&start_s=${window}&end_s=${window + .999999}&include_masks=true&limit=200`, {signal: abort.signal});
      trackCache.current.set(key, result);
      // Keep a bounded cache while allowing smooth playback over prefetched windows.
      if (trackCache.current.size > 8) trackCache.current.delete(trackCache.current.keys().next().value!);
      return result;
    };
    load(trackWindow).then(result => { setTracks(result); if (trackWindow + 1 < (plan?.duration_s || 0)) load(trackWindow + 1).catch(() => {}); })
      .catch(e => { if (e.name !== "AbortError") setError(e.message); });
    return () => abort.abort();
  }, [selected, job?.run_id, handoff, trackWindow, dimensions.fps, plan?.duration_s]);

  useEffect(() => {
    const canvas = canvasRef.current, element = videoRef.current;
    if (!canvas || !element || !media) return;
    let id = 0;
    const update = () => { setTime(element.currentTime); id = requestAnimationFrame(update); };
    id = requestAnimationFrame(update);
    return () => cancelAnimationFrame(id);
  }, [media]);

  useEffect(() => {
    const canvas = canvasRef.current, ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!showMasks) return;
    tracks.tracks.filter(t => t.observed && t.frame_index === frame && !hidden.includes(t.entity_id)).forEach(track => {
      const entityIndex = plan?.entities.findIndex(e => e.entity_id === track.entity_id) ?? 0;
      const color = colors[Math.max(0, entityIndex) % colors.length];
      const rle = track.mask_ref ? tracks.masks[track.mask_ref] : undefined;
      if (rle) {
        const overlay = document.createElement("canvas"); overlay.width = rle.width; overlay.height = rle.height;
        const context = overlay.getContext("2d")!;
        const image = context.createImageData(rle.width, rle.height);
        const rgb = [1, 3, 5].map(i => parseInt(color.slice(i, i + 2), 16));
        let offset = 0;
        rle.counts.forEach((count, index) => {
          if (index % 2) for (let pixel = offset; pixel < offset + count; pixel++) {
            image.data.set([...rgb, 80], pixel * 4);
          }
          offset += count;
        });
        context.putImageData(image, 0, 0); ctx.drawImage(overlay, 0, 0, canvas.width, canvas.height);
      }
      if (track.bbox_xyxy) {
        const [x1, y1, x2, y2] = track.bbox_xyxy;
        ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
        ctx.font = "12px monospace"; ctx.fillStyle = color;
        ctx.fillText(`${track.entity_id} · ${track.provider_track_id ?? "?"}`, x1, Math.max(14, y1 - 6));
      }
    });
    projection.filter(p => p.frame_index === frame && p.projected_centroid && !hidden.includes(p.entity_id)).forEach(p => {
      const [x, y] = p.projected_centroid!;
      ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(x-7, y); ctx.lineTo(x+7, y); ctx.moveTo(x, y-7); ctx.lineTo(x, y+7); ctx.stroke();
    });
  }, [tracks, frame, plan, showMasks, hidden, projection]);

  async function upload(file: File, synthetic = false) {
    setBusy("Checking & uploading video…"); setError("");
    try {
      const buffer = await file.arrayBuffer();
      const hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", buffer)), x => x.toString(16).padStart(2, "0")).join("");
      const created = await api<{video_id: string; upload_url: string; upload_headers: Record<string, string>}>("/v1/videos", {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({filename: file.name,
          byte_count: file.size, sha256: hash, provenance: {rights_status: synthetic ? "synthetic" : "user_supplied", uploader: "local-user"}})});
      const uploaded = await fetch(created.upload_url, {method: "PUT", headers: created.upload_headers, body: file});
      if (!uploaded.ok) throw new Error(`Object upload failed (${uploaded.status})`);
      await api(`/v1/videos/${created.video_id}/complete-upload`, {method: "POST"});
      const run = await api<Job>(`/v1/videos/${created.video_id}/process`, {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({idempotency_key: `upload-${created.video_id}`})});
      generation.current++; setSelected({video_id: created.video_id, filename: file.name, status: "UPLOADED"});
      setPlan(null); setHandoff(null); setArtifacts([]); setMedia(""); setTracks({tracks: [], masks: {}}); setTime(0); setJob(run); setEvents([]);
      await refresh();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(""); if (inputRef.current) inputRef.current.value = ""; }
  }

  async function demo() {
    setBusy("Generating synthetic fixture…"); setError("");
    try {
      const response = await fetch(API + "/v1/demo-source");
      if (!response.ok) throw new Error("Could not generate demo source");
      await upload(new File([await response.blob()], "synthetic-fixture.mp4", {type: "video/mp4"}), true);
    } catch (e) { setError((e as Error).message); setBusy(""); }
  }

  function seek(value: number) { if (videoRef.current) videoRef.current.currentTime = value; setTime(value); }
  async function jobAction(action: string) {
    if (!job) return;
    try { const result = await api<Job>(`/v1/jobs/${job.job_id}/${action}`, {method: "POST"}); setJob(result); if (action === "retry") setSubscriptionVersion(v => v + 1); }
    catch (e) { setError((e as Error).message); }
  }
  function canvasPoint(event: React.PointerEvent<HTMLCanvasElement>): [number, number] {
    const rect = event.currentTarget.getBoundingClientRect();
    return [(event.clientX - rect.left) * dimensions.width / rect.width, (event.clientY - rect.top) * dimensions.height / rect.height];
  }
  async function correct(event: React.PointerEvent<HTMLCanvasElement>) {
    if (!correctionEntity || !job || !selected) return;
    const point = canvasPoint(event), start = dragStart.current || point;
    const track = tracks.tracks.find(t => t.entity_id === correctionEntity);
    if (!track) return setError("No shot context at this frame; seek inside the processed clip.");
    setBusy("Applying correction in a new run…");
    try {
      const payload = {source_job_id: job.job_id, entity_id: correctionEntity, shot_id: track.shot_id,
        frame_index: frame, kind: correctionKind, ...(correctionKind === "point" ? {point} : {
          bbox_xyxy: [Math.min(start[0], point[0]), Math.min(start[1], point[1]), Math.max(start[0], point[0]), Math.max(start[1], point[1])]})};
      const run = await api<Job>(`/v1/videos/${selected.video_id}/corrections`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
      setCorrectionEntity(""); setHandoff(null); setJob(run); setEvents([]);
    } catch (e) { setError((e as Error).message); } finally { setBusy(""); }
  }

  const active = plan?.actions.filter(a => a.start_s <= time && a.end_s > time) || [];
  const terminal = !job || ["COMPLETED", "NEEDS_REVIEW", "FAILED", "CANCELLED"].includes(job.status);

  return <div className="workspace">
    <aside className="sidebar">
      <a className="brand" href="/"><span className="mark">v<span>2</span>r</span><span>Video2Robot<small>PERCEPTION WORKSPACE</small></span></a>
      <div className="nav-label">WORKSPACE <span>01</span></div>
      <div className="nav-active"><span>▧</span> Video understanding <span className="nav-dot" /></div>
      <div className="sidebar-section"><span>RECENT VIDEOS</span><span>{videos.length.toString().padStart(2, "0")}</span></div>
      <div className="video-list">{videos.map(video => <button className={selected?.video_id === video.video_id ? "video-link selected" : "video-link"} key={video.video_id} onClick={() => openVideo(video).catch(e => setError(e.message))}>
        <span className="file-icon">▷</span><span>{video.filename}<small>{video.status.replaceAll("_", " ")}</small></span>
      </button>)}{!videos.length && <p className="muted empty-list">Your uploaded clips will appear here.</p>}</div>
      <div className="sidebar-bottom"><span className="status-dot" /> Local project<small>Perception 0.1 · interaction 0.2</small></div>
    </aside>

    <main>
      <header className="topbar"><div><span className="muted">Compiler</span><span className="slash">/</span>Video understanding</div><span className={`mode ${mode === "fixture" ? "fixture" : ""}`}><span />{mode === "fixture" ? "FIXTURE MODE" : mode.toUpperCase()}</span></header>
      <div className="page-heading"><div><div className="eyebrow">FROM VIDEO TO STRUCTURED EVIDENCE</div><h1>Understand. Track. Reconstruct.</h1><p>Inspect semantic plans, persistent tracks, relative 3D trajectories, and contact evidence.</p></div><button className="primary" onClick={() => inputRef.current?.click()} disabled={!!busy}>＋ Upload video</button></div>
      <input aria-label="Upload video file" ref={inputRef} type="file" accept="video/mp4,video/quicktime" hidden onChange={e => e.target.files?.[0] && upload(e.target.files[0])} />
      {mode === "fixture" && <div className="fixture-banner"><span className="badge-icon">◇</span><div><strong>Offline fixture workspace</strong><span>Synthetic outputs test the pipeline. They are not real model predictions or benchmark evidence.</span></div><button onClick={demo} disabled={!!busy}>Run synthetic demo <span>↗</span></button></div>}
      {error && <div role="alert" className="error">{error}<button aria-label="Dismiss error" onClick={() => setError("")}>×</button></div>}
      {busy && <div role="status" className="busy"><span className="spinner" />{busy}</div>}

      <div className="pipeline">{(job?.pipeline === "reconstruction" ? phaseTwoStages : stages).map((stage, i) => {
        const complete = job?.stages?.some(s => s.stage === stage && s.status === "COMPLETED") || (!!handoff);
        const running = job?.stage === stage && !terminal;
        return <div key={stage} className={`pipeline-stage ${complete ? "done" : running ? "running" : ""}`}><span className="step-number">{complete ? "✓" : `0${i + 1}`}</span><div>{names[stage]}<small>{complete ? "Artifacts available" : running ? "Processing" : stageHints[stage]}</small></div>{i < 2 && <span className="step-arrow">→</span>}</div>;
      })}</div>

      <div className="content-grid"><section className="viewer card">
        <div className="card-head"><div><span className="section-number">01</span> SOURCE & PERCEPTION</div><label className="toggle"><input type="checkbox" checked={showMasks} onChange={e => setShowMasks(e.target.checked)} /> Masks</label></div>
        <div className="video-surface" style={{aspectRatio: `${dimensions.width}/${dimensions.height}`}}>
          {media ? <><video ref={videoRef} src={media} controls playsInline onTimeUpdate={e => setTime(e.currentTarget.currentTime)} onEnded={() => setTime(0)} />
            <canvas ref={canvasRef} width={dimensions.width} height={dimensions.height} className={correctionEntity ? "overlay correcting" : "overlay"} onPointerDown={e => { dragStart.current = canvasPoint(e); e.currentTarget.setPointerCapture(e.pointerId); }} onPointerUp={correct} /></> :
            <div className="empty-view"><div className="frame-symbol">⌖</div><h2>{selected ? "Building your perception artifacts" : "Every trajectory starts with a video"}</h2><p>{selected ? "Stage updates and artifacts will appear automatically." : "Upload a tabletop manipulation clip to inspect what happened, where, and when."}</p>{!selected && <button onClick={() => inputRef.current?.click()}>Choose an MP4 <span>↑</span></button>}<small>10–120 seconds · mostly rigid objects · one dominant hand</small></div>}
          <span className="video-label">{handoff ? "NORMALIZED SOURCE" : "SOURCE VIDEO"}</span>
        </div>
        <div className="video-meta"><span>{selected?.filename || "No video selected"}</span><span className="mono">{time.toFixed(2)}s <span className="muted">/ {plan?.duration_s.toFixed(2) || "—"}s</span></span></div>
        <div className="timeline"><div className="timeline-header"><span>ACTION TIMELINE</span><span className="muted">Coarse semantic timing</span></div><div className="timeline-track">
          {plan?.actions.map((action, i) => <button title={`${action.primitive}: ${action.start_s.toFixed(2)}–${action.end_s.toFixed(2)}s`} key={action.action_id} className={active.includes(action) ? "segment active" : "segment"} style={{left: `${100 * action.start_s / plan.duration_s}%`, width: `${100 * (action.end_s - action.start_s) / plan.duration_s}%`, background: colors[i % colors.length]}} onClick={() => seek(action.start_s)}>{action.primitive.toLowerCase()}</button>)}
          {!plan && <span className="timeline-placeholder">Action intervals appear after semantic parsing</span>}
          {plan && <div className="playhead" style={{left: `${100 * Math.min(time, plan.duration_s) / plan.duration_s}%`}} />}
        </div><div className="time-ruler"><span>0:00</span><span>{plan ? `${plan.duration_s.toFixed(1)}s` : "—"}</span></div></div>
        <div className="entities"><div className="timeline-header"><span>TRACKED ENTITIES</span><span className="muted">Click to toggle</span></div><div className="entity-chips">{plan?.entities.map((entity, i) => <button key={entity.entity_id} className={`entity-chip ${hidden.includes(entity.entity_id) ? "hidden-entity" : ""}`} onClick={() => setHidden(old => old.includes(entity.entity_id) ? old.filter(x => x !== entity.entity_id) : [...old, entity.entity_id])}><span style={{background: colors[i % colors.length]}} />{entity.semantic_name}<code>{entity.entity_id}</code></button>)}{!plan && <span className="muted">Entity identities have not been inferred yet.</span>}</div>
          {tracks.tracks.some(t => !t.observed || t.identity_status !== "associated") && <p className="track-warning">Some observations are missing or identity is uncertain at this frame. Inspect the tracking report.</p>}
        </div>
      </section>

      <aside className="inspector card"><div className="card-head"><div><span className="section-number">02</span> INSPECT EVIDENCE</div><span className="tiny-dot" /></div>
        <div className="tabs"><button className={panel === "actions" ? "active" : ""} onClick={() => setPanel("actions")}>Action plan</button><button className={panel === "artifacts" ? "active" : ""} onClick={() => setPanel("artifacts")}>Artifacts <span>{artifacts.length}</span></button></div>
        {panel === "actions" ? <div className="action-panel">{plan ? <><div className="task-summary"><span className="eyebrow">TASK HYPOTHESIS</span><h2>{plan.task}</h2><span className="skill">{plan.canonical_skill}</span></div><div className="action-list">{plan.actions.map((action, i) => <button key={action.action_id} className={`action-row ${active.includes(action) ? "current" : ""}`} onClick={() => seek(action.start_s)}><span className="action-index">{(i + 1).toString().padStart(2, "0")}</span><span><strong>{action.primitive.toLowerCase()}</strong><small>{action.object || "unknown object"}{action.target ? ` → ${action.target}` : ""}</small></span><span className="action-time">{action.start_s.toFixed(1)}–{action.end_s.toFixed(1)}s</span></button>)}</div><p className="semantic-note">Contact requirements are semantic hypotheses. Physical contact and refined boundaries belong to the next layer.</p></> : <div className="empty-inspector"><span>⌘</span><h3>A plan you can inspect</h3><p>Task entities, canonical primitives, dependencies, and uncertain steps will appear here.</p></div>}</div> : <div className="artifact-list">{artifacts.map(artifact => <a key={artifact.uri} href={artifact.url} target="_blank" rel="noreferrer"><span>↧</span><div><strong>{artifact.name}</strong><small>{(artifact.byte_count / 1024).toFixed(1)} KB · {artifact.sha256.slice(0, 10)}</small></div><span>↗</span></a>)}{!artifacts.length && <p className="muted">No artifacts available for this run.</p>}</div>}
      </aside></div>

      <div className="bottom-grid"><section className="card status-card"><div className="card-head"><div><span className="section-number">03</span> RUN STATUS</div><span className={`status-pill ${job?.status === "FAILED" ? "failed" : ""}`}>{job?.status.replaceAll("_", " ") || "AWAITING VIDEO"}</span></div><div className="status-body"><div className="status-text"><strong>{job ? `${job.inference_mode === "fixture" ? "Synthetic" : "Live"} perception run` : "Ready for your first clip"}</strong><p>{job?.error ? `${job.error.code}: ${job.error.message}` : events.at(-1) || "The original video is preserved. Every stage produces versioned artifacts."}</p>{job && <code>{job.run_id}</code>}</div>{job?.status === "FAILED" && <button onClick={() => jobAction("retry")}>Retry failed stage</button>}{job && !terminal && <button onClick={() => jobAction("cancel")}>Cancel run</button>}</div></section>
      <section className="card handoff-card"><div className="card-head"><div><span className="section-number">04</span> GEOMETRY HANDOFF</div><span className="mono">v0.1.0</span></div><div className="handoff-body"><div className={`handoff-icon ${handoff?.ready_for_geometry ? "ready" : ""}`}>↗</div><div><strong>{handoff ? handoff.ready_for_geometry ? "Ready for reconstruction" : "Review required" : "A clear boundary to the next layer"}</strong><p>{handoff ? handoff.review_reasons[0] || "Validated 2D artifacts are available." : "Semantic plan + tracks + masks + source timeline."}</p><small>2D perception only · metric scale unvalidated</small></div></div></section></div>
      {selected && job && plan && <ReconstructionPanel videoId={selected.video_id} run={job} time={time} fps={dimensions.fps}
        onProjection={setProjection} onStarted={run => {setJob({...run, stage: null}); setHandoff(null); setEvents([]); setProjection([]);}} />}
      {handoff && plan && job?.pipeline !== "reconstruction" && <details className="corrections card"><summary>Correct an entity grounding <span>Creates a new run; preserves original output</span></summary><div className="correction-tools"><label>Entity<select value={correctionEntity} onChange={e => setCorrectionEntity(e.target.value)}><option value="">Choose entity</option>{plan.entities.map(e => <option key={e.entity_id} value={e.entity_id}>{e.semantic_name}</option>)}</select></label><label>Prompt<select value={correctionKind} onChange={e => setCorrectionKind(e.target.value as "point" | "box")}><option value="point">Positive point</option><option value="box">Bounding box</option></select></label><p>{mode === "fixture" ? "Fixture color masks do not respond to visual prompts. This tests correction lineage; live mode uses the SAM prompt." : "Pause the video, select an entity, then click or drag on the image."}</p></div></details>}
      <footer><span>VIDEO2ROBOT / FIRST LAYER</span><span>Semantics → persistent perception → reconstruction</span></footer>
    </main>
  </div>;
}
