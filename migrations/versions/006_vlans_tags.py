"""VLANs and tags as their own tables

Expand, migrate, contract in one step (app and database upgrade together):
subnets.vlan (a number) becomes a link to a vlans row, subnets.tags (text,
comma-separated) becomes rows in tags + subnet_tags. Addresses gain tags.

Revision ID: 006_vlans_tags
Revises: 005_history
Create Date: 2026-10-15
"""
import sqlalchemy as sa
from alembic import op

revision = '006_vlans_tags'
down_revision = '005_history'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'vlans',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('vid', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('site', sa.String(100), nullable=False, server_default=''),
        sa.Column('description', sa.Text()),
        sa.Column('created_at', sa.DateTime()),
        sa.UniqueConstraint('vid', 'site', name='unique_vlan_per_site'),
    )
    op.create_table(
        'tags',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(50), nullable=False),
    )
    op.execute('CREATE UNIQUE INDEX unique_tag_name ON tags (lower(name))')
    op.create_table(
        'subnet_tags',
        sa.Column('subnet_id', sa.Integer(), sa.ForeignKey('subnets.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('tag_id', sa.Integer(), sa.ForeignKey('tags.id', ondelete='CASCADE'), primary_key=True),
    )
    op.create_table(
        'ip_tags',
        sa.Column('ip_id', sa.Integer(), sa.ForeignKey('ips.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('tag_id', sa.Integer(), sa.ForeignKey('tags.id', ondelete='CASCADE'), primary_key=True),
    )
    op.add_column('subnets', sa.Column('vlan_id', sa.Integer(), sa.ForeignKey('vlans.id', ondelete='SET NULL')))
    op.create_index('ix_subnets_vlan_id', 'subnets', ['vlan_id'])

    conn = op.get_bind()
    # VLAN numbers -> vlans rows
    conn.execute(sa.text(
        "INSERT INTO vlans (vid, name, site, created_at) "
        "SELECT DISTINCT vlan, 'VLAN ' || vlan, '', now() FROM subnets WHERE vlan BETWEEN 1 AND 4094"))
    conn.execute(sa.text(
        "UPDATE subnets s SET vlan_id = v.id FROM vlans v WHERE v.vid = s.vlan AND v.site = ''"))
    # Comma-separated tags -> tags and subnet_tags
    rows = conn.execute(sa.text("SELECT id, tags FROM subnets WHERE coalesce(tags, '') <> ''")).fetchall()
    ids = {}
    for subnet_id, text in rows:
        for name in {t.strip()[:50] for t in text.split(',') if t.strip()}:
            key = name.lower()
            if key not in ids:
                ids[key] = conn.execute(sa.text('INSERT INTO tags (name) VALUES (:n) RETURNING id'), {'n': name}).scalar()
            conn.execute(sa.text('INSERT INTO subnet_tags (subnet_id, tag_id) VALUES (:s, :t) ON CONFLICT DO NOTHING'),
                         {'s': subnet_id, 't': ids[key]})

    op.drop_index('idx_subnet_vlan', table_name='subnets')
    op.drop_column('subnets', 'vlan')
    op.drop_column('subnets', 'tags')


def downgrade():
    op.add_column('subnets', sa.Column('vlan', sa.Integer()))
    op.add_column('subnets', sa.Column('tags', sa.Text()))
    op.create_index('idx_subnet_vlan', 'subnets', ['vlan'])
    conn = op.get_bind()
    conn.execute(sa.text('UPDATE subnets s SET vlan = v.vid FROM vlans v WHERE v.id = s.vlan_id'))
    conn.execute(sa.text(
        "UPDATE subnets s SET tags = x.names FROM ("
        "SELECT st.subnet_id, string_agg(t.name, ',' ORDER BY lower(t.name)) AS names "
        "FROM subnet_tags st JOIN tags t ON t.id = st.tag_id GROUP BY st.subnet_id) x "
        "WHERE x.subnet_id = s.id"))
    op.drop_index('ix_subnets_vlan_id', table_name='subnets')
    op.drop_column('subnets', 'vlan_id')
    op.drop_table('ip_tags')
    op.drop_table('subnet_tags')
    op.drop_table('tags')
    op.drop_table('vlans')
