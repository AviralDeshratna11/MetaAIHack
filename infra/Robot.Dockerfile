# Optional runtime; build the existing base first (docker compose build api).
FROM video2robot-backend:dev
RUN apt-get update && apt-get install -y --no-install-recommends libegl1 libgl1 libosmesa6 && rm -rf /var/lib/apt/lists/*
COPY requirements-robot.txt requirements-lerobot.txt /opt/requirements/
RUN pip install --no-cache-dir -r /opt/requirements/requirements-robot.txt
RUN python -m venv /opt/lerobot && /opt/lerobot/bin/pip install --no-cache-dir torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cpu
RUN /opt/lerobot/bin/pip install --no-cache-dir --timeout 120 --retries 5 lerobot==0.4.1 --no-deps && /opt/lerobot/bin/pip install --no-cache-dir --timeout 120 --retries 5 -r /opt/requirements/requirements-lerobot.txt
COPY requirements-rl.txt /opt/requirements/
RUN /opt/lerobot/bin/pip install --no-cache-dir -r /opt/requirements/requirements-rl.txt -r /opt/requirements/requirements-robot.txt
ENV MUJOCO_GL=egl LEROBOT_PYTHON=/opt/lerobot/bin/python
