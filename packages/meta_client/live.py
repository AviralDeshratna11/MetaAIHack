import asyncio
import dataclasses
import json
import random
import time
from pathlib import Path
from typing import Protocol

import cv2
import httpx
import numpy as np
from meta_sam_parser import (FramePrompt, PromptBox, PromptObject, PromptPoint, build_object_prompt,
                             decode_mask_to_raster, parse_responses_stream, video_segmentation_format)

from packages.common.config import settings
from packages.common.utils import DomainError, digest


class Provider(Protocol):
    def semantic(self, video: Path, duration: float, prompt: str, schema: dict, repair: dict | None, record) -> str: ...
    def track(self, video: Path, prompt: str, width: int, height: int, corrections: list[dict], record) -> list[dict]: ...


def parse_sam_text(text: str):
    async def parse():
        # Non-streaming Responses output is fed through the official stream parser
        # using a complete, finalized lane. This preserves its grammar validation.
        async def events():
            lane = {"item_id": "msg", "output_index": 0, "content_index": 0}
            if text:
                yield {"type": "response.output_text.delta", "delta": text, **lane}
            yield {"type": "response.output_text.done", "text": text, **lane}
            yield {"type": "response.completed", "response": {"status": "completed", "output": []}}
        return await parse_responses_stream(events(), video_segmentation_format()).final_result()
    return asyncio.run(parse())


def sam_records(text, width, height):
    parsed = parse_sam_text(text)
    if parsed.outcome.status != "completed" or parsed.diagnostics:
        raise DomainError("E_SAM_PARSE", "SAM output incomplete or malformed; inspect raw provider output")
    records = []
    for rec in parsed.records:
        if rec.kind != "mask":
            continue
        if rec.frame is None:
            raise DomainError("E_SAM_FRAME", "Video mask lacks explicit frame reference")
        bounds = rec.bounds
        x1, y1, x2, y2 = [int(v) for v in [bounds.left, bounds.top, bounds.right, bounds.bottom]]
        if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
            raise DomainError("E_SAM_COORDINATES", "Provider mask outside normalized frame")
        if rec.mask.height * rec.mask.width > 100_000_000:
            raise DomainError("E_SAM_MASK", "Mask payload exceeds decode quota")
        local = np.frombuffer(decode_mask_to_raster(rec.mask), dtype=np.uint8).reshape(rec.mask.height, rec.mask.width)
        # Provider masks are box-local rasters. Expand only into the documented bounds.
        local = cv2.resize(local, (x2 - x1, y2 - y1), interpolation=cv2.INTER_NEAREST)
        full = np.zeros((height, width), dtype=np.uint8)
        full[y1:y2, x1:x2] = local
        records.append({"frame": rec.frame.frame_index, "object_id": rec.object_id,
                        "bbox": [x1, y1, x2, y2], "mask": full, "confidence": rec.confidence})
    return records


class LiveProvider:
    def __init__(self, client=None, config=None):
        cfg = settings()
        frozen = config or {}
        self.muse_model = frozen.get("muse_model", cfg.muse_model)
        self.sam_model = frozen.get("sam_model", cfg.sam_model)
        if not cfg.model_api_key and client is None:
            raise DomainError("E_CREDENTIALS", "Set MODEL_API_KEY server-side before selecting live inference", 503)
        self.client = client or httpx.Client(base_url=cfg.meta_base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {cfg.model_api_key}"}, timeout=httpx.Timeout(300, connect=20))
        self.files = {}

    def request(self, endpoint, *, record, model, key, **kwargs):
        cached = record.lookup(key) if hasattr(record, "lookup") else None
        if cached is not None:
            return cached
        for attempt in range(1, 4):
            # Persist intent before the billable request; unknown outcomes are not blindly replayed.
            event = {"model": model, "status": "started", "request_key": key, "attempt": attempt}
            record(event)
            start = time.monotonic()
            try:
                response = self.client.request("POST", endpoint, **kwargs)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                record({**event, "status": "failed", "error": {"code": "E_PROVIDER_CONNECT", "retryable": True}})
                if attempt == 3:
                    raise DomainError("E_PROVIDER_CONNECT", "Cannot connect to Meta API", 502, True) from exc
                time.sleep(min(8, 2 ** attempt + random.random()))
                continue
            except httpx.TransportError as exc:
                record({**event, "status": "unknown", "error": {"code": "E_PROVIDER_OUTCOME_UNKNOWN", "retryable": False}})
                raise DomainError("E_PROVIDER_OUTCOME_UNKNOWN", "Provider request outcome unknown; inspect model run before resubmitting", 502) from exc
            request_id = response.headers.get("x-request-id")
            if response.status_code in (429, 500, 502, 503, 504):
                record({**event, "status": "failed", "request_id": request_id,
                        "error": {"http_status": response.status_code, "retryable": True}})
                if attempt == 3:
                    raise DomainError("E_PROVIDER_TRANSIENT", f"Meta API returned {response.status_code} after three attempts", 502, True)
                retry_after = response.headers.get("Retry-After", "")
                delay = float(retry_after) if retry_after.replace(".", "", 1).isdigit() else 2 ** attempt + random.random()
                time.sleep(min(60, max(0, delay)))
                continue
            if response.is_error:
                record({**event, "status": "failed", "request_id": request_id,
                        "error": {"http_status": response.status_code, "retryable": False}})
                code = "E_CREDENTIALS" if response.status_code in (401, 403) else "E_PROVIDER_REQUEST"
                raise DomainError(code, f"Meta API rejected request ({response.status_code}); check model access and provider contract", 502)
            result = response.json()
            record({**event, "status": "completed", "request_id": request_id or result.get("id"),
                    "latency_ms": int((time.monotonic() - start) * 1000), "usage": result.get("usage") or {},
                    "raw_output": json.dumps(result)})
            return result

    def upload(self, video, record):
        from packages.common.utils import file_hash
        key = digest({"file": file_hash(video)})
        if key not in self.files:
            # HTTPX multipart streams must be reopened for each retry.
            content = video.read_bytes()
            result = self.request("files", model="files-api", key=key, record=record,
                data={"purpose": "user_data"}, files={"file": (video.name, content, "video/mp4")})
            self.files[key] = result["id"]
        return self.files[key]

    @staticmethod
    def output_text(result):
        if result.get("status") not in (None, "completed"):
            raise DomainError("E_PROVIDER_INCOMPLETE", "Provider returned incomplete response")
        parts = [part for item in result.get("output", []) for part in item.get("content", [])]
        if any(p.get("type") == "refusal" for p in parts):
            raise DomainError("E_PROVIDER_REFUSAL", "Provider refused video inference")
        return "".join(part.get("text", "") for part in parts if part.get("type") == "output_text")

    def semantic(self, video, duration, prompt, schema, repair, record):
        file_id = self.upload(video, record)
        text = f"{prompt}\nCanonical duration: {duration}\nOutput schema:\n{json.dumps(schema)}"
        if repair:
            text += "\nRepair this prior output using these validation errors:\n" + json.dumps(repair)
        payload = {"model": self.muse_model, "input": [{"role": "user", "content": [
            {"type": "input_text", "text": text}, {"type": "input_file", "file_id": file_id}]}]}
        result = self.request("responses", model=self.muse_model, key=digest(payload), record=record, json=payload)
        return self.output_text(result)

    def track(self, video, prompt, width, height, corrections, record):
        file_id = self.upload(video, record)
        visual = [c for c in corrections if c["kind"] in ("point", "box")]
        if visual:
            prompts = [FramePrompt(frame=c["frame_index"],
                box=PromptBox(*c["bbox_xyxy"]) if c["kind"] == "box" else None,
                points=[PromptPoint(*c["point"])] if c["kind"] == "point" else None) for c in visual]
            prompt = build_object_prompt(size=(width, height), objects=[PromptObject(id=0, prompts=prompts)])
        payload = {"model": self.sam_model, "stream": False,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt},
                      {"type": "input_video", "file_id": file_id}]}],
            "metadata": {"mask_encoding": "one_bit", "include_confidence": "true"}}
        result = self.request("responses", model=self.sam_model, key=digest(payload), record=record, json=payload)
        return sam_records(self.output_text(result), width, height)

