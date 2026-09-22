"""index order items by product

Índice sobre `order_items.product_id`: `sold_count` (unidades vendidas de un producto, decisión
0023) agrega las líneas de orden pagadas de un producto, y sin este índice esa subconsulta recorre
la tabla entera de líneas.

Es la columna `product_id`, no `variant_id`: la insignia «más vendido» va por producto, y la ficha
del producto agrega todas sus variantes.

Revision ID: 8f0a63d4c1b9
Revises: dd68961274d7
Create Date: 2026-09-22 18:05:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f0a63d4c1b9"
down_revision: str | None = "dd68961274d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_order_items_product_id", "order_items", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_order_items_product_id", table_name="order_items")
