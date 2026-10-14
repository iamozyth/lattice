"""Roles, session versions, DHCP ranges, discoveries; normalise stored addresses

Revision ID: 003_roles_dhcp_discoveries
Revises: 002_connectors
Create Date: 2026-10-15
"""
import ipaddress

import sqlalchemy as sa
from alembic import op

revision = '003_roles_dhcp_discoveries'
down_revision = '002_connectors'
branch_labels = None
depends_on = None


def _normalize(conn, table, column, parse, scope=None):
    """Rewrite values to their canonical form unless that would clash."""
    cols = f'id, {column}' + (f', {scope}' if scope else '')
    rows = conn.execute(sa.text(f'SELECT {cols} FROM {table}')).fetchall()
    taken = {(r[2] if scope else None, r[1]) for r in rows}
    for row in rows:
        try:
            canonical = parse(row[1])
        except ValueError:
            continue
        key = (row[2] if scope else None, canonical)
        if canonical != row[1] and key not in taken:
            conn.execute(sa.text(f'UPDATE {table} SET {column} = :v WHERE id = :id'),
                         {'v': canonical, 'id': row[0]})
            taken.add(key)


def upgrade():
    # Users: is_admin -> role, plus a version that revokes sessions when bumped
    op.add_column('users', sa.Column('role', sa.String(10), nullable=False, server_default='editor'))
    op.add_column('users', sa.Column('session_version', sa.Integer(), nullable=False, server_default='1'))
    op.execute("UPDATE users SET role = 'admin' WHERE is_admin")
    op.drop_column('users', 'is_admin')
    # The unique constraints already index these
    op.drop_index('ix_users_username', table_name='users')
    op.drop_index('ix_users_email', table_name='users')

    # Subnets: scan settings
    op.add_column('subnets', sa.Column('scan_enabled', sa.Boolean(), nullable=True))
    op.add_column('subnets', sa.Column('last_scan_at', sa.DateTime(), nullable=True))
    op.drop_index('idx_subnet_cidr', table_name='subnets')

    # IPs: cascade at the database level, index MACs for conflict checks
    op.drop_constraint('ips_subnet_id_fkey', 'ips', type_='foreignkey')
    op.create_foreign_key('ips_subnet_id_fkey', 'ips', 'subnets', ['subnet_id'], ['id'],
                          ondelete='CASCADE')
    op.drop_index('idx_ip_address', table_name='ips')
    op.create_index('idx_ip_mac', 'ips', ['mac_address'])

    op.create_table(
        'dhcp_ranges',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('subnet_id', sa.Integer(), sa.ForeignKey('subnets.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('start_address', sa.String(45), nullable=False),
        sa.Column('end_address', sa.String(45), nullable=False),
        sa.Column('description', sa.String(255)),
    )
    op.create_index('ix_dhcp_ranges_subnet_id', 'dhcp_ranges', ['subnet_id'])

    op.create_table(
        'discoveries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('subnet_id', sa.Integer(), sa.ForeignKey('subnets.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('address', sa.String(45), nullable=False),
        sa.Column('mac_address', sa.String(17)),
        sa.Column('hostname', sa.String(255)),
        sa.Column('vendor', sa.String(100)),
        sa.Column('source', sa.String(20), nullable=False, server_default='scan'),
        sa.Column('ignored', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('first_seen', sa.DateTime(), nullable=False),
        sa.Column('last_seen', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('subnet_id', 'address', name='unique_discovery_per_subnet'),
    )

    # Older versions stored CIDRs and IPv6 addresses as typed
    conn = op.get_bind()
    _normalize(conn, 'subnets', 'cidr', lambda v: str(ipaddress.ip_network(v, strict=False)))
    _normalize(conn, 'ips', 'address', lambda v: str(ipaddress.ip_address(v)), scope='subnet_id')
    op.execute("UPDATE ips SET mac_address = UPPER(mac_address) WHERE mac_address IS NOT NULL")


def downgrade():
    op.drop_table('discoveries')
    op.drop_index('ix_dhcp_ranges_subnet_id', table_name='dhcp_ranges')
    op.drop_table('dhcp_ranges')
    op.drop_index('idx_ip_mac', table_name='ips')
    op.create_index('idx_ip_address', 'ips', ['address'])
    op.drop_constraint('ips_subnet_id_fkey', 'ips', type_='foreignkey')
    op.create_foreign_key('ips_subnet_id_fkey', 'ips', 'subnets', ['subnet_id'], ['id'])
    op.create_index('idx_subnet_cidr', 'subnets', ['cidr'])
    op.drop_column('subnets', 'last_scan_at')
    op.drop_column('subnets', 'scan_enabled')
    op.create_index('ix_users_email', 'users', ['email'])
    op.create_index('ix_users_username', 'users', ['username'])
    op.add_column('users', sa.Column('is_admin', sa.Boolean(), server_default=sa.false()))
    op.execute("UPDATE users SET is_admin = (role = 'admin')")
    op.drop_column('users', 'session_version')
    op.drop_column('users', 'role')
