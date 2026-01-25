"""add connectors table

Revision ID: 002_connectors
Revises: 001_initial_schema
Create Date: 2026-01-25
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '002_connectors'
down_revision = '001_initial_schema'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'connectors',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('type', sa.String(length=50), nullable=False),
        sa.Column('config_encrypted', sa.LargeBinary(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('last_sync_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index('idx_connector_type', 'connectors', ['type'])
    op.create_index('idx_connector_enabled', 'connectors', ['enabled'])


def downgrade():
    op.drop_index('idx_connector_enabled', table_name='connectors')
    op.drop_index('idx_connector_type', table_name='connectors')
    op.drop_table('connectors')
