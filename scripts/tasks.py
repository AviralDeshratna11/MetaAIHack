"""Cross-platform task runner; use python -m scripts.tasks TASK from repo root."""
import argparse
import os
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("task", choices=["up", "down", "api", "worker", "dispatch", "web", "test", "media-tests", "smoke", "schemas", "check", "golden"])
    task = parser.parse_args().task
    npm = "npm.cmd" if os.name == "nt" else "npm"
    tasks = {
        "up": [["docker", "compose", "up", "--build", "-d"]],
        "down": [["docker", "compose", "down"]],
        "api": [[sys.executable, "-m", "uvicorn", "apps.api.main:app", "--host", "127.0.0.1", "--port", "58000"]],
        "worker": [[sys.executable, "-m", "rq", "worker", "--url", os.environ.get("REDIS_URL", "redis://localhost:56379/0"), "video2robot"]],
        "dispatch": [[sys.executable, "-m", "apps.api.orchestration"]],
        "web": [[npm, "run", "dev"]],
        "test": [[sys.executable, "-m", "pytest", "-q"]],
        "media-tests": [["docker", "compose", "run", "--rm", "api", "python", "-m", "pytest", "-q", "tests/test_media.py"]],
        "smoke": [[sys.executable, "-m", "scripts.smoke"]],
        "schemas": [[sys.executable, "-m", "scripts.export_schemas"], [npm, "run", "schemas"]],
        "check": [[sys.executable, "-m", "pytest", "-q"], [sys.executable, "-m", "scripts.export_schemas", "--check"],
                  [npm, "run", "schemas:check"], [npm, "run", "typecheck"], [npm, "run", "build"]],
        "golden": [[sys.executable, "-m", "scripts.golden_assets", "validate"]],
    }
    for command in tasks[task]:
        subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
