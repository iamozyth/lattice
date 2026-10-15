"""Single sign-on: settings table and SSO subject on users

Revision ID: 004_sso
Revises: 003_roles_dhcp_discoveries
Create Date: 2026-10-15
"""
import sqlalchemy as sa
from alembic import op

revision = '004_sso'
down_revision = '003_roles_dhcp_discoveries'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'settings',
        sa.Column('key', sa.String(64), primary_key=True),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime()),
    )
    op.add_column('users', sa.Column('sso_subject', sa.String(255), nullable=True))
    op.create_unique_constraint('users_sso_subject_key', 'users', ['sso_subject'])


def downgrade():
    op.drop_constraint('users_sso_subject_key', 'users', type_='unique')
    op.drop_column('users', 'sso_subject')
    op.drop_table('settings')
