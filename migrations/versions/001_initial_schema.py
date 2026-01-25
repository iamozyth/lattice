"""Initial schema: subnets, ips, users

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-01-25 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001_initial_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create subnets table
    op.create_table(
        'subnets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('cidr', sa.String(43), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('vlan', sa.Integer(), nullable=True),
        sa.Column('gateway', sa.String(45), nullable=True),
        sa.Column('dns_primary', sa.String(45), nullable=True),
        sa.Column('dns_secondary', sa.String(45), nullable=True),
        sa.Column('location', sa.String(255), nullable=True),
        sa.Column('environment', sa.String(50), nullable=True),
        sa.Column('tags', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
        sa.UniqueConstraint('cidr')
    )
    op.create_index('idx_subnet_cidr', 'subnets', ['cidr'])
    op.create_index('idx_subnet_vlan', 'subnets', ['vlan'])
    op.create_index('idx_subnet_environment', 'subnets', ['environment'])

    # Create ips table
    op.create_table(
        'ips',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('address', sa.String(45), nullable=False),
        sa.Column('hostname', sa.String(255), nullable=True),
        sa.Column('fqdn', sa.String(255), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('subnet_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=True),
        sa.Column('mac_address', sa.String(17), nullable=True),
        sa.Column('device_type', sa.String(100), nullable=True),
        sa.Column('manufacturer', sa.String(100), nullable=True),
        sa.Column('model', sa.String(100), nullable=True),
        sa.Column('serial_number', sa.String(100), nullable=True),
        sa.Column('owner', sa.String(255), nullable=True),
        sa.Column('department', sa.String(255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('last_seen', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['subnet_id'], ['subnets.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('address', 'subnet_id', name='unique_ip_per_subnet')
    )
    op.create_index('idx_ip_address', 'ips', ['address'])
    op.create_index('idx_ip_status', 'ips', ['status'])
    op.create_index('idx_ip_hostname', 'ips', ['hostname'])

    # Create users table
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(80), nullable=False),
        sa.Column('email', sa.String(120), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('is_admin', sa.Boolean(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username'),
        sa.UniqueConstraint('email')
    )
    op.create_index('ix_users_username', 'users', ['username'])
    op.create_index('ix_users_email', 'users', ['email'])


def downgrade():
    op.drop_index('ix_users_email', table_name='users')
    op.drop_index('ix_users_username', table_name='users')
    op.drop_table('users')
    op.drop_index('idx_ip_hostname', table_name='ips')
    op.drop_index('idx_ip_status', table_name='ips')
    op.drop_index('idx_ip_address', table_name='ips')
    op.drop_table('ips')
    op.drop_index('idx_subnet_environment', table_name='subnets')
    op.drop_index('idx_subnet_vlan', table_name='subnets')
    op.drop_index('idx_subnet_cidr', table_name='subnets')
    op.drop_table('subnets')
