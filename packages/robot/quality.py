"""Frozen baseline-v1 gates; unknown mandatory evidence never passes Gold."""
from packages.schemas.robotization import QualityReport


def classify(trajectory, simulation, export_report):
    checks = {
        "live_source": trajectory.inference_mode == "live",
        "nonempty_trajectory": bool(trajectory.frames),
        "trajectory_valid": bool(trajectory.frames) and all(f.valid for f in trajectory.frames),
        "simulation_physics": simulation.get("physics_stepped") is True,
        "simulation_limits": simulation.get("passed") is True,
        "export_roundtrip": export_report.get("roundtrip_passed") is True,
        "requested_exports":export_report.get('requested_formats_passed',True) is True,
        "upstream_review_resolved": not trajectory.review_reasons,
        "measured_scale": trajectory.config.calibration.mode == "measured",
        "task_scene_validated": simulation.get("task_scene_validated") is True,
        "task_success": simulation.get("task_success"),
    }
    reasons = [name for name, passed in checks.items() if passed is not True]
    software = all(checks[k] is True for k in ("nonempty_trajectory", "trajectory_valid", "simulation_physics", "simulation_limits", "export_roundtrip","requested_exports"))
    classification = "Gold" if not reasons else "Silver" if software and checks["live_source"] else "Reject"
    return QualityReport(classification=classification, checks=checks, reasons=reasons,
                         accepted_training_subset=classification == "Gold")
