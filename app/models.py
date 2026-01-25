from app import db, login_manager
from datetime import datetime
import ipaddress
import re
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from sqlalchemy import LargeBinary

class Connector(db.Model):
    __tablename__ = 'connectors'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # e.g., 'unifi'
    config_encrypted = db.Column(LargeBinary, nullable=False)
    enabled = db.Column(db.Boolean, default=True)
    last_sync_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.Index('idx_connector_type', 'type'),
        db.Index('idx_connector_enabled', 'enabled'),
    )

    def to_dict(self, include_details: bool = False, details: dict | None = None):
        """Serialize without exposing secrets. Optionally include safe details."""
        data = {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'enabled': self.enabled,
            'last_sync_at': self.last_sync_at.isoformat() if self.last_sync_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_details and details:
            data['details'] = details
        return data


class Subnet(db.Model):
    __tablename__ = 'subnets'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True)
    cidr = db.Column(db.String(43), nullable=False, unique=True)  # Support IPv6
    description = db.Column(db.Text)
    vlan = db.Column(db.Integer)
    gateway = db.Column(db.String(45))  # Support IPv6
    dns_primary = db.Column(db.String(45))
    dns_secondary = db.Column(db.String(45))
    location = db.Column(db.String(255))  # Physical/logical location
    environment = db.Column(db.String(50))  # prod, dev, staging, etc.
    tags = db.Column(db.Text)  # Comma-separated tags
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    ips = db.relationship('IP', backref='subnet', lazy=True, cascade='all, delete-orphan')
    
    __table_args__ = (
        db.Index('idx_subnet_cidr', 'cidr'),
        db.Index('idx_subnet_vlan', 'vlan'),
        db.Index('idx_subnet_environment', 'environment'),
    )
    
    @staticmethod
    def validate_cidr(cidr_str):
        """Validate CIDR notation and return network object or raise ValueError"""
        try:
            network = ipaddress.ip_network(cidr_str, strict=False)
            return network
        except ValueError as e:
            raise ValueError(f"Invalid CIDR notation: {str(e)}")
    
    @staticmethod
    def validate_ip(ip_str):
        """Validate an IP address"""
        try:
            return ipaddress.ip_address(ip_str)
        except ValueError as e:
            raise ValueError(f"Invalid IP address: {str(e)}")
    
    def get_network(self):
        """Get the ipaddress network object for this subnet"""
        try:
            return ipaddress.ip_network(self.cidr, strict=False)
        except:
            return None
    
    def contains_ip(self, ip_str):
        """Check if an IP address is within this subnet"""
        try:
            network = self.get_network()
            ip = ipaddress.ip_address(ip_str)
            return ip in network
        except:
            return False
    
    def get_available_ips(self, limit=100):
        """Get a list of available IPs in the subnet (excluding used ones)"""
        network = self.get_network()
        if not network:
            return []
        
        used_ips = {ip.address for ip in self.ips}
        available = []
        
        # Skip network and broadcast for IPv4 /31 and larger
        hosts = list(network.hosts()) if network.prefixlen < 31 else list(network)
        
        for ip in hosts:
            if str(ip) not in used_ips:
                available.append(str(ip))
                if len(available) >= limit:
                    break
        
        return available
    
    def get_next_available_ip(self):
        """Get the next available IP in the subnet"""
        available = self.get_available_ips(limit=1)
        return available[0] if available else None
    
    def to_dict(self, include_ips=False):
        network = self.get_network()
        
        if network:
            if isinstance(network, ipaddress.IPv4Network):
                first_ip = str(network.network_address)
                last_ip = str(network.broadcast_address)
                # For /31 and /32, all addresses are usable
                if network.prefixlen >= 31:
                    usable_ips = network.num_addresses
                else:
                    usable_ips = network.num_addresses - 2
            else:
                first_ip = str(network.network_address)
                last_ip = str(network.broadcast_address)
                usable_ips = min(network.num_addresses, 2**32)  # Cap display for large IPv6
            prefix_length = network.prefixlen
            netmask = str(network.netmask)
        else:
            first_ip = None
            last_ip = None
            usable_ips = 0
            prefix_length = None
            netmask = None
        
        used_ips = len(self.ips)
        utilization = round((used_ips / usable_ips * 100), 1) if usable_ips > 0 else 0
        
        result = {
            'id': self.id,
            'name': self.name,
            'cidr': self.cidr,
            'description': self.description,
            'vlan': self.vlan,
            'gateway': self.gateway,
            'dns_primary': self.dns_primary,
            'dns_secondary': self.dns_secondary,
            'location': self.location,
            'environment': self.environment,
            'tags': self.tags.split(',') if self.tags else [],
            'first_ip': first_ip,
            'last_ip': last_ip,
            'netmask': netmask,
            'prefix_length': prefix_length,
            'usable_ips': usable_ips,
            'used_ips': used_ips,
            'available_ips': usable_ips - used_ips,
            'utilization': utilization,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
        
        if include_ips:
            result['ips'] = sorted(
                [ip.to_dict() for ip in self.ips],
                key=lambda x: ip_sort_key(x['address'])
            )
        
        return result


class IP(db.Model):
    __tablename__ = 'ips'
    
    id = db.Column(db.Integer, primary_key=True)
    address = db.Column(db.String(45), nullable=False)  # Support IPv6
    hostname = db.Column(db.String(255))
    fqdn = db.Column(db.String(255))  # Fully qualified domain name
    description = db.Column(db.Text)
    subnet_id = db.Column(db.Integer, db.ForeignKey('subnets.id'), nullable=False)
    status = db.Column(db.String(20), default='available')
    mac_address = db.Column(db.String(17))
    device_type = db.Column(db.String(100))
    manufacturer = db.Column(db.String(100))
    model = db.Column(db.String(100))
    serial_number = db.Column(db.String(100))
    owner = db.Column(db.String(255))
    department = db.Column(db.String(255))
    notes = db.Column(db.Text)
    last_seen = db.Column(db.DateTime)  # For future ping/scan feature
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Status options
    STATUSES = ['available', 'in-use', 'reserved', 'blocked', 'dhcp', 'deprecated']
    
    __table_args__ = (
        db.UniqueConstraint('address', 'subnet_id', name='unique_ip_per_subnet'),
        db.Index('idx_ip_address', 'address'),
        db.Index('idx_ip_status', 'status'),
        db.Index('idx_ip_hostname', 'hostname'),
    )
    
    @staticmethod
    def validate_mac(mac_str):
        """Validate MAC address format"""
        if not mac_str:
            return None
        
        # Normalize MAC address
        mac_clean = mac_str.upper().replace('-', ':').replace('.', ':')
        
        # Check various formats
        patterns = [
            r'^([0-9A-F]{2}:){5}[0-9A-F]{2}$',  # 00:11:22:33:44:55
            r'^([0-9A-F]{2}-){5}[0-9A-F]{2}$',  # 00-11-22-33-44-55
            r'^([0-9A-F]{4}\.){2}[0-9A-F]{4}$',  # 0011.2233.4455
        ]
        
        # Try standard format
        if re.match(r'^([0-9A-F]{2}:){5}[0-9A-F]{2}$', mac_clean):
            return mac_clean
        
        # Try to parse and reformat
        mac_digits = re.sub(r'[^0-9A-F]', '', mac_clean)
        if len(mac_digits) == 12:
            return ':'.join(mac_digits[i:i+2] for i in range(0, 12, 2))
        
        raise ValueError("Invalid MAC address format")
    
    def to_dict(self):
        return {
            'id': self.id,
            'address': self.address,
            'hostname': self.hostname,
            'fqdn': self.fqdn,
            'description': self.description,
            'subnet_id': self.subnet_id,
            'subnet_name': self.subnet.name if self.subnet else None,
            'subnet_cidr': self.subnet.cidr if self.subnet else None,
            'status': self.status,
            'mac_address': self.mac_address,
            'device_type': self.device_type,
            'manufacturer': self.manufacturer,
            'model': self.model,
            'serial_number': self.serial_number,
            'owner': self.owner,
            'department': self.department,
            'notes': self.notes,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


def ip_sort_key(ip_str):
    """Generate a sortable key for IP addresses (works for IPv4 and IPv6)"""
    try:
        ip = ipaddress.ip_address(ip_str)
        return (ip.version, int(ip))
    except:
        return (999, 0)  # Invalid IPs sort last


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def set_password(self, password):
        """Hash and set the password"""
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters long")
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Check if the provided password matches the hash"""
        return check_password_hash(self.password_hash, password)
    
    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'is_admin': self.is_admin,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
