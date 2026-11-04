import numpy as np
import pytest
from pydantic import ValidationError
from packages.geometry.windows import frame_windows, align_window
from packages.schemas.reconstruction import ReconstructionConfig


def test_windows_cover_frames_with_shared_reference_and_bounded_gpu_batch():
    windows = frame_windows(range(20))
    assert all(w[0] == 0 and len(w) <= 4 for w in windows)
    assert set(sum(windows, [])) == set(range(20))


def test_alignment_recovers_gauge_and_rejects_inconsistent_geometry():
    rng = np.random.default_rng(12)
    source = rng.normal(size=(20, 30, 3))
    target = 2*source + np.array([1, -.2, 3])
    scale, rotation, translation, report = align_window(source, target)
    assert scale == pytest.approx(2)
    assert np.allclose(scale*source@rotation.T+translation, target)
    assert report['independent_accuracy'] is False
    with pytest.raises(ValueError):
        align_window(source, rng.normal(size=source.shape), .001)


def test_low_vram_dense_sampling_requires_explicit_windowing():
    with pytest.raises(ValidationError):
        ReconstructionConfig(memory_mode='low_vram')
    cfg = ReconstructionConfig(memory_mode='low_vram', windowed=True, start_s=4, end_s=6)
    assert cfg.windowed
    with pytest.raises(ValidationError):
        ReconstructionConfig(start_s=6, end_s=4)
