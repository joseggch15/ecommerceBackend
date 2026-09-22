"""add cart item price snapshot

Añade `cart_items.unit_price_snapshot`: el precio de la variante **cuando se añadió** la línea al
carrito. Con él la respuesta del carrito puede avisar de que el precio cambió (`price_changed`).

Es `NULL` en las líneas que ya existían (se añadieron antes de esta columna); en ese caso no se
avisa de ningún cambio, porque no hay precio de referencia.

Las dos líneas de índices que generó `--autogenerate` (`ix_products_search_vector` e
`ix_products_title_trgm`) se han **eliminado a mano**: son un falso positivo, porque esos índices
GIN se crean con SQL crudo en la migración `26a56be90086` y no están declarados en el modelo.

Revision ID: dd68961274d7
Revises: e7c9474064ee
Create Date: 2026-09-22 14:07:57.683705

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "dd68961274d7"
down_revision: str | None = "e7c9474064ee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cart_items",
        sa.Column("unit_price_snapshot", sa.Numeric(precision=12, scale=2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cart_items", "unit_price_snapshot")
