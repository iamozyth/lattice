"""Change history

Revision ID: 005_history
Revises: 004_sso
Create Date: 2026-10-15
"""
import sqlalchemy as sa
from alembic import op

revision = '005_history'
down_revision = '004_sso'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'changes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('at', sa.DateTime(), nullable=False),
        sa.Column('user_id', sa.Integer()),
        sa.Column('username', sa.String(80), nullable=False),
        sa.Column('via', sa.String(10), nullable=False),
        sa.Column('action', sa.String(10), nullable=False),
        sa.Column('entity', sa.String(20), nullable=False),
        sa.Column('entity_id', sa.Integer()),
        sa.Column('label', sa.String(255)),
        sa.Column('subnet_id', sa.Integer()),
        sa.Column('diff', sa.JSON(), nullable=False),
    )
    op.create_index('ix_changes_at', 'changes', ['at'])
    op.create_index('ix_changes_subnet_id', 'changes', ['subnet_id'])
    op.create_index('idx_change_entity', 'changes', ['entity', 'entity_id'])


def downgrade():
    op.drop_table('changes')
