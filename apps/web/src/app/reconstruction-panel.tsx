"use client";

import { useEffect, useMemo, useState } from "react";
import type { GeometryWindow, LayerTwoHandoff, ReconstructionReport, RefinedAction } from "../generated/contracts";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:58000";
const palette = ["#ef9b55", "#74c8ba", "#b6a1dc", "#d5bf66"];
type Run = {job_id: string; run_id: string; status: string; pipeline?: string; source_job_id?: string | null; inference_mode: string};

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(API + path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.message || "Reconstruction request failed");
  return body;
}

export default function ReconstructionPanel({videoId, run, time, fps, onStarted, onProjection}: {
  videoId: string; run: Run; time: number; fps: number; onStarted: (run: Run) => void;
  onProjection: (points: {entity_id: string; frame_index: number; projected_centroid: number[] | null}[]) => void;
}) {
  const [report, setReport] = useState<ReconstructionReport | null>(null);
  const [handoff, setHandoff] = useState<LayerTwoHandoff | null>(null);
  const [window, setWindow] = useState<GeometryWindow | null>(null);
  const [actions, setActions] = useState<RefinedAction[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [body, setBody] = useState(false);
  const [allowReview, setAllowReview] = useState(false);
  const [yaw, setYaw] = useState(25);
  const [pitch, setPitch] = useState(-15);
  const isPhaseTwo = run.pipeline === "reconstruction";
  const terminal = ["COMPLETED", "NEEDS_REVIEW", "FAILED", "CANCELLED"].includes(run.status);
  const frame = Math.floor(time*fps+.001);

  useEffect(() => {
    setReport(null); setWindow(null); setHandoff(null); setActions([]); setError(""); onProjection([]);
    if (!isPhaseTwo || !["COMPLETED", "NEEDS_REVIEW"].includes(run.status)) return;
    const abort = new AbortController();
    const query = `?run_id=${run.run_id}`;
    Promise.all([
      request<ReconstructionReport>(`/v1/videos/${videoId}/geometry-report${query}`, {signal: abort.signal}),
      request<LayerTwoHandoff>(`/v1/videos/${videoId}/phase2-handoff${query}`, {signal: abort.signal}),
      request<GeometryWindow>(`/v1/videos/${videoId}/geometry${query}&limit=2000`, {signal: abort.signal}),
      request<RefinedAction[]>(`/v1/videos/${videoId}/refined-actions${query}`, {signal: abort.signal}),
    ]).then(([quality, result, data, refined]) => {
      setReport(quality); setHandoff(result); setWindow(data); setActions(refined);
      onProjection([...(data.hands || []), ...(data.objects || [])].map(r => ({entity_id: r.entity_id,
        frame_index: r.frame_index, projected_centroid: r.projected_centroid ?? null})));
    }).catch(e => {if (e.name !== "AbortError") setError(e.message);});
    return () => abort.abort();
  }, [videoId, run.run_id, run.status, isPhaseTwo, onProjection]);

  const poses = useMemo(() => [...(window?.hands || []), ...(window?.objects || [])], [window]);
  const current = poses.filter(r => r.frame_index === frame);
  const shot = current[0]?.shot_id;
  const visible = poses.filter(r => r.pose && r.shot_id === shot);
  const names = [...new Set(visible.map(r => r.entity_id))];
  const points = visible.map(r => r.pose!.position_xyz);
  const center = [0, 1, 2].map(axis => points.length ? points.reduce((s, p) => s+p[axis], 0)/points.length : 0);
  const extent = Math.max(.05, ...points.flatMap(p => p.map((v, i) => Math.abs(v-center[i]))));
  function screen(position: number[]) {
    const [x, y, z] = position.map((v, i) => (v-center[i])/extent);
    const a = yaw*Math.PI/180, b = pitch*Math.PI/180;
    const rx = Math.cos(a)*x+Math.sin(a)*z, rz = -Math.sin(a)*x+Math.cos(a)*z;
    return [250+rx*145, 160+(Math.cos(b)*y-Math.sin(b)*rz)*115];
  }
  async function start() {
    setBusy(true); setError("");
    try {
      const result = await request<Run>(`/v1/videos/${videoId}/reconstruct`, {method: "POST",
        headers: {"Content-Type": "application/json"}, body: JSON.stringify({source_job_id: isPhaseTwo ? run.source_job_id : run.job_id,
          idempotency_key: crypto.randomUUID(), allow_review_source: allowReview,
          config: {backend: run.inference_mode === "fixture" ? "fixture" : "vggt", body_backend: body ? "sam3d" : "none"}})});
      onStarted(result);
    } catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  return <section className="card reconstruction-panel" aria-label="Phase 2 reconstruction">
    <div className="card-head"><div><span className="section-number">05</span> HAND / SCENE 3D · OBJECT TRAJECTORIES · CONTACT</div><span>v0.2.0</span></div>
    <div className="reconstruction-tools"><div><h2>Reconstruct the interaction</h2><p>{run.inference_mode === "fixture"
      ? "Synthetic relative geometry tests the complete pipeline. It does not reconstruct a real human."
      : "VGGT scene geometry, optional SAM 3D Body, and independent contact evidence. A configured GPU runtime is required."}</p></div>
      <button className="primary" onClick={start} disabled={busy || !terminal}>{busy ? "Submitting…" : isPhaseTwo ? "Re-run phase 2" : "Run phase 2"}</button>
    </div>
    {run.inference_mode !== "fixture" && <div className="reconstruction-options">
      <label><input type="checkbox" checked={body} onChange={e => setBody(e.target.checked)} /> Use SAM 3D Body for anatomical wrists</label>
      <label><input type="checkbox" checked={allowReview} onChange={e => setAllowReview(e.target.checked)} /> Explore source with unresolved perception review reasons</label>
    </div>}
    {error && <p className="reconstruction-error" role="alert">{error}</p>}
    {isPhaseTwo && !terminal && <p className="reconstruction-pending" role="status">Reconstructing scene → aligning hands and objects → fusing contact → building interaction trajectory…</p>}
    {report && window && <>
      <div className="geometry-metrics"><span><strong>{report.camera_frames}</strong> sampled cameras</span><span><strong>{report.hand_pose_frames}</strong> hand estimates</span><span><strong>{report.object_pose_frames}</strong> object estimates</span><span><strong>{report.contact_events}</strong> contact events</span><span><strong>{report.reprojection_median_px?.toFixed(2) ?? "—"} px</strong> centroid consistency</span></div>
      <div className="reconstruction-grid"><div className="scene-view"><span className="eyebrow">{shot || "SEEK VIDEO"} / RELATIVE SCALE</span>
        <svg viewBox="0 0 500 320" role="img" aria-label="Interactive view of sampled 3D trajectories">
          <path d="M40 260H460 M250 35V290" stroke="#dbe4d9" strokeDasharray="4 6" fill="none" />
          {names.flatMap((entity, i) => [...new Set(visible.filter(r => r.entity_id === entity).map(r => r.track_id))].map(track => {
            const path = visible.filter(r => r.track_id === track).sort((a,b) => a.frame_index-b.frame_index);
            return <polyline key={track} points={path.map(r => screen(r.pose!.position_xyz).join(",")).join(" ")} fill="none" stroke={palette[i%palette.length]} strokeWidth="2" opacity=".65" />;
          }))}
          {current.filter(r => r.pose).map(row => {const [x,y] = screen(row.pose!.position_xyz); return <g key={row.track_id}><circle cx={x} cy={y} r="6" fill={palette[Math.max(0,names.indexOf(row.entity_id))%palette.length]} /><text x={x+10} y={y-8} fontSize="12">{row.entity_id}</text></g>;})}
          {!current.some(r => r.pose) && <text x="250" y="160" textAnchor="middle" fill="#7c847f" fontSize="12">No 3D sample at this frame</text>}
        </svg>
        <div className="scene-controls"><label>Rotate <input aria-label="Scene yaw" type="range" min="-180" max="180" value={yaw} onChange={e => setYaw(+e.target.value)} /></label><label>Tilt <input aria-label="Scene pitch" type="range" min="-80" max="80" value={pitch} onChange={e => setPitch(+e.target.value)} /></label></div>
        <small>Sampled position paths. Shot-local world; missing frames stay missing. Crosshairs on the video show projected 3D centroids.</small>
      </div><div className="contact-inspector"><span className="eyebrow">CONTACT EVIDENCE AT {time.toFixed(2)}s</span>
        {(window.contacts || []).filter(r => r.frame_index === frame).map(row => <div className="contact-row" key={`${row.hand_id}/${row.object_id}`}><strong>{row.hand_id} → {row.object_id}</strong><span className={`contact-state ${row.state.toLowerCase()}`}>{row.state.replaceAll("_", " ")}</span><small>2D {row.distance_2d_px?.toFixed(1) ?? "—"} px · 3D {row.distance_3d_relative?.toFixed(4) ?? "—"} relative · score {row.probability?.toFixed(2) ?? "—"}</small><small>{row.geometry_origin === "held" ? "Recent 3D sample held for evidence" : row.warnings?.[0] || "Estimated evidence; no force measurement"}</small></div>)}
        <p className="semantic-note">Contact scores are uncalibrated hypotheses. Grasp/release candidates do not establish physical validity.</p>
        <details><summary>Boundary candidates</summary>{actions.map(action => <p key={action.action_id}><strong>{action.action_id} {action.primitive}</strong><br />{action.semantic_start_s.toFixed(2)}s semantic → {action.refined_start_s?.toFixed(2) ?? "unchanged"}{action.refined_start_s != null ? "s candidate" : ""}</p>)}</details>
      </div></div>
      <div className="reconstruction-review"><strong>{handoff?.ready_for_robotization ? "Interaction handoff available" : "Review required before robotization"}</strong><ul>{report.review_reasons.map((reason, i) => <li key={i}>{reason}</li>)}</ul></div>
    </>}
  </section>;
}
