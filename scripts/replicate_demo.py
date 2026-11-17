"""Video demonstration -> inferred skill -> robot replication in simulation, without the web stack.

Runs the same compiler entry point as the queued worker. The demonstration is either
an existing reconstruction (``--itr interaction_trajectory.json.gz``) or a labeled
synthetic one (``--demo``). Output: replay video, reports, datasets and ``viewer.html``.

    python -m scripts.replicate_demo --demo laptop_lid
    python -m scripts.replicate_demo --itr path/to/interaction_trajectory.json.gz --hand HAND_A --object LAPTOP
"""
import argparse
import gzip
import html
import json
import os
import tempfile
import time
from pathlib import Path

from packages.robot.synthetic import DEMOS, demonstration
from packages.schemas.reconstruction import InteractionTrajectory
from packages.schemas.robotization import RobotizationConfig


def viewer(output, title, synthetic):
    """Self-contained page: replay video next to what was inferred and what happened."""
    read = lambda name: json.loads((output/name).read_text(encoding="utf-8"))
    report, quality, simulation = read("replication_report.json"), read("quality_report.json"), read("simulation_report.json")
    skill, scene, joint = report["skill"], report["scene"], simulation["task_joint"]
    free = scene is None  # carried object: progress is distance moved, not a joint value
    if free:
        task, origin = report["transport"], simulation["states"][0]["proxy_object_position_m"]
        distance = sum(v*v for v in task["displacement_m"])**.5
        scene = {"joint": "free", "template": "carried object", "start": 0., "goal": distance, "momentary": False}
        joint = {"start": 0., "final": simulation["object_displacement_m"], "peak": simulation["object_displacement_m"]}
        for state in simulation["states"]:
            state["task_joint_value"] = sum((a-b)**2 for a, b in zip(state["proxy_object_position_m"], origin))**.5
    reached = joint["peak"] if scene.get("momentary") else abs(joint["final"]-joint["start"])
    unit = "rad" if scene["joint"] == "revolute" else "m"
    amount = lambda v: f"{v:.3f} {unit}" + (f" ({v*57.2958:.0f}°)" if unit == "rad" else "")
    def row(v):
        final = "—" if v["final_joint"] is None else format(v["final_joint"], ".3f")
        outcome = "success" if v["success"] else html.escape(v["reason"] or "failed")
        position = ", ".join(format(x, ".3f") for x in v["position_m"])
        return (f"<tr><td>{v['index']+1}</td><td>{position}</td><td>{v['yaw_rad']*57.2958:.0f}°</td><td>{v['radius_m']:.3f}</td>"
                f"<td>{final} / {v['goal']:.3f}</td><td class=\"{'ok' if v['success'] else 'bad'}\">{outcome}</td></tr>")
    rows = "".join(row(v) for v in report["variations"]) or "<tr><td colspan=6>No variations requested</td></tr>"
    varied = "not run" if not report["variations"] else str(sum(v["success"] for v in report["variations"]))+" of "+str(len(report["variations"]))+" succeeded"
    reasons = "".join("<li>"+html.escape(r)+"</li>" for r in report["review_reasons"])
    gate = html.escape(", ".join(quality["reasons"]).replace("_", " ") or "none")
    violations = html.escape(", ".join(simulation["violations"]) or "none")
    preface = "Synthetic demonstration (diagnostic input, not real footage). " if synthetic else ""
    verdict, verdict_class = ("Succeeded", "ok") if report["simulation_task_success"] else ("Did not succeed", "bad")
    demonstrated_unit = html.escape(skill["displacement_unit"].replace("_", " "))
    states = [{"t": s["execution_time_s"], "phase": s.get("phase"), "joint": s.get("task_joint_value"), "source": s["source_time_s"]} for s in simulation["states"]]
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>
:root{{--bg:#f6f7f9;--card:#fff;--ink:#1c2430;--muted:#5b6777;--line:#dfe3e8;--ok:#1f7a4d;--bad:#b3261e;--accent:#b45f06}}
@media (prefers-color-scheme:dark){{:root{{--bg:#12161c;--card:#1b212a;--ink:#e8ecf1;--muted:#9aa6b5;--line:#2d3642;--ok:#5ac68e;--bad:#f2857d;--accent:#f0a44b}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}}main{{max-width:1080px;margin:auto;padding:24px 16px}}
h1{{font-size:22px;margin:0 0 4px}}h2{{font-size:15px;margin:0 0 8px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}}
.grid{{display:grid;grid-template-columns:minmax(0,3fr) minmax(0,2fr);gap:16px}}@media(max-width:800px){{.grid{{grid-template-columns:1fr}}}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px;margin-top:16px}}video{{width:100%;border-radius:6px;background:#000}}
dl{{display:grid;grid-template-columns:auto 1fr;gap:4px 16px;margin:0}}dt{{color:var(--muted)}}dd{{margin:0}}
table{{width:100%;border-collapse:collapse;font-size:14px}}td,th{{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}}
.ok{{color:var(--ok);font-weight:600}}.bad{{color:var(--bad);font-weight:600}}.note{{color:var(--muted);font-size:13px}}
#live{{font-variant-numeric:tabular-nums;margin-top:8px}}#bar{{height:8px;background:var(--line);border-radius:4px;overflow:hidden;margin-top:6px}}#fill{{height:100%;width:0;background:var(--accent)}}
.scroll{{overflow-x:auto}}</style></head><body><main>
<h1>{html.escape(title)}</h1>
<p class="note">{preface}Real MuJoCo physics on the pinned Franka model. The object is a stand-in generated from the inferred skill, not a reconstruction of the filmed object.</p>
<div class="grid"><section class="card"><h2>Simulated replication</h2><video id="v" src="simulation/simulation_replay.mp4" controls autoplay muted loop playsinline></video>
<div id="live">—</div><div id="bar"><div id="fill"></div></div></section>
<section class="card"><h2>Result</h2><dl>
<dt>Task in simulation</dt><dd class="{verdict_class}">{verdict}</dd>
<dt>{'Object carried' if free else 'Joint moved'}</dt><dd>{amount(reached)} of {amount(abs(scene['goal']-scene['start']))} planned</dd>
<dt>Checked violations</dt><dd>{violations}</dd>
<dt>Moved/resized scenes</dt><dd>{varied}</dd>
<dt>Quality gate</dt><dd>{html.escape(quality['classification'])}</dd></dl>
<h2 style="margin-top:16px">Inferred skill</h2><dl>
<dt>Joint</dt><dd>{html.escape(skill['kind'])} → {html.escape(scene['template'])}</dd>
<dt>Direction</dt><dd>{html.escape(skill['direction'])}</dd>
<dt>Demonstrated</dt><dd>{skill['displacement']:.3f} {demonstrated_unit}</dd>
<dt>Evidence</dt><dd>{html.escape(skill['direction_evidence'])}</dd>
<dt>Samples</dt><dd>{skill['samples']} hand poses, {skill['contact_samples']} in contact</dd>
<dt>Confidence</dt><dd>{skill['confidence']:.2f} (heuristic, uncalibrated)</dd></dl></section></div>
<section class="card"><h2>Same skill, different scene</h2><div class="scroll"><table><tr><th>#</th><th>Object position (m)</th><th>Yaw</th><th>Radius (m)</th><th>Achieved / goal</th><th>Outcome</th></tr>{rows}</table></div>
<p class="note">Each row re-plans from the object's new pose and re-runs physics. The robot motion differs; the process does not.</p></section>
<section class="card"><h2>Open items</h2><ul>{reasons}</ul>
<p class="note">Quality reasons: {gate}. Files: robot_trajectory.json, simulation_report.json, replication_report.json, skill_model.json, learning_bundle.zip.</p></section>
</main><script>
const states={json.dumps(states)},goal={scene['goal']},start={scene['start']},unit={json.dumps(unit)};
const v=document.getElementById('v'),live=document.getElementById('live'),fill=document.getElementById('fill');
function tick(){{let s=states[0];for(const x of states){{if(x.t<=v.currentTime+1e-6)s=x;else break;}}
const p=Math.max(0,Math.min(1,(s.joint-start)/(goal-start)));
live.textContent=`phase: ${{s.phase}} · robot ${{s.t.toFixed(2)}}s ↔ demonstration ${{s.source.toFixed(2)}}s · joint ${{s.joint.toFixed(3)}} ${{unit}} (${{(p*100).toFixed(0)}}% of goal)`;
fill.style.width=(p*100)+'%';requestAnimationFrame(tick);}}tick();
</script></body></html>"""
    (output/"viewer.html").write_text(page, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--demo", choices=sorted(DEMOS), help="Synthetic demonstration (diagnostic)")
    parser.add_argument("--itr", type=Path, help="interaction_trajectory.json or .json.gz from a reconstruction run")
    parser.add_argument("--hand"); parser.add_argument("--object"); parser.add_argument("--shot")
    parser.add_argument("--start", type=float, default=0); parser.add_argument("--end", type=float, default=120)
    parser.add_argument("--robot", choices=["panda", "fr3"], default="panda")
    parser.add_argument("--assets", help="Robot asset directory; defaults to data/robots/<robot>")
    parser.add_argument("--template", choices=["auto", "lid", "door", "drawer", "knob", "button", "object"], default="auto")
    parser.add_argument("--direction", choices=["auto", "open", "close"], default="auto")
    parser.add_argument("--variations", type=int, default=4)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--no-export", action="store_true", help="Skip the LeRobot dataset export")
    parser.add_argument("--lerobot-python", default=".venv-lerobot/Scripts/python.exe" if os.name == "nt" else ".venv-lerobot/bin/python")
    parser.add_argument("--output", type=Path, default=Path("data/replication"))
    args = parser.parse_args()
    if bool(args.demo) == bool(args.itr):
        parser.error("Choose exactly one of --demo or --itr")
    if args.demo:
        itr, truth = demonstration(args.demo, seed=args.seed)
        hand, thing, shot, title = "HAND", "OBJECT", "shot_000", f"Replication: {itr.task} (synthetic demonstration)"
    else:
        raw = args.itr.read_bytes()
        itr = InteractionTrajectory.model_validate_json(gzip.decompress(raw) if args.itr.suffix == ".gz" else raw)
        truth = None
        actors = [e.entity_id for e in itr.entities if e.role == "actor"]
        others = [e.entity_id for e in itr.entities if e.role == "manipulated_object"] or [e.entity_id for e in itr.entities if e.role != "actor"]
        hand, thing = args.hand or (actors[0] if actors else None), args.object or (others[0] if others else None)
        shot = args.shot or (itr.frames[0].shot_id if itr.frames else None)
        if not hand or not thing or not shot:
            parser.error("Could not choose --hand/--object/--shot from the reconstruction; pass them explicitly")
        title = f"Replication: {itr.task}"
    assets = args.assets or ("data/robots/franka_fr3" if args.robot == "fr3" else "data/robots/franka_emika_panda")
    config = RobotizationConfig(robot_id=args.robot, mode="skill", hand_id=hand, object_id=thing, shot_id=shot, start_s=args.start,
        end_s=args.end, initial_gripper="open", require_export=not args.no_export,
        replication={"template": args.template, "direction": args.direction, "variations": args.variations, "variation_seed": args.seed})
    args.output.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix=f"{args.demo or 'itr'}-", dir=args.output))
    from workers.robotization_entry import run
    lerobot = Path(args.lerobot_python)
    request = {"itr": itr.model_dump(mode="json"), "handoff": {"review_reasons": []}, "run_id": output.name,
        "runtime": {"config": config.model_dump(mode="json"), "assets": assets, "lerobot_python": str(lerobot.absolute()) if lerobot.is_file() else ""}}
    started = time.monotonic()
    trajectory, simulation, export, quality = run(request, output)
    report = json.loads((output/"replication_report.json").read_text(encoding="utf-8"))
    viewer(output, title, bool(args.demo))
    rl = json.loads((output/"rl"/"rl_report.json").read_text(encoding="utf-8"))
    summary = {"status": "replicated" if report["simulation_task_success"] else "not_replicated", "output": output.as_posix(),
        "viewer": (output/"viewer.html").as_posix(), "video": (output/"simulation"/"simulation_replay.mp4").as_posix(),
        "input": "synthetic demonstration" if args.demo else str(args.itr), "ground_truth": truth,
        "skill": {k: report["skill"][k] for k in ("kind", "template", "direction", "displacement", "displacement_unit", "confidence")},
        "joint": simulation["task_joint"], "object_displacement_m": simulation["object_displacement_m"],
        "planned": report["scene"] or report["transport"], "violations": simulation["violations"], "video_codec": simulation["video"],
        "variations": {"succeeded": sum(v["success"] for v in report["variations"]), "total": len(report["variations"])},
        "frames": len(trajectory.frames), "export": {k: export.get(k) for k in ("status", "roundtrip_passed", "reason")},
        "rl": {k: rl.get(k) for k in ("status", "transitions", "reason")}, "quality": quality.classification,
        "quality_reasons": quality.reasons, "elapsed_s": round(time.monotonic()-started, 1)}
    (output/"summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    if not report["simulation_task_success"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
