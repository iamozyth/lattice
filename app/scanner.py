"""Network scanning and discovery module for IPAM"""
import nmap
import socket
import logging
from datetime import datetime
from app import db
from app.models import Subnet, IP

logger = logging.getLogger(__name__)


class NetworkScanner:
    """Performs network scans and discovers live hosts"""
    
    def __init__(self):
        try:
            self.nm = nmap.PortScanner()
        except nmap.PortScannerError as e:
            logger.error(f"Nmap not available: {e}")
            self.nm = None
    
    def is_available(self):
        """Check if nmap is available"""
        return self.nm is not None
    
    def scan_subnet(self, subnet_cidr, scan_type='ping'):
        """
        Scan a subnet for live hosts
        
        Args:
            subnet_cidr: CIDR notation (e.g., '192.168.1.0/24')
            scan_type: 'ping' for fast discovery, 'full' for detailed scan
        
        Returns:
            dict with scan results and discovered hosts
        """
        if not self.is_available():
            return {'error': 'Nmap is not available', 'discovered': []}
        
        try:
            logger.info(f"Starting {scan_type} scan on {subnet_cidr}")
            
            if scan_type == 'ping':
                # Fast ping scan to discover live hosts
                arguments = '-sn'  # Ping scan, no port scan
            else:
                # More detailed scan with OS and service detection
                arguments = '-sV -O --script smb-os-discovery'
            
            self.nm.scan(hosts=subnet_cidr, arguments=arguments, timeout=300)
            
            discovered = []
            for host in self.nm.all_hosts():
                if self.nm[host].state()['state'] == 'up':
                    host_info = self._extract_host_info(host)
                    discovered.append(host_info)
            
            logger.info(f"Scan complete. Found {len(discovered)} live hosts in {subnet_cidr}")
            return {
                'subnet': subnet_cidr,
                'scan_type': scan_type,
                'timestamp': datetime.utcnow().isoformat(),
                'total_discovered': len(discovered),
                'discovered': discovered
            }
        
        except Exception as e:
            logger.error(f"Scan error for {subnet_cidr}: {str(e)}")
            return {
                'error': str(e),
                'subnet': subnet_cidr,
                'discovered': []
            }
    
    def _extract_host_info(self, host):
        """Extract enriched information about a discovered host"""
        info = {
            'address': host,
            'status': 'discovered',
            'hostname': None,
            'mac_address': None,
            'manufacturer': None,
            'os_info': None,
            'open_ports': []
        }
        
        # Attempt reverse DNS lookup
        try:
            info['hostname'] = socket.gethostbyaddr(host)[0]
        except (socket.herror, socket.gaierror):
            pass
        
        # Extract MAC address if available
        if 'mac' in self.nm[host]['addresses']:
            info['mac_address'] = self.nm[host]['addresses']['mac']
        
        # Try to get vendor/manufacturer info
        if 'osmatch' in self.nm[host]:
            matches = self.nm[host]['osmatch']
            if matches:
                info['os_info'] = matches[0]['name']
        
        # Extract open ports
        try:
            for proto in self.nm[host].all_protocols():
                ports = self.nm[host][proto].keys()
                for port in ports:
                    state = self.nm[host][proto][port]['state']
                    if state == 'open':
                        info['open_ports'].append({
                            'port': port,
                            'protocol': proto,
                            'service': self.nm[host][proto][port].get('name', 'unknown')
                        })
        except:
            pass
        
        return info
    
    def recommend_ips_for_subnet(self, subnet_id, discovered_hosts):
        """
        Recommend IPs to add to inventory based on discovered hosts
        
        Args:
            subnet_id: Database subnet ID
            discovered_hosts: List of discovered host dictionaries
        
        Returns:
            List of recommendations with confidence levels
        """
        subnet = Subnet.query.get(subnet_id)
        if not subnet:
            return []
        
        existing_ips = {ip.address for ip in subnet.ips}
        recommendations = []
        
        for host in discovered_hosts:
            ip = host['address']
            
            # Skip if already in inventory
            if ip in existing_ips:
                continue
            
            # Skip network and broadcast addresses
            if not subnet.contains_ip(ip):
                continue
            
            confidence = 0.5  # Base confidence
            device_type = 'unknown'
            
            # Increase confidence based on enriched data
            if host.get('hostname'):
                confidence = min(1.0, confidence + 0.2)
            
            if host.get('mac_address'):
                confidence = min(1.0, confidence + 0.15)
                device_type = self._infer_device_type(host.get('mac_address'), host.get('os_info'))
            
            if host.get('os_info'):
                confidence = min(1.0, confidence + 0.15)
            
            # Penalize for too many open ports (might be a false positive)
            if len(host.get('open_ports', [])) > 20:
                confidence *= 0.8
            
            recommendations.append({
                'address': ip,
                'hostname': host.get('hostname'),
                'mac_address': host.get('mac_address'),
                'device_type': device_type,
                'os_info': host.get('os_info'),
                'open_ports': host.get('open_ports', []),
                'confidence': round(confidence, 2),
                'suggested_status': 'in-use'
            })
        
        # Sort by confidence
        recommendations.sort(key=lambda x: x['confidence'], reverse=True)
        return recommendations
    
    def _infer_device_type(self, mac_address, os_info):
        """Infer device type from MAC address vendor and OS info"""
        # Common MAC address prefixes (first 3 octets)
        mac_prefixes = {
            '00:1A:2B': 'Router',
            '00:1C:23': 'Network Device',
            '00:50:F2': 'Microsoft',
            '08:00:27': 'VirtualBox',
            '00:0C:29': 'VMware',
            '52:54:00': 'KVM/QEMU',
        }
        
        prefix = mac_address[:8].upper() if mac_address else ''
        
        for mac_prefix, device_type in mac_prefixes.items():
            if prefix.startswith(mac_prefix):
                return device_type
        
        # Infer from OS info
        if os_info:
            os_lower = os_info.lower()
            if 'printer' in os_lower:
                return 'Printer'
            elif 'router' in os_lower or 'firewall' in os_lower:
                return 'Router'
            elif 'switch' in os_lower:
                return 'Switch'
            elif 'linux' in os_lower:
                return 'Server'
            elif 'windows' in os_lower:
                return 'Workstation'
            elif 'mac' in os_lower:
                return 'Workstation'
        
        return 'Unknown Device'
    
    def verify_ip_status(self, ip_address, subnet_id):
        """
        Verify if an IP is currently live/responsive
        
        Args:
            ip_address: IP address to verify
            subnet_id: Associated subnet ID
        
        Returns:
            dict with verification result
        """
        if not self.is_available():
            return {'error': 'Nmap not available', 'verified': False}
        
        try:
            self.nm.scan(hosts=ip_address, arguments='-sn', timeout=10)
            
            is_live = self.nm[ip_address].state()['state'] == 'up'
            
            # Update last_seen if live
            if is_live:
                ip_obj = IP.query.filter_by(address=ip_address, subnet_id=subnet_id).first()
                if ip_obj:
                    ip_obj.last_seen = datetime.utcnow()
                    db.session.commit()
            
            return {
                'address': ip_address,
                'is_live': is_live,
                'verified_at': datetime.utcnow().isoformat()
            }
        
        except Exception as e:
            logger.error(f"Verification error for {ip_address}: {str(e)}")
            return {'error': str(e), 'address': ip_address, 'verified': False}
