"""Run in an explicitly configured GPU environment, not the default CPU worker.

No downloads: install the official VGGT/SAM3D packages and supply local weights.
Output is arrays + JSON (never pickle). Checkpoints are trusted server configuration.
"""
import argparse
import json
import time
from contextlib import contextmanager
from pathlib import Path

import cv2
import numpy as np

from packages.geometry.math3d import unproject


@contextmanager
def local_body_backbone(torch, directory):
    """Route the real upstream constructor to pinned local code; prohibit Hub downloads."""
    directory = Path(directory)
    if not (directory / "hubconf.py").is_file() or not (directory / "source_manifest.json").is_file():
        raise RuntimeError("Pinned local DINOv3 source is required for SAM 3D Body")
    original = torch.hub.load
    def load(repo_or_dir, model, *args, **kwargs):
        if repo_or_dir != "facebookresearch/dinov3" or kwargs.get("pretrained", True):
            raise RuntimeError("Unconfigured online Torch Hub model load blocked")
        kwargs.pop("source", None)
        return original(str(directory), model, *args, source="local", **kwargs)
    torch.hub.load = load
    try:
        yield
    finally:
        torch.hub.load = original


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
    started = time.monotonic()
    cfg = request["config"]
    import torch
    from vggt.models.vggt import VGGT
    from vggt.utils.pose_enc import pose_encoding_to_extri_intri
    if not torch.cuda.is_available():
        raise RuntimeError("Local VGGT/SAM3D worker requires CUDA; fixture mode is separate")
    paths = sorted(((int(i), p) for i, p in request["frames"].items()))
    originals = [cv2.cvtColor(cv2.imread(path), cv2.COLOR_BGR2RGB) for _, path in paths]
    padded = [preprocess(img, cfg.get("image_size", 518)) for img in originals]
    images_cpu = torch.from_numpy(np.stack([p[0].transpose(2, 0, 1) for p in padded])).float() / 255
    dtype = torch.bfloat16 if torch.cuda.get_device_capability()[0] >= 8 else torch.float16
    low = cfg.get("memory_mode") == "low_vram"
    if low:
        # The official aggregator and camera/depth heads are used unchanged. Keep
        # the aggregator in reduced precision on CUDA and run its FP32 heads on CPU.
        # Point/track heads are unused by this adapter and need not be loaded.
        if len(paths) > 4:
            raise RuntimeError("low_vram frame quota exceeded")
        from accelerate import init_empty_weights
        with init_empty_weights():
            model = VGGT(enable_point=False, enable_track=False)
        weights = torch.load(cfg["vggt_checkpoint"], map_location="cpu", weights_only=True, mmap=True)
        weights = {k:v for k,v in weights.items() if not k.startswith(("point_head.", "track_head."))}
        model.load_state_dict(weights, assign=True)
        model.eval()
        model.aggregator.to(device="cuda", dtype=dtype)
        images = images_cpu.cuda()
        with torch.inference_mode(), torch.autocast(device_type="cuda", dtype=dtype):
            tokens, patch_start_idx = model.aggregator(images[None])
        tokens_cpu = [t.float().cpu() if t is not None else None for t in tokens]
        del tokens, images
        # Release CUDA weights before depth decoding/body inference.
        model.aggregator = None
        torch.cuda.empty_cache()
        with torch.inference_mode():
            poses = model.camera_head(tokens_cpu)[-1]
            depths, confidence = model.depth_head(tokens_cpu, images=images_cpu[None], patch_start_idx=patch_start_idx)
        predictions = {"pose_enc": poses, "depth": depths, "depth_conf": confidence}
        del tokens_cpu, weights
    else:
        model = VGGT()
        model.load_state_dict(torch.load(cfg["vggt_checkpoint"], map_location="cpu", weights_only=True))
        model = model.cuda().eval()
        images = images_cpu.cuda()
        with torch.inference_mode(), torch.autocast(device_type="cuda", dtype=dtype):
            predictions = model(images)
        del images
    extrinsic, intrinsic = pose_encoding_to_extri_intri(predictions["pose_enc"], images_cpu.shape[-2:])
    extrinsic, intrinsic = extrinsic[0].float().cpu().numpy(), intrinsic[0].float().cpu().numpy()
    depths = predictions["depth"][0].float().cpu().numpy()[..., 0]
    confidence = predictions["depth_conf"][0].float().cpu().numpy()
    del model, predictions, images_cpu
    torch.cuda.empty_cache()
    (args.output / "runtime_report.json").write_text(json.dumps({"torch": torch.__version__,
        "device": torch.cuda.get_device_name(0), "memory_mode": cfg.get("memory_mode", "standard"),
        "image_size": cfg.get("image_size", 518), "sampled_frames": len(paths),
        "peak_cuda_bytes": torch.cuda.max_memory_allocated(), "camera_depth_heads": "cpu_fp32" if low else "cuda",
        "precision": str(dtype)}), encoding="utf-8")
    body = None
    if cfg["body_backend"] == "sam3d":
        from sam_3d_body import SAM3DBodyEstimator, load_sam_3d_body
        from sam_3d_body.metadata.mhr70 import mhr_names
        if low:
            # Same pinned upstream construction/state loader; mmap avoids a second
            # resident checkpoint copy on memory-limited hosts.
            from sam_3d_body.models.meta_arch import SAM3DBody
            from sam_3d_body.utils.config import get_config
            from sam_3d_body.utils.checkpoint import load_state_dict
            model_cfg = get_config(str(Path(cfg["body_checkpoint"]).parent / "model_config.yaml"))
            model_cfg.defrost()
            model_cfg.MODEL.MHR_HEAD.MHR_MODEL_PATH = cfg["body_mhr"]
            model_cfg.freeze()
            local_source = Path(cfg["body_checkpoint"]).parent.parent / "sources" / "dinov3"
            with local_body_backbone(torch, local_source):
                model = SAM3DBody(model_cfg)
            checkpoint = torch.load(cfg["body_checkpoint"], map_location="cpu", weights_only=False, mmap=True)
            state = checkpoint.get("state_dict", checkpoint)
            derived_suffixes = ("mask_token", "hand_pose_comps_ori")
            missing = [name for name, _ in model.named_parameters() if name not in state
                       and ".mhr." not in name and not name.endswith(derived_suffixes)]
            if missing:
                raise RuntimeError("Body checkpoint does not match required learned parameters: "+", ".join(missing[:8]))
            load_state_dict(model, state, strict=False)
            del state, checkpoint
            model = model.to("cuda").eval()
        else:
            local_source = Path(cfg["body_checkpoint"]).parent.parent / "sources" / "dinov3"
            with local_body_backbone(torch, local_source):
                model, model_cfg = load_sam_3d_body(cfg["body_checkpoint"], device=torch.device("cuda"), mhr_path=cfg["body_mhr"])
        body = SAM3DBodyEstimator(model, model_cfg)
    body_count = 0
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
        body_count += len(people)
    report_path = args.output / "runtime_report.json"
    report = json.loads(report_path.read_text())
    report.update(status="completed", body_backend=cfg["body_backend"], body_hypotheses=body_count,
                  peak_cuda_bytes=torch.cuda.max_memory_allocated(), elapsed_s=round(time.monotonic()-started, 3))
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
