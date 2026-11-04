"use client";
import {useEffect,useState} from "react";
const API=process.env.NEXT_PUBLIC_API_URL||"http://localhost:58000";
type Dataset={video_id:string;filename:string;run_id:string;quality:string;accepted_training_subset:boolean;robot:string;task:string|null;transitions:number;bundle_url:string;bundle_sha256:string;reasons:string[];inference_mode:string};
export default function DatasetCatalog(){
  const [items,setItems]=useState<Dataset[]>([]);const [filter,setFilter]=useState("");const [error,setError]=useState("");const [loading,setLoading]=useState(true);
  useEffect(()=>{const abort=new AbortController();setLoading(true);setError("");fetch(API+"/v1/datasets"+(filter?"?quality="+filter:""),{signal:abort.signal}).then(async r=>{if(!r.ok)throw new Error("Dataset catalog unavailable");setItems((await r.json()).datasets);}).catch(e=>{if(e.name!=="AbortError")setError(e.message);}).finally(()=>{if(!abort.signal.aborted)setLoading(false);});return()=>abort.abort();},[filter]);
  return <main style={{maxWidth:1100,margin:"auto",padding:32}}><a href="/">← Compiler workspace</a><h1>Robot learning datasets</h1>
    <p>Immutable compiled runs. Quality and simulation scope remain attached to every download. Silver and diagnostic data require explicit review before training.</p>
    <label>Quality <select value={filter} onChange={e=>setFilter(e.target.value)}><option value="">All</option>{["Gold","Silver","Reject"].map(q=><option key={q}>{q}</option>)}</select></label>
    {loading&&<p role="status">Loading datasets…</p>}{error&&<p role="alert">{error}</p>}
    {!loading&&!error&&!items.length&&<p>No compiled bundles match this filter.</p>}
    {items.map(d=><article key={d.run_id} className="card" style={{padding:24,marginTop:20}}><h2>{d.filename} · {d.quality}</h2>
      <p>{d.robot} · {d.task||"No RL task"} · {d.transitions} transitions · {d.inference_mode} source</p>
      <p>{d.accepted_training_subset?"Accepted training subset":"Review-gated diagnostic dataset"}</p>
      <ul>{d.reasons.map(r=><li key={r}>{r.replaceAll("_"," ")}</li>)}</ul>
      <a href={d.bundle_url} download>Download learning ZIP</a>{" · "}<a href={`/?video=${d.video_id}&run=${d.run_id}`}>Inspect source, replay and reports</a>
      <details><summary>Artifact integrity</summary><p>SHA-256: <code style={{overflowWrap:"anywhere"}}>{d.bundle_sha256}</code></p><p>{d.run_id}</p></details>
    </article>)}
  </main>;
}
