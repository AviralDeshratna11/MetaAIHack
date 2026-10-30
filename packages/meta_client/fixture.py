import json

import cv2
import numpy as np

from packages.schemas.models import ActionGraph, ActionSegment, Edge, Entity, SemanticPlan
from packages.video.masks import bbox


def fixture_plan(duration):
    entities = [Entity(entity_id=e, category=c, semantic_name=f"synthetic {c}", sam_prompt=c,
                       role=r, motion=m, confidence=None,
                       uncertainty_reasons=["Synthetic fixture; not model inference"])
        for e, c, r, m in [("hand", "human hand", "actor", "manipulated"),
                            ("mug", "mug", "manipulated_object", "manipulated"),
                            ("bowl", "bowl", "target", "static")]]
    primitives = ["REACH", "GRASP", "LIFT", "TRANSPORT", "POUR", "PLACE", "RELEASE"]
    actions = [ActionSegment(action_id=f"a{i:02}", primitive=p, start_s=i * duration / 7,
        end_s=(i + 1) * duration / 7, actor="hand", object="mug", target="bowl" if p == "POUR" else None,
        requires_contact=p != "REACH", uncertainty_reasons=["Synthetic timing; not inferred from video"])
        for i, p in enumerate(primitives)]
    return SemanticPlan(task="Synthetic mug-to-bowl workflow", canonical_skill="pour", duration_s=duration,
        entities=entities, actions=actions, action_graph=ActionGraph(nodes=[a.action_id for a in actions],
            edges=[Edge(source=a.action_id, target=b.action_id, reason="temporal") for a, b in zip(actions, actions[1:])]),
        warnings=["FIXTURE MODE: deterministic synthetic semantics; not real model evidence"])


class FixtureProvider:
    def semantic(self, video, duration, prompt, schema, repair, record):
        result = fixture_plan(duration).model_dump_json()
        record({"model": "synthetic-semantic-v1", "status": "completed", "latency_ms": 0,
                "usage": {}, "raw_output": result})
        return result

    def track(self, video, prompt, width, height, corrections, record):
        """Synthetic color fixtures only. No learned segmentation or human-video claims."""
        index = {"mug": 0, "bowl": 1, "human hand": 2}.get(prompt)
        records = []
        cap = cv2.VideoCapture(str(video))
        frame = 0
        while True:
            ok, image = cap.read()
            if not ok:
                break
            # Fixture colors: BGR orange, turquoise, purple.
            colors = [(40, 135, 245), (170, 190, 40), (190, 100, 190)]
            if index is not None:
                dist = np.linalg.norm(image.astype(float) - np.array(colors[index]), axis=2)
                mask = (dist < 38).astype(np.uint8)
                box = bbox(mask)
                if box:
                    records.append({"frame": frame, "object_id": "0", "mask": mask,
                                    "bbox": box, "confidence": None})
            frame += 1
        cap.release()
        record({"model": "synthetic-color-tracker-v1", "status": "completed", "latency_ms": 0,
                "usage": {"frames": frame}, "raw_output": json.dumps({"synthetic": True, "records": len(records)})})
        return records
