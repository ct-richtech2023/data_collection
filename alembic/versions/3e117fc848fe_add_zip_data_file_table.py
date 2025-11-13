"""add_zip_data_file_table

Revision ID: 3e117fc848fe
Revises: 21e6b98fdc36
Create Date: 2025-11-13 09:16:48.682504

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3e117fc848fe'
down_revision: Union[str, None] = '21e6b98fdc36'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 创建 zip_data_file 表
    op.create_table('zip_data_file',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('file_name', sa.Text(), nullable=False),
    sa.Column('file_size', sa.BigInteger(), nullable=False),
    sa.Column('download_number', sa.Integer(), nullable=False),
    sa.Column('download_url', sa.Text(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('create_time', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('update_time', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    # 创建索引
    op.create_index(op.f('ix_zip_data_file_id'), 'zip_data_file', ['id'], unique=False)
    op.create_index('ix_zip_data_file_user_id', 'zip_data_file', ['user_id'], unique=False)


def downgrade() -> None:
    # 删除索引
    op.drop_index('ix_zip_data_file_user_id', table_name='zip_data_file')
    op.drop_index(op.f('ix_zip_data_file_id'), table_name='zip_data_file')
    # 删除表
    op.drop_table('zip_data_file')
