"""create inventory tables and drop variant stock

Revision ID: 5972bb1db1b2
Revises: 26a56be90086
Create Date: 2026-09-21 21:46:05.305893

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '5972bb1db1b2'
down_revision: str | None = '26a56be90086'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'inventory_items',
        sa.Column('variant_id', sa.UUID(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('reserved_quantity', sa.Integer(), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['variant_id'], ['product_variants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_inventory_items_variant_id', 'inventory_items', ['variant_id'], unique=True)
    op.create_table(
        'inventory_movements',
        sa.Column('variant_id', sa.UUID(), nullable=False),
        sa.Column('delta', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['variant_id'], ['product_variants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_inventory_movements_variant_id', 'inventory_movements', ['variant_id'], unique=False)
    op.drop_column('product_variants', 'stock')
    # NOTA: los índices de búsqueda (pg_trgm/tsvector) los gestiona la migración
    # 26a56be90086; esta migración no los toca.


def downgrade() -> None:
    op.add_column('product_variants', sa.Column('stock', sa.INTEGER(), autoincrement=False, nullable=False))
    op.drop_index('ix_inventory_movements_variant_id', table_name='inventory_movements')
    op.drop_table('inventory_movements')
    op.drop_index('ix_inventory_items_variant_id', table_name='inventory_items')
    op.drop_table('inventory_items')
