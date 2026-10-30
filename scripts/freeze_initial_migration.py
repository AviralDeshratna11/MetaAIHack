"""Development helper to freeze the initial model snapshot before first release."""
from pathlib import Path

from alembic.autogenerate import produce_migrations, render_python_code
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from apps.api.db import Base


def main():
    with create_engine("sqlite://").connect() as conn:
        migrations = produce_migrations(MigrationContext.configure(conn), Base.metadata)
        upgrade = render_python_code(migrations.upgrade_ops)
        downgrade = render_python_code(migrations.downgrade_ops)
    content = '''"""Initial metadata snapshot. Revision 0001."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
''' + upgrade + '\n\n\ndef downgrade():\n' + downgrade + '\n'
    Path("apps/api/migrations/versions/0001_initial.py").write_text(content, encoding="utf-8")
    print("Frozen initial migration. Future schema changes require a NEW revision.")


if __name__ == "__main__":
    main()
