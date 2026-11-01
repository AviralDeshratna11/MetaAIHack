"""CPU geometry kernels; no model imports or implicit unit conversion."""
import cv2
import numpy as np


def transform_points(points, transform):
    points, transform = np.asarray(points, float), np.asarray(transform, float)
    return points @ transform[:3, :3].T + transform[:3, 3]


def quaternion_matrix(quaternion):
    x, y, z, w = np.asarray(quaternion, float)
    if not np.isclose(x*x + y*y + z*z + w*w, 1, atol=1e-5):
        raise ValueError("non-unit quaternion")
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])


def matrix_quaternion(rotation):
    vector = cv2.Rodrigues(np.asarray(rotation, float))[0].ravel()
    angle = np.linalg.norm(vector)
    if angle < 1e-10:
        return [0., 0., 0., 1.]
    quaternion = np.r_[vector / angle * np.sin(angle / 2), np.cos(angle / 2)]
    return (quaternion / np.linalg.norm(quaternion)).tolist()


def pose_matrix(pose):
    if pose is None or pose["quaternion_xyzw"] is None:
        return None
    matrix = np.eye(4)
    matrix[:3, :3] = quaternion_matrix(pose["quaternion_xyzw"])
    matrix[:3, 3] = pose["position_xyz"]
    return matrix


def matrix_pose(matrix):
    return {"position_xyz": matrix[:3, 3].tolist(),
            "quaternion_xyzw": matrix_quaternion(matrix[:3, :3])}


def align_similarity(source, target):
    """Umeyama similarity: target = scale * R * source + translation.

    Reject collinear correspondences; report residual rather than a probability.
    """
    source, target = np.asarray(source, float), np.asarray(target, float)
    if source.shape != target.shape or source.ndim != 2 or source.shape[1] != 3 or len(source) < 3:
        raise ValueError("at least three paired 3D points required")
    if not np.isfinite(source).all() or not np.isfinite(target).all():
        raise ValueError("nonfinite correspondences")
    source_mean, target_mean = source.mean(0), target.mean(0)
    a, b = source - source_mean, target - target_mean
    if np.linalg.matrix_rank(a, tol=1e-8) < 2 or np.linalg.matrix_rank(b, tol=1e-8) < 2:
        raise ValueError("collinear or coincident alignment points")
    u, singular, vt = np.linalg.svd(b.T @ a / len(a))
    signs = np.ones(3)
    signs[-1] = np.linalg.det(u @ vt)
    rotation = u @ np.diag(signs) @ vt
    scale = float(np.dot(singular, signs) / np.mean(np.sum(a*a, axis=1)))
    if scale <= 0 or not np.isfinite(scale):
        raise ValueError("invalid alignment scale")
    translation = target_mean - scale * rotation @ source_mean
    aligned = scale * source @ rotation.T + translation
    rmse = float(np.sqrt(np.mean(np.sum((aligned - target)**2, axis=1))))
    return scale, rotation, translation, rmse


def unproject(depth, intrinsic, world_from_camera):
    y, x = np.indices(depth.shape)
    pixels = np.stack([x, y, np.ones_like(x)], axis=-1)
    rays = pixels @ np.linalg.inv(intrinsic).T
    return transform_points(rays * depth[..., None], world_from_camera)


def project(points, intrinsic, world_from_camera):
    camera = transform_points(points, np.linalg.inv(world_from_camera))
    projected = camera @ np.asarray(intrinsic).T
    valid = camera[:, 2] > 1e-8
    uv = np.full((len(camera), 2), np.nan)
    uv[valid] = projected[valid, :2] / projected[valid, 2:3]
    return uv


def principal_rotation(points, previous=None):
    """Surface-PCA orientation hypothesis; symmetrical axes stay unknown."""
    points = np.asarray(points, float)
    if len(points) < 12:
        return None
    values, vectors = np.linalg.eigh(np.cov(points.T))
    order = np.argsort(values)[::-1]
    values, rotation = values[order], vectors[:, order]
    if values[1] <= 1e-10 or values[0] / values[1] < 1.15 or values[1] / max(values[2], 1e-10) < 1.15:
        return None
    reference = np.eye(3) if previous is None else previous
    for i in range(2):
        if np.dot(rotation[:, i], reference[:, i]) < 0:
            rotation[:, i] *= -1
    rotation[:, 2] = np.cross(rotation[:, 0], rotation[:, 1])
    return rotation


def finite_difference(current, previous, dt):
    if current is None or previous is None or dt <= 0:
        return None
    return ((np.asarray(current) - previous) / dt).tolist()
