import time

from alembic import command
from alembic.config import Config

from packages.common.storage import Storage


def main():
    command.upgrade(Config("apps/api/alembic.ini"), "head")
    for attempt in range(30):
        try:
            Storage().ensure_bucket()
            return
        except Exception:
            if attempt == 29:
                raise
            time.sleep(2)


if __name__ == "__main__":
    main()
