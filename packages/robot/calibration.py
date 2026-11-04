"""Measured world-to-base similarity fit; no inference of physical dimensions."""
import hashlib
import json
import numpy as np
from packages.geometry.math3d import align_similarity
from packages.schemas.robotization import Calibration


def fit_calibration(world_points,base_points_m,evidence,max_residual_m=.02):
    source,target=np.asarray(world_points,float),np.asarray(base_points_m,float)
    scale,rotation,translation,rmse=align_similarity(source,target)
    if not evidence.strip():raise ValueError('Measurement evidence is required')
    if rmse>max_residual_m:raise ValueError(f'Calibration residual {rmse:.6f}m exceeds {max_residual_m:.6f}m')
    transform=np.eye(4);transform[:3,:3]=rotation;transform[:3,3]=translation
    digest=hashlib.sha256(json.dumps({'world':source.tolist(),'base_m':target.tolist()},sort_keys=True).encode()).hexdigest()
    return Calibration(mode='measured',scale_m_per_unit=scale,base_from_world=transform.tolist(),evidence=evidence,
        residual_m=rmse,correspondence_hash=digest,correspondence_count=len(source))
