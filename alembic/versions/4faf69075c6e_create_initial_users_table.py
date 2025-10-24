"""create_initial_users_table

Revision ID: 4faf69075c6e
Revises: bec0bfe62bad
Create Date: 2025-10-23 08:41:43.482420

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4faf69075c6e'
down_revision: Union[str, None] = 'bec0bfe62bad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
