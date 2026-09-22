"""enable search indexes

Revision ID: 26a56be90086
Revises: 915dafad01ed
Create Date: 2026-09-21 21:33:39.572461

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '26a56be90086'
down_revision: str | None = '915dafad01ed'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX ix_products_title_trgm ON products USING gin (title gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_products_search_vector ON products USING gin ("
        "to_tsvector('simple', coalesce(title, '') || ' ' || "
        "coalesce(description, '') || ' ' || coalesce(brand, ''))"
        ")"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_products_search_vector")
    op.execute("DROP INDEX IF EXISTS ix_products_title_trgm")
    # pg_trgm no se elimina: es una extensión compartida y segura de mantener.
