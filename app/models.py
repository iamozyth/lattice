import ipaddress
from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app import db, login_manager

# IP statuses that count towards a subnet's utilization
USED_STATUSES = ('in-use', 'reserved', 'dhcp', 'blocked')
IP_STATUSES = ('available', 'in-use', 'reserved', 'blocked', 'dhcp', 'deprecated')
ROLES = ('viewer', 'editor', 'admin')

# Largest count we send to the browser; JS numbers lose precision above 2**53
MAX_JS_INT = 2**53 - 1


def ip_sort_key(ip_str):
    """Sort key for addresses that works across IPv4 and IPv6."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return (ip.version, int(ip))
    except ValueError:
        return (99, 0)


def _iso(value):
    return value.isoformat() if value else None


class Connector(db.Model):
    __tablename__ = 'connectors'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    config_encrypted = db.Column(db.LargeBinary, nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    last_sync_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.Index('idx_connector_type', 'type'),
        db.Index('idx_connector_enabled', 'enabled'),
    )

    def to_dict(self, details=None):
        return {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'enabled': self.enabled,
            'last_sync_at': _iso(self.last_sync_at),
            'created_at': _iso(self.created_at),
            'updated_at': _iso(self.updated_at),
            'details': details or {},
        }


subnet_tags = db.Table(
    'subnet_tags',
    db.Column('subnet_id', db.Integer, db.ForeignKey('subnets.id', ondelete='CASCADE'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tags.id', ondelete='CASCADE'), primary_key=True),
)
ip_tags = db.Table(
    'ip_tags',
    db.Column('ip_id', db.Integer, db.ForeignKey('ips.id', ondelete='CASCADE'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tags.id', ondelete='CASCADE'), primary_key=True),
)


def _tag_names(tags):
    return sorted((t.name for t in tags), key=str.lower)


class Vlan(db.Model):
    __tablename__ = 'vlans'

    id = db.Column(db.Integer, primary_key=True)
    vid = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    site = db.Column(db.String(100), nullable=False, default='', server_default='')
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('vid', 'site', name='unique_vlan_per_site'),)

    def __str__(self):
        return f'VLAN {self.vid} {self.name}'

    def to_dict(self):
        return {'id': self.id, 'vid': self.vid, 'name': self.name, 'site': self.site,
                'description': self.description}


class Tag(db.Model):
    __tablename__ = 'tags'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)

    __table_args__ = (db.Index('unique_tag_name', db.func.lower(name), unique=True),)

    def __str__(self):
        return self.name


class Subnet(db.Model):
    __tablename__ = 'subnets'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True)
    cidr = db.Column(db.String(43), nullable=False, unique=True)
    description = db.Column(db.Text)
    vlan_id = db.Column(db.Integer, db.ForeignKey('vlans.id', ondelete='SET NULL'), index=True)
    gateway = db.Column(db.String(45))
    dns_primary = db.Column(db.String(45))
    dns_secondary = db.Column(db.String(45))
    location = db.Column(db.String(255))
    environment = db.Column(db.String(50))
    scan_enabled = db.Column(db.Boolean)  # None = automatic (small IPv4 subnets only)
    last_scan_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    ips = db.relationship('IP', backref='subnet', lazy=True, cascade='all, delete-orphan',
                          passive_deletes=True)
    dhcp_ranges = db.relationship('DhcpRange', backref='subnet', lazy=True,
                                  cascade='all, delete-orphan', passive_deletes=True,
                                  order_by='DhcpRange.id')
    vlan_obj = db.relationship('Vlan', backref=db.backref('subnets', lazy=True), lazy='joined')
    tags = db.relationship('Tag', secondary=subnet_tags, lazy='selectin', backref=db.backref('subnets', lazy=True))
    TRACKED_RELATIONS = ('tags',)

    __table_args__ = (
        db.Index('idx_subnet_environment', 'environment'),
    )

    @property
    def network(self):
        return ipaddress.ip_network(self.cidr, strict=False)

    def contains(self, address):
        try:
            return ipaddress.ip_address(address) in self.network
        except ValueError:
            return False

    @property
    def usable_count(self):
        net = self.network
        if net.version == 4 and net.prefixlen < 31:
            return net.num_addresses - 2
        return net.num_addresses

    @property
    def auto_scan(self):
        """Whether the scheduler should ping-scan the whole subnet."""
        if self.scan_enabled is not None:
            return self.scan_enabled
        net = self.network
        return net.version == 4 and net.prefixlen >= 20

    def reserved_addresses(self):
        """Addresses next-free must never hand out: network, broadcast and gateway."""
        net = self.network
        reserved = set()
        if net.version == 4 and net.prefixlen < 31:
            reserved.update({net.network_address, net.broadcast_address})
        if net.version == 6 and net.prefixlen < 127:
            reserved.add(net.network_address)  # subnet-router anycast
        if self.gateway:
            try:
                reserved.add(ipaddress.ip_address(self.gateway))
            except ValueError:
                pass
        return reserved

    def in_dhcp_range(self, address):
        addr = ipaddress.ip_address(address)
        return any(r.contains(addr) for r in self.dhcp_ranges)

    def free_addresses(self, used, limit=50, max_checks=65536):
        """Yield up to `limit` free addresses without materialising the network."""
        reserved = self.reserved_addresses()
        ranges = [(r.start_int, r.end_int) for r in self.dhcp_ranges]
        found = []
        net = self.network
        address_cls = type(net.network_address)
        first, last = int(net.network_address), int(net.broadcast_address)
        for n, value in enumerate(range(first, last + 1)):
            if n >= max_checks or len(found) >= limit:
                break
            addr = address_cls(value)
            if addr in reserved or str(addr) in used:
                continue
            if any(lo <= value <= hi for lo, hi in ranges):
                continue
            found.append(str(addr))
        return found

    def to_dict(self, used_count=None, ip_count=None):
        net = self.network
        usable = self.usable_count
        if used_count is None:
            used_count = sum(1 for ip in self.ips if ip.status in USED_STATUSES)
        if ip_count is None:
            ip_count = len(self.ips)
        return {
            'id': self.id,
            'name': self.name,
            'cidr': self.cidr,
            'version': net.version,
            'description': self.description,
            'vlan': self.vlan_obj.vid if self.vlan_obj else None,
            'vlan_id': self.vlan_id,
            'vlan_name': self.vlan_obj.name if self.vlan_obj else None,
            'gateway': self.gateway,
            'dns_primary': self.dns_primary,
            'dns_secondary': self.dns_secondary,
            'location': self.location,
            'environment': self.environment,
            'tags': _tag_names(self.tags),
            'first_ip': str(net.network_address),
            'last_ip': str(net.broadcast_address),
            'netmask': str(net.netmask),
            'prefix_length': net.prefixlen,
            'usable_ips': min(usable, MAX_JS_INT),
            'ip_count': ip_count,
            'used_ips': used_count,
            'free_ips': min(max(usable - used_count, 0), MAX_JS_INT),
            'utilization': round(used_count / usable * 100, 1) if usable else 0,
            'scan_enabled': self.scan_enabled,
            'auto_scan': self.auto_scan,
            'last_scan_at': _iso(self.last_scan_at),
            'dhcp_ranges': [r.to_dict() for r in self.dhcp_ranges],
            'created_at': _iso(self.created_at),
            'updated_at': _iso(self.updated_at),
        }


class DhcpRange(db.Model):
    __tablename__ = 'dhcp_ranges'

    id = db.Column(db.Integer, primary_key=True)
    subnet_id = db.Column(db.Integer, db.ForeignKey('subnets.id', ondelete='CASCADE'),
                          nullable=False, index=True)
    start_address = db.Column(db.String(45), nullable=False)
    end_address = db.Column(db.String(45), nullable=False)
    description = db.Column(db.String(255))

    @property
    def start_int(self):
        return int(ipaddress.ip_address(self.start_address))

    @property
    def end_int(self):
        return int(ipaddress.ip_address(self.end_address))

    @property
    def size(self):
        return self.end_int - self.start_int + 1

    def contains(self, addr):
        return self.start_int <= int(addr) <= self.end_int

    def to_dict(self):
        return {
            'id': self.id,
            'subnet_id': self.subnet_id,
            'start': self.start_address,
            'end': self.end_address,
            'size': min(self.size, MAX_JS_INT),
            'description': self.description,
        }


class IP(db.Model):
    __tablename__ = 'ips'

    id = db.Column(db.Integer, primary_key=True)
    address = db.Column(db.String(45), nullable=False)
    hostname = db.Column(db.String(255))
    fqdn = db.Column(db.String(255))
    description = db.Column(db.Text)
    subnet_id = db.Column(db.Integer, db.ForeignKey('subnets.id', ondelete='CASCADE'), nullable=False)
    status = db.Column(db.String(20), default='available')
    mac_address = db.Column(db.String(17))
    device_type = db.Column(db.String(100))
    manufacturer = db.Column(db.String(100))
    model = db.Column(db.String(100))
    serial_number = db.Column(db.String(100))
    owner = db.Column(db.String(255))
    department = db.Column(db.String(255))
    notes = db.Column(db.Text)
    last_seen = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tags = db.relationship('Tag', secondary=ip_tags, lazy='selectin', backref=db.backref('ips', lazy=True))
    TRACKED_RELATIONS = ('tags',)

    # Fields a client may set; everything else is managed by the server
    FIELDS = ('address', 'hostname', 'fqdn', 'description', 'status', 'mac_address',
              'device_type', 'manufacturer', 'model', 'serial_number', 'owner',
              'department', 'notes')

    __table_args__ = (
        db.UniqueConstraint('address', 'subnet_id', name='unique_ip_per_subnet'),
        db.Index('idx_ip_status', 'status'),
        db.Index('idx_ip_hostname', 'hostname'),
        db.Index('idx_ip_mac', 'mac_address'),
    )

    def to_dict(self):
        data = {field: getattr(self, field) for field in self.FIELDS}
        data.update({
            'id': self.id,
            'subnet_id': self.subnet_id,
            'subnet_name': self.subnet.name if self.subnet else None,
            'subnet_cidr': self.subnet.cidr if self.subnet else None,
            'last_seen': _iso(self.last_seen),
            'created_at': _iso(self.created_at),
            'updated_at': _iso(self.updated_at),
            'tags': _tag_names(self.tags),
        })
        return data


class Discovery(db.Model):
    """A host seen on the network by a scan or connector, documented or not."""
    __tablename__ = 'discoveries'

    id = db.Column(db.Integer, primary_key=True)
    subnet_id = db.Column(db.Integer, db.ForeignKey('subnets.id', ondelete='CASCADE'), nullable=False)
    address = db.Column(db.String(45), nullable=False)
    mac_address = db.Column(db.String(17))
    hostname = db.Column(db.String(255))
    vendor = db.Column(db.String(100))
    source = db.Column(db.String(20), nullable=False, default='scan')
    ignored = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    first_seen = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    subnet = db.relationship('Subnet')

    __table_args__ = (
        db.UniqueConstraint('subnet_id', 'address', name='unique_discovery_per_subnet'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'subnet_id': self.subnet_id,
            'subnet_name': self.subnet.name if self.subnet else None,
            'subnet_cidr': self.subnet.cidr if self.subnet else None,
            'address': self.address,
            'mac_address': self.mac_address,
            'hostname': self.hostname,
            'vendor': self.vendor,
            'source': self.source,
            'ignored': self.ignored,
            'first_seen': _iso(self.first_seen),
            'last_seen': _iso(self.last_seen),
        }


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(10), nullable=False, default='editor', server_default='editor')
    is_active = db.Column(db.Boolean, default=True)
    # Set for accounts created by single sign-on: the provider's stable user ID
    sso_subject = db.Column(db.String(255), unique=True)
    session_version = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def set_password(self, password):
        if len(password) < 8:
            raise ValueError('Password must be at least 8 characters')
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def has_role(self, role):
        return ROLES.index(self.role) >= ROLES.index(role)

    @property
    def is_admin(self):
        return self.role == 'admin'

    def get_id(self):
        # Bumping session_version logs out every session and remember cookie
        return f'{self.id}:{self.session_version}'

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'role': self.role,
            'is_active': self.is_active,
            'source': 'sso' if self.sso_subject else 'local',
            'created_at': _iso(self.created_at),
        }


class Change(db.Model):
    """One recorded change: who did what to which object, with before/after values."""
    __tablename__ = 'changes'

    id = db.Column(db.Integer, primary_key=True)
    at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    user_id = db.Column(db.Integer)
    username = db.Column(db.String(80), nullable=False)
    via = db.Column(db.String(10), nullable=False)
    action = db.Column(db.String(10), nullable=False)
    entity = db.Column(db.String(20), nullable=False)
    entity_id = db.Column(db.Integer)
    label = db.Column(db.String(255))
    subnet_id = db.Column(db.Integer, index=True)
    diff = db.Column(db.JSON, nullable=False, default=dict)

    __table_args__ = (db.Index('idx_change_entity', 'entity', 'entity_id'),)

    def to_dict(self):
        return {'id': self.id, 'at': _iso(self.at), 'user_id': self.user_id, 'username': self.username,
                'via': self.via, 'action': self.action, 'entity': self.entity, 'entity_id': self.entity_id,
                'label': self.label, 'subnet_id': self.subnet_id, 'diff': self.diff}


class Setting(db.Model):
    """Small JSON settings saved from the UI, e.g. single sign-on."""
    __tablename__ = 'settings'

    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    try:
        uid, version = (int(part) for part in user_id.split(':'))
    except ValueError:
        return None
    user = db.session.get(User, uid)
    if not user or not user.is_active or user.session_version != version:
        return None
    return user
