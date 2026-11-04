"use client";
import {useState} from "react";
import type {RobotizationConfig} from "../generated/contracts";
type Calibration=NonNullable<RobotizationConfig["calibration"]>;
const API=process.env.NEXT_PUBLIC_API_URL||"http://localhost:58000";

export default function CalibrationForm({onApply}:{onApply:(calibration:Calibration)=>void}) {
  const [world,setWorld]=useState("");const [base,setBase]=useState("");const [evidence,setEvidence]=useState("");
  const [busy,setBusy]=useState(false);const [error,setError]=useState("");const [result,setResult]=useState<Calibration|null>(null);
  async function fit(){
    setBusy(true);setError("");
    try {
      const response=await fetch(API+"/v1/calibration/fit",{method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({world_points:JSON.parse(world),base_points_m:JSON.parse(base),evidence})});
      const data=await response.json();if(!response.ok)throw new Error(data.message||"Calibration fit failed");
      setResult(data);onApply(data);
    }catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  return <details><summary>Fit measured scene-to-robot calibration</summary>
    <p>Supply at least three corresponding non-collinear points. Scene coordinates use the selected shot world; robot-base coordinates must be measured in meters. A residual checks the fit, not the truth of supplied measurements.</p>
    <label>Scene points (JSON array of xyz)<textarea aria-label="Calibration scene points" value={world} onChange={e=>setWorld(e.target.value)} placeholder="[[x,y,z], ...]" rows={3}/></label>
    <label>Matching robot-base points in meters<textarea aria-label="Calibration robot points" value={base} onChange={e=>setBase(e.target.value)} placeholder="[[x,y,z], ...]" rows={3}/></label>
    <label>Measurement evidence<input value={evidence} onChange={e=>setEvidence(e.target.value)} placeholder="Measurement method and reference"/></label>
    <button disabled={busy||!world||!base||!evidence.trim()} onClick={fit}>{busy?"Fitting…":"Fit and apply calibration"}</button>
    {error&&<p role="alert">{error}</p>}
    {result&&<p>Applied scale {(result.scale_m_per_unit??1).toFixed(6)} m/unit · residual {((result.residual_m||0)*1000).toFixed(3)} mm · {result.correspondence_count} correspondences. <a download="calibration.json" href={"data:application/json;charset=utf-8,"+encodeURIComponent(JSON.stringify(result,null,2))}>Download calibration</a></p>}
  </details>;
}
