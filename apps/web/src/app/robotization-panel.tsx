"use client";
import {useEffect, useRef, useState} from "react";
import type {RobotTrajectory, QualityReport, SemanticPlan} from "../generated/contracts";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:58000";
type Run = {job_id: string; run_id: string; status: string; pipeline?: string; source_job_id?: string | null; inference_mode: string};
type Artifact = {name: string; url: string};
async function read<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(API+path, init); const data = await response.json();
  if (!response.ok) throw new Error(data.message || "Robotization request failed");
  return data;
}

export default function RobotizationPanel({videoId, run, time, plan, onSeek, onStarted}: {
  videoId: string; run: Run; time: number; plan: SemanticPlan | null; onSeek: (time: number) => void; onStarted: (run: Run) => void;
}) {
  const [config, setConfig] = useState(() => JSON.stringify({initial_gripper: "unknown", calibration: {mode: "workspace_adaptation", evidence: "Automatic robot workspace adaptation; no measured dimensions"}}, null, 2));
  const [hand, setHand] = useState(""); const [object, setObject] = useState("");
  const [shot, setShot] = useState("shot_000"); const [start, setStart] = useState(0); const [end, setEnd] = useState(5);
  useEffect(() => {
    setHand(plan?.entities.find(e => e.role === "actor")?.entity_id || "");
    setObject(plan?.entities.find(e => e.role === "manipulated_object")?.entity_id || "");
  }, [plan]);
  const [allowReview, setAllowReview] = useState(false);
  const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const [trajectory, setTrajectory] = useState<RobotTrajectory | null>(null);
  const [quality, setQuality] = useState<QualityReport | null>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const replay = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    setTrajectory(null); setQuality(null); setArtifacts([]); setError("");
    if (run.pipeline !== "robotization" || !["COMPLETED", "NEEDS_REVIEW"].includes(run.status)) return;
    const abort = new AbortController(); const suffix = `?run_id=${run.run_id}`;
    Promise.all([
      read<RobotTrajectory>(`/v1/videos/${videoId}/robot-trajectory${suffix}`, {signal: abort.signal}),
      read<QualityReport>(`/v1/videos/${videoId}/robot-quality${suffix}`, {signal: abort.signal}),
      read<{artifacts: Artifact[]}>(`/v1/videos/${videoId}/artifacts${suffix}`, {signal: abort.signal}),
    ]).then(([t,q,a]) => {setTrajectory(t); setQuality(q); setArtifacts(a.artifacts);})
      .catch(e => {if (e.name !== "AbortError") setError(e.message);});
    return () => abort.abort();
  }, [videoId, run.run_id, run.pipeline, run.status]);
  const frame = trajectory?.frames.length ? trajectory.frames.reduce((a,b) => Math.abs(a.source_time_s-time) <= Math.abs(b.source_time_s-time) ? a : b) : undefined;
  useEffect(() => {
    if (replay.current && frame && replay.current.paused && Math.abs(replay.current.currentTime-frame.execution_time_s) > .08) replay.current.currentTime = frame.execution_time_s;
  }, [frame]);
  async function submitRobotization() {
    setBusy(true); setError("");
    try {
      const payload = {source_job_id: run.pipeline === "robotization" ? run.source_job_id : run.job_id,
        idempotency_key: crypto.randomUUID(), allow_review_source: allowReview,
        config: {...JSON.parse(config), hand_id: hand, object_id: object, shot_id: shot, start_s: start, end_s: end}};
      const check = await read<{ready_for_ik_attempt: boolean; paired_samples: number; reasons: string[]}>(`/v1/videos/${videoId}/robotize/check`, {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
      if (!check.ready_for_ik_attempt) throw new Error(`${check.paired_samples} paired hand/object samples. ${check.reasons.join(". ")}. Correct identities or reconstruct a continuous interval before submitting.`);
      const result = await read<Run>(`/v1/videos/${videoId}/robotize`, {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)});
      onStarted(result);
    } catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  if (!["reconstruction", "robotization"].includes(run.pipeline || "")) return null;
  const media = artifacts.find(a => a.name === "simulation/simulation_replay.mp4");
  const bundle = artifacts.find(a => a.name === "learning_bundle.zip");
  return <section className="card reconstruction-panel" aria-label="Phase 3 robotization">
    <div className="card-head"><span>06 / FRANKA · IK · SIMULATION · LEROBOT</span><span>v0.3.0</span></div>
    <div className="reconstruction-tools"><div><h2>Compile a robot demonstration</h2><p>Workspace adaptation works without measured dimensions. It changes task scale and does not establish metric reconstruction.</p></div>
      <button className="primary" disabled={busy || !hand || !object || !["COMPLETED", "NEEDS_REVIEW"].includes(run.status)} onClick={submitRobotization}>{busy ? "Submitting…" : "Run phase 3"}</button></div>
    <div className="reconstruction-options">
      <label>Manipulating hand<select value={hand} onChange={e => setHand(e.target.value)}><option value="">Choose hand</option>{plan?.entities.filter(e => e.role === "actor").map(e => <option key={e.entity_id} value={e.entity_id}>{e.semantic_name}</option>)}</select></label>
      <label>Object<select value={object} onChange={e => setObject(e.target.value)}><option value="">Choose object</option>{plan?.entities.filter(e => e.role !== "actor").map(e => <option key={e.entity_id} value={e.entity_id}>{e.semantic_name}</option>)}</select></label>
      <label>Shot<input value={shot} onChange={e => setShot(e.target.value)} /></label>
      <label>Start (source seconds)<input type="number" min={0} step={.1} value={start} onChange={e => setStart(Number(e.target.value))} /></label>
      <label>End (source seconds)<input type="number" min={0} step={.1} value={end} onChange={e => setEnd(Number(e.target.value))} /></label>
    </div>
    <details><summary>Task interval, calibration and robot configuration</summary>
      <p>Choose entity and shot IDs from the reconstruction. Initial gripper state is an explicit assumption.</p>
      <label>Configuration<textarea aria-label="Robotization configuration JSON" rows={12} style={{width: "100%", fontFamily: "monospace"}} value={config} onChange={e => setConfig(e.target.value)} /></label>
      <label><input type="checkbox" checked={allowReview} onChange={e => setAllowReview(e.target.checked)} /> Explore unresolved source; retain all review reasons</label>
    </details>
    {error && <p role="alert" className="reconstruction-error">{error}</p>}
    {quality && <div><h3>{quality.classification} / {quality.accepted_training_subset ? "Accepted subset" : "Diagnostic output"}</h3>
      <ul>{quality.reasons.map(r => <li key={r}>{r.replaceAll("_", " ")}</li>)}</ul><p>Physical readiness remains unverified. Simulation uses an assumed proxy scene.</p></div>}
    {bundle && <div><a className="primary" href={bundle.url} download>Download robot learning bundle</a><p>Includes LeRobot data, RL transitions when an explicit task is configured, checksums and quality reasons. Read rl_report.json before training; reviewed data requires an explicit training override.</p></div>}
    {trajectory && <><p>{String(trajectory.adaptation.mode)} · {trajectory.frames.length} retimed commands · {trajectory.inference_mode}</p>
      <input aria-label="Robot execution timeline" type="range" min={0} max={Math.max(0,trajectory.frames.length-1)} step={1}
        value={frame ? trajectory.frames.indexOf(frame) : 0} onChange={e => onSeek(trajectory.frames[Number(e.target.value)].source_time_s)} style={{width:"100%"}} />
      {frame && <><p>Source {frame.source_time_s.toFixed(2)}s → robot {frame.execution_time_s.toFixed(2)}s · TCP error {(frame.position_error_m*1000).toFixed(1)} mm · gripper {frame.gripper_state}</p>
        <p>Target [{frame.target_position_m.map(n => n.toFixed(3)).join(", ")}] · achieved [{frame.achieved_position_m.map(n => n.toFixed(3)).join(", ")}]</p>
        <p>Joints (rad): {frame.joints_rad.map(n => n.toFixed(3)).join(" / ")}</p><p role="status">{frame.reasons.join(" · ") || "Kinematic frame checks passed"}</p></>}
      {media && <video ref={replay} src={media.url} controls style={{width:"100%", maxWidth:640}} aria-label="Physics replay"
        onTimeUpdate={() => {if (replay.current && !replay.current.paused && trajectory.frames.length) {const t=replay.current.currentTime; const f=trajectory.frames.reduce((a,b) => Math.abs(a.execution_time_s-t)<=Math.abs(b.execution_time_s-t)?a:b); onSeek(f.source_time_s);}}} />}
      <div className="artifact-list">{artifacts.filter(a => a.name.startsWith("export/") || a.name.startsWith("rl/") || ["quality_report.json", "simulation_report.json", "phase3_handoff.json", "learning_manifest.json"].includes(a.name)).map(a => <a key={a.name} href={a.url} target="_blank" rel="noreferrer">{a.name}</a>)}</div>
    </>}
  </section>;
}
