"use client";
import {useEffect, useMemo, useRef, useState} from "react";
import type {RobotTrajectory, QualityReport, SemanticPlan} from "../generated/contracts";
import CalibrationForm from "./calibration-form";

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
  const [config, setConfig] = useState(() => JSON.stringify({initial_gripper: "unknown",workspace_extent_m:.02,execution_speed_scale:.25,final_hold_s:.5, calibration: {mode: "workspace_adaptation", evidence: "Automatic robot workspace adaptation; no measured dimensions"}}, null, 2));
  const [robot,setRobot]=useState("panda");const [proposalNotes,setProposalNotes]=useState<string[]>([]);
  useEffect(()=>{setRobot("panda");setProposalNotes([]);setAllowReview(false);setConfig(JSON.stringify({initial_gripper:"unknown",workspace_extent_m:.02,execution_speed_scale:.25,final_hold_s:.5,calibration:{mode:"workspace_adaptation",evidence:"Automatic robot workspace adaptation; no measured dimensions"}},null,2));},[videoId]);
  const settings=useMemo(()=>{try{return JSON.parse(config);}catch{return null;}},[config]);
  function patchConfig(patch:Record<string,unknown>){if(!settings)return setError("Repair the advanced JSON first.");setConfig(JSON.stringify({...settings,...patch},null,2));}
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
    ]).then(([t,q,a]) => {setTrajectory(t); setQuality(q); setArtifacts(a.artifacts);
      setConfig(JSON.stringify(t.config,null,2));setRobot(t.config.robot_id||"panda");setHand(t.config.hand_id);setObject(t.config.object_id);setShot(t.config.shot_id);setStart(t.config.start_s??0);setEnd(t.config.end_s??5);})
      .catch(e => {if (e.name !== "AbortError") setError(e.message);});
    return () => abort.abort();
  }, [videoId, run.run_id, run.pipeline, run.status]);
  const frame = trajectory?.frames.length ? trajectory.frames.reduce((a,b) => Math.abs(a.source_time_s-time) <= Math.abs(b.source_time_s-time) ? a : b) : undefined;
  useEffect(() => {
    if (replay.current && frame && replay.current.paused && Math.abs(replay.current.currentTime-frame.execution_time_s) > .08) replay.current.currentTime = frame.execution_time_s;
  }, [frame]);
  async function suggestInterval(){
    setBusy(true);setError("");
    try{
      const source=run.pipeline==="robotization"?run.source_job_id:run.job_id;
      const result=await read<{available:boolean;config:RobotTrajectory["config"];reasons:string[]}>(`/v1/videos/${videoId}/robotize/proposal?source_job_id=${encodeURIComponent(source||"")}&robot_id=${robot}`);
      if(!result.available)throw new Error(result.reasons.join(". "));
      const cfg=result.config;setConfig(JSON.stringify(cfg,null,2));setHand(cfg.hand_id);setObject(cfg.object_id);setShot(cfg.shot_id);setStart(cfg.start_s??0);setEnd(cfg.end_s??5);setProposalNotes(result.reasons);
    }catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  async function submitRobotization() {
    setBusy(true); setError("");
    try {
      const payload = {source_job_id: run.pipeline === "robotization" ? run.source_job_id : run.job_id,
        idempotency_key: crypto.randomUUID(), allow_review_source: allowReview,
        config: {...JSON.parse(config), robot_id:robot, hand_id: hand, object_id: object, shot_id: shot, start_s: start, end_s: end}};
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
      <label>Robot<select value={robot} onChange={e=>setRobot(e.target.value)}><option value="panda">Franka Panda</option><option value="fr3">FR3 + Panda hand (simulated composition)</option></select></label>
      <label>Manipulating hand<select value={hand} onChange={e => setHand(e.target.value)}><option value="">Choose hand</option>{plan?.entities.filter(e => e.role === "actor").map(e => <option key={e.entity_id} value={e.entity_id}>{e.semantic_name}</option>)}</select></label>
      <label>Object<select value={object} onChange={e => setObject(e.target.value)}><option value="">Choose object</option>{plan?.entities.filter(e => e.role !== "actor").map(e => <option key={e.entity_id} value={e.entity_id}>{e.semantic_name}</option>)}</select></label>
      <label>Shot<input value={shot} onChange={e => setShot(e.target.value)} /></label>
      <label>Start (source seconds)<input type="number" min={0} step={.1} value={start} onChange={e => setStart(Number(e.target.value))} /></label>
      <label>End (source seconds)<input type="number" min={0} step={.1} value={end} onChange={e => setEnd(Number(e.target.value))} /></label>
    </div>
    <div className="reconstruction-options"><button disabled={busy||!plan?.duration_s} onClick={()=>{setStart(0);setEnd(plan?.duration_s||0);patchConfig({require_full_interval:true,episode_end:"trajectory_end",execution_speed_scale:1,final_hold_s:0});}}>Use whole clip interval ({plan?.duration_s.toFixed(2)||"—"}s)</button>
      <label><input type="checkbox" checked={settings?.require_full_interval===true} onChange={e=>patchConfig({require_full_interval:e.target.checked})}/> Require paired geometry through the requested interval</label>
      <label><input type="checkbox" checked={settings?.episode_end==="trajectory_end"} onChange={e=>patchConfig({episode_end:e.target.checked?"trajectory_end":"task_success"})}/> Retain the entire trajectory in RL data, including after endpoint success</label>
      <p>Full-clip mode requires continuous associated hand/object geometry. This single-arm compiler uses one selected object and configured orientation; changing objects, two-hand support and fluid transfer need additional validated task stages. Safe retiming can make execution longer than the source.</p>
    </div>
    <div className="reconstruction-options"><button disabled={busy} onClick={suggestInterval}>Suggest supported interval and endpoint task</button>
      <label>Execution speed scale<input type="number" min={.05} max={1} step={.05} value={settings?.execution_speed_scale??1} onChange={e=>patchConfig({execution_speed_scale:+e.target.value})}/></label>
      <label>Final hold (seconds)<input type="number" min={0} max={5} step={.1} value={settings?.final_hold_s??0} onChange={e=>patchConfig({final_hold_s:+e.target.value})}/></label>
      <label>Workspace radius (meters)<input type="number" min={.001} max={.4} step={.005} value={settings?.workspace_extent_m??.02} onChange={e=>patchConfig({workspace_extent_m:+e.target.value})}/></label>
      <label>Initial gripper<select value={settings?.initial_gripper??"unknown"} onChange={e=>patchConfig({initial_gripper:e.target.value})}><option value="unknown">Unknown — infer from evidence</option><option value="open">Open — explicit assumption</option><option value="closed">Closed — explicit assumption</option></select></label>
      <label><input type="checkbox" checked={settings?.export_rlds===true} onChange={e=>patchConfig({export_rlds:e.target.checked})}/> Include official TFDS/RLDS export (configured runtime required)</label>
    </div>
    {proposalNotes.length>0&&<p role="status">{proposalNotes.join(" ")}</p>}
    <p>Task reward: {settings?.task_scene?.task||"not configured; RL transitions will be blocked"}. Calibration: {settings?.calibration?.mode||"workspace_adaptation"}.</p>
    <CalibrationForm onApply={calibration=>patchConfig({calibration})}/>
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
      <p>Observed source coverage: {trajectory.frames[0]?.source_time_s.toFixed(2)}–{trajectory.frames.at(-1)?.source_time_s.toFixed(2)}s · robot execution {trajectory.frames.at(-1)?.execution_time_s.toFixed(2)}s. Coverage does not certify complete action replication.</p>
      <input aria-label="Robot execution timeline" type="range" min={0} max={Math.max(0,trajectory.frames.length-1)} step={1}
        value={frame ? trajectory.frames.indexOf(frame) : 0} onChange={e => onSeek(trajectory.frames[Number(e.target.value)].source_time_s)} style={{width:"100%"}} />
      {frame && <><p>Source {frame.source_time_s.toFixed(2)}s → robot {frame.execution_time_s.toFixed(2)}s · TCP error {(frame.position_error_m*1000).toFixed(1)} mm · gripper {frame.gripper_state}</p>
        <p>Target [{frame.target_position_m.map(n => n.toFixed(3)).join(", ")}] · achieved [{frame.achieved_position_m.map(n => n.toFixed(3)).join(", ")}]</p>
        <p>Joints (rad): {frame.joints_rad.map(n => n.toFixed(3)).join(" / ")}</p><p role="status">{frame.reasons.join(" · ") || "Kinematic frame checks passed"}</p></>}
      {media && <video ref={replay} src={media.url} controls style={{width:"100%", maxWidth:640}} aria-label="Physics replay"
        onTimeUpdate={() => {if (replay.current && !replay.current.paused && trajectory.frames.length) {const t=replay.current.currentTime; const f=trajectory.frames.reduce((a,b) => Math.abs(a.execution_time_s-t)<=Math.abs(b.execution_time_s-t)?a:b); onSeek(f.source_time_s);}}} />}
      <div className="artifact-list">{artifacts.filter(a => a.name.startsWith("export/") || a.name.startsWith("rl/") || a.name.startsWith("rlds/") || ["quality_report.json", "simulation_report.json", "phase3_handoff.json", "learning_manifest.json"].includes(a.name)).map(a => <a key={a.name} href={a.url} target="_blank" rel="noreferrer">{a.name}</a>)}</div>
    </>}
  </section>;
}
