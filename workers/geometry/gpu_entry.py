"""Run in an explicitly configured GPU environment, not the default CPU worker.

No downloads: install the official VGGT/SAM3D packages and supply local weights.
Output is arrays + JSON (never pickle). Checkpoints are trusted server configuration.
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from packages.geometry.math3d import unproject


def preprocess(image, size=518):
    h, w = image.shape[:2]
    if w >= h:
        nw, nh = size, max(14, round(h * size / w / 14) * 14)
    else:
        nh, nw = size, max(14, round(w * size / h / 14) * 14)
    top, left = (size - nh)//2, (size - nw)//2
    padded = np.full((size, size, 3), 255, np.uint8)
    padded[top:top+nh, left:left+nw] = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_CUBIC)
    # OpenCV resizing maps pixel centers: u'=(u+.5)*scale-.5+padding.
    sx, sy = nw/w, nh/h
    affine = np.array([[sx, 0, left+(sx-1)/2], [0, sy, top+(sy-1)/2], [0, 0, 1.]], float)
    return padded, affine, (left, top, nw, nh)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    request = json.loads(args.request.read_text())
    cfg = request["config"]
    import torch
    from vggt.models.vggt import VGGT
    from vggt.utils.pose_enc import pose_encoding_to_extri_intri
    if not torch.cuda.is_available():
        raise RuntimeError("Local VGGT/SAM3D worker requires CUDA; fixture mode is separate")
    paths = sorted(((int(i), p) for i, p in request["frames"].items()))
    originals = [cv2.cvtColor(cv2.imread(path), cv2.COLOR_BGR2RGB) for _, path in paths]
    padded = [preprocess(img) for img in originals]
    images = torch.from_numpy(np.stack([p[0].transpose(2, 0, 1) for p in padded])).float().cuda() / 255
    model = VGGT()
    model.load_state_dict(torch.load(cfg["vggt_checkpoint"], map_location="cpu", weights_only=True))
    model = model.cuda().eval()
    dtype = torch.bfloat16 if torch.cuda.get_device_capability()[0] >= 8 else torch.float16
    with torch.inference_mode(), torch.autocast(device_type="cuda", dtype=dtype):
        predictions = model(images)
    extrinsic, intrinsic = pose_encoding_to_extri_intri(predictions["pose_enc"], images.shape[-2:])
    extrinsic, intrinsic = extrinsic[0].float().cpu().numpy(), intrinsic[0].float().cpu().numpy()
    depths = predictions["depth"][0].float().cpu().numpy()[..., 0]
    confidence = predictions["depth_conf"][0].float().cpu().numpy()
    del model, predictions, images
    torch.cuda.empty_cache()
    body = None
    if cfg["body_backend"] == "sam3d":
        from sam_3d_body import SAM3DBodyEstimator, load_sam_3d_body
        from sam_3d_body.metadata.mhr70 import mhr_names
        model, model_cfg = load_sam_3d_body(cfg["body_checkpoint"], device=torch.device("cuda"), mhr_path=cfg["body_mhr"])
        body = SAM3DBodyEstimator(model, model_cfg)
    for order, (frame, path) in enumerate(paths):
        affine, (left, top, nw, nh) = padded[order][1:]
        h, w = originals[order].shape[:2]
        k = np.linalg.inv(affine) @ intrinsic[order]
        world_from_camera = np.eye(4)
        world_from_camera[:3] = extrinsic[order]
        world_from_camera = np.linalg.inv(world_from_camera)
        depth = cv2.resize(depths[order][top:top+nh, left:left+nw], (w, h), interpolation=cv2.INTER_LINEAR)
        conf = cv2.resize(confidence[order][top:top+nh, left:left+nw], (w, h), interpolation=cv2.INTER_NEAREST)
        points = unproject(depth, k, world_from_camera)
        points[~np.isfinite(depth) | (depth <= 1e-8)] = np.nan
        np.savez_compressed(args.output / f"frame_{frame}.npz", intrinsic=k, world_from_camera=world_from_camera,
            points=points.astype(np.float32), confidence=conf.astype(np.float32), preprocessing_affine=affine)
        people = []
        if body is not None:
            # Full-image person hypothesis: never feed a hand bbox as a person bbox.
            # Association and alignment are independently checked in the CPU stage.
            for person in body.process_one_image(str(Path(path).resolve()), cam_int=torch.from_numpy(k).float()[None]):
                people.append({"names": mhr_names,
                    "keypoints_2d": np.asarray(person["pred_keypoints_2d"])[:70, :2].tolist(),
                    "keypoints_3d": (np.asarray(person["pred_keypoints_3d"])[:70] + person["pred_cam_t"]).tolist(),
                    "person_detection": "full_image_hypothesis"})
        (args.output / f"body_{frame}.json").write_text(json.dumps(people, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    main()
