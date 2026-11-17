"""Make simulator replays playable in a browser.

OpenCV's portable encoder writes MPEG-4 Part 2 (``mp4v``), which Chrome, Edge and
Firefox refuse to play in a <video> element. When an FFmpeg binary is available the
replay is re-encoded to H.264 with the same frames and rate; otherwise the original
file is kept and the report says so.
"""
import os
import shutil
import subprocess
from pathlib import Path


def ffmpeg_binary():
    configured = os.environ.get("FFMPEG") or "ffmpeg"
    found = shutil.which(configured)
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def browser_playable(path):
    """Re-encode in place. Returns the codec actually stored and why."""
    path = Path(path)
    binary = ffmpeg_binary()
    if binary is None:
        return {"codec": "mp4v", "browser_playable": False, "reason": "No FFmpeg binary; install imageio-ffmpeg or set FFMPEG"}
    target = path.with_name(path.stem+".h264.mp4")
    # passthrough keeps one output frame per rendered frame for dataset alignment.
    command = [binary, "-y", "-loglevel", "error", "-i", str(path), "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-preset", "veryfast", "-crf", "20", "-fps_mode", "passthrough", "-movflags", "+faststart", str(target)]
    try:
        completed = subprocess.run(command, capture_output=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"codec": "mp4v", "browser_playable": False, "reason": f"FFmpeg could not run: {exc}"}
    if completed.returncode or not target.is_file() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        return {"codec": "mp4v", "browser_playable": False, "reason": completed.stderr.decode(errors="replace")[-300:] or "FFmpeg failed"}
    os.replace(target, path)
    return {"codec": "h264", "browser_playable": True, "reason": None}
