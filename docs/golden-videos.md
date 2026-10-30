# Recording and annotating real golden clips

No real golden media was supplied with the architecture. All three live acceptance
clips and the challenge cases are `missing_source` in `eval/golden/manifest.json`.
Synthetic shape videos exercise infrastructure only; their fixed action sequence
does not prove that Muse understands human demonstrations.

Record a 20–30 second third-person pouring clip with the hand, mug, bowl and return
surface visible throughout. Keep a steady camera, clear light and no hard edits.
Then record pick/place and open/close examples. Keep people who did not consent out
of the frame. Use team-recorded or authorized material and enter its provenance.
Do not infer a license merely because a video is online.

```powershell
.\.venv\Scripts\python.exe -m scripts.golden_assets import pouring C:\path\pouring.mp4 --rights team_recorded --source team-camera --consent recorded
.\.venv\Scripts\python.exe -m scripts.golden_assets validate
```

FFmpeg and ffprobe must be installed locally for the import command, or copy the
file into this workspace and run the same module through the Docker backend image.
Sources live under ignored `data/golden`; hashes and provenance stay in the manifest.
Never overwrite a source after import; add a new scenario/version instead.

Copy `eval/annotations/template.json` for each clip and annotate independently of
predictions. Actions use `primitive`, `start_s`, `end_s`. Selected mask entries use
`key` (frame/entity) and a `row-major-rle-v1` `mask`. Identity annotations contain
`frame_index`, `entity_id`, `physical_object_id`, and `visible`. Occlusion-recovery
entries contain `event_id` and `physical_object_id`. Null arrays mean unannotated;
empty arrays mean an annotator explicitly found no events. Usability is
`usable`, `review`, `reject` or `unknown`. Preserve annotator and source hash.

Evaluation greedily matches same-primitive action intervals by highest tIoU >= .5,
one-to-one. It reports precision/recall/F1, matched tIoU and boundary errors. These
coarse Muse boundaries are distinct from future physical-boundary refinement.
Mask mIoU uses selected annotated frames; missing predictions score zero and empty
unions are excluded. Identity correctness uses only annotated visible frames.
Provider ordinal changes alone are not verified physical ID switches.

```powershell
.\.venv\Scripts\python.exe -m eval.metrics.evaluate annotation.json predictions.json eval/reports/run.json
```

Expand to 24–40 diverse clips and 8–12 thorough annotations after the first three
clips work. Include partial occlusions, similar objects, moving cameras, both hands,
clutter, hard cuts and hidden/blurred negatives. Do not report synthetic evaluation
as real-model performance or replace unknown annotations with perfect scores.
