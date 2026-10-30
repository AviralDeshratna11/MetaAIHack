# Meta provider contract

Documentation checked on 2026-10-30; account availability remains unverified until
the project owner supplies credentials for a later live test. No paid calls are
required or made by the offline tests. The default is `INFERENCE_MODE=fixture`.

- [Muse video understanding](https://dev.meta.ai/docs/video-understanding): Files
  upload with purpose `user_data`, then Responses `input_file` with `file_id`.
  The configured Muse default is `muse-spark-1.3`; output is locally validated JSON.
- [SAM overview](https://dev.meta.ai/docs/sam/overview): Responses API with a text
  concept and `input_video`; one concept per request. The API example spells the
  model `sam-3.1`, while the [model page](https://dev.meta.ai/models/sam-3-1) labels
  it `sam-3-1`. The configurable default follows the API example; capability
  inspection must confirm the account's actual model ID before live processing.
- [SAM output grammar](https://dev.meta.ai/docs/sam/reading-segmentation): explicit,
  possibly sparse/unordered frame markers and object ordinals, followed by box and
  box-local mask tokens. Zero matches is valid. Objects are stable within continuous
  visibility, not guaranteed through exits or complete occlusion.
- [Official parser](https://dev.meta.ai/docs/sam/client-libraries): installed Python
  package `meta-sam-parser==0.1.0`; use `parse_responses_stream` with
  `video_segmentation_format`, not a semantic JSON parser. Retain raw responses;
  reject malformed diagnostics instead of silently omitting bad records.

The implementation requests non-streaming SAM responses, which the overview supports,
then feeds finalized text into the official parser. This bounds transport complexity
for short clips; internal job progress uses SSE independently. No SAM session/polling
endpoint is invented. No local Object Multiplex performance claim is made for hosted
concept calls. There is one concept request per entity per shot, bounded by the job
request budget; Files references are cached within the run. Each shot is encoded
separately to enforce continuity boundaries. The remaining live acceptance checks are
provider media limits, model access, confidence behavior and real-video latency.

The adapter requests `metadata.mask_encoding=one_bit` and
`metadata.include_confidence=true` as documented strings. Confidence absent from a
record remains null. Derived tracking confidence (.9 on an ordinary measured row,
.65 when warnings apply) is an explicitly uncalibrated heuristic, not a probability
from Meta. A post-occlusion candidate is unverified even when its ordinal is unchanged.

Visual corrections use the official `build_object_prompt` helper with media size,
frame, point or half-open box. Corrections are recorded in a new run; fixture masks
are fixed color outputs and do not react to point/box prompts. Association corrections
choose a provider candidate explicitly. The UI labels fixture correction behavior.

The per-job default of 16 provider requests includes Files uploads and retries.
Timeouts after transmission are unknown outcomes and block automatic replay.
Actual/estimated cost stay null unless independently known; usage and provider request
IDs are retained. A model-access probe is a separate explicit command, never a
background paid inference call. Set the API key in `.env` locally; never send it in chat.
