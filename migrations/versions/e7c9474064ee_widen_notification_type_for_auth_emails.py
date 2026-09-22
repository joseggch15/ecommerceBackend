"""widen notification type for auth emails

Amplia `notifications.type` porque los correos transaccionales añaden dos valores más largos que
el máximo anterior (`order_delivered`, 15 caracteres): `email_verification` (18) y
`password_reset` (14). La columna es un VARCHAR sin restricción de comprobación, así que basta con
ensancharla.

Las dos líneas de índices que generó `--autogenerate` (`ix_products_search_vector` y
`ix_products_title_trgm`) se han eliminado a mano: son un falso positivo, porque esos índices GIN
se crean con SQL crudo en la migración `26a56be90086` y no están declarados en el modelo.

Revision ID: e7c9474064ee
Revises: 6ea2b3f185b6
Create Date: 2026-09-22 13:46:03.834865

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7c9474064ee"
down_revision: str | None = "6ea2b3f185b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOTIFICATION_TYPE = sa.Enum(
    "order_paid",
    "order_shipped",
    "order_delivered",
    "order_cancelled",
    "welcome",
    "email_verification",
    "password_reset",
    name="notification_type",
    native_enum=False,
)


def upgrade() -> None:
    op.alter_column(
        "notifications",
        "type",
        existing_type=sa.VARCHAR(length=15),
        type_=_NOTIFICATION_TYPE,
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "notifications",
        "type",
        existing_type=_NOTIFICATION_TYPE,
        type_=sa.VARCHAR(length=15),
        existing_nullable=False,
    )
