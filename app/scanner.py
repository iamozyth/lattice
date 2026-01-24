"""Network scanning and discovery module for IPAM"""
import subprocess
import socket
import logging
import ipaddress
from datetime import datetime
from app import db
from app.models import Subnet, IP

logger = logging.getLogger(__name__)


class NetworkScanner:
    """Performs network scans and discovers live hosts"""
    
    def __init__(self):
        self._nmap_available = self._check_nmap()
    
    def _check_nmap(self):
        """Check if nmap is installed and available"""
        try:
            result = subprocess.run(['nmap', '--version'], capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    def is_available(self):
        """Check if nmap is available"""
        return self._nmap_available
    
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
                cmd = ['nmap', '-sn', subnet_cidr]
            else:
                # More detailed scan with OS and service detection
                cmd = ['nmap', '-sV', '-O', '--script', 'smb-os-discovery', subnet_cidr]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            
            if result.returncode not in [0, 1]:  # 1 is normal for nmap (some hosts down)
                return {'error': f'Nmap scan failed: {result.stderr}', 'discovered': []}
            
            discovered = self._parse_nmap_output(result.stdout)
            
            logger.info(f"Scan complete. Found {len(discovered)} live hosts in {subnet_cidr}")
            return {
                'subnet': subnet_cidr,
                'scan_type': scan_type,
                'timestamp': datetime.utcnow().isoformat(),
                'total_discovered': len(discovered),
                'discovered': discovered
            }
        
        except subprocess.TimeoutExpired:
            return {'error': 'Scan timeout (>10 minutes)', 'discovered': []}
        except Exception as e:
            logger.error(f"Scan error for {subnet_cidr}: {str(e)}")
            return {'error': str(e), 'subnet': subnet_cidr, 'discovered': []}
    
    def _parse_nmap_output(self, output):
        """Parse nmap output to extract discovered hosts"""
        discovered = []
        lines = output.split('\n')
        
        for line in lines:
            line = line.strip()
            # Look for "Nmap scan report for" lines indicating a live host
            if line.startswith('Nmap scan report for'):
                parts = line.split()
                if len(parts) >= 5:
                    host_info = parts[-1].strip('()')
                    # Extract IP (last part, typically in parentheses or plain)
                    try:
                        # Try to parse as IP
                        ip_str = host_info
                        # Basic IP validation
                        if self._is_valid_ip(ip_str):
                            info = {
                                'address': ip_str,
                                'status': 'discovered',
                                'hostname': None,
                                'mac_address': None,
                                'manufacturer': None,
                                'os_info': None,
                                'open_ports': []
                            }
                            
                            # Try reverse DNS lookup
                            try:
                                info['hostname'] = socket.gethostbyaddr(ip_str)[0]
                            except (socket.herror, socket.gaierror):
                                pass
                            
                            discovered.append(info)
                    except:
                        pass
        
        return discovered
    
    def _is_valid_ip(self, ip_str):
        """Check if string is a valid IP address"""
        try:
            ipaddress.ip_address(ip_str)
            return True
        except:
            return False
    
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
            
            confidence = 0.8  # Higher base confidence since host responded to ping
            device_type = 'Unknown Device'
            
            # Increase confidence based on enriched data
            if host.get('hostname'):
                confidence = min(1.0, confidence + 0.15)
                device_type = host.get('hostname')
            
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
            cmd = ['nmap', '-sn', ip_address]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            is_live = 'up' in result.stdout.lower() and result.returncode in [0, 1]
            
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
        
        except subprocess.TimeoutExpired:
            return {'error': 'Verification timeout', 'address': ip_address, 'verified': False}
        except Exception as e:
            logger.error(f"Verification error for {ip_address}: {str(e)}")
            return {'error': str(e), 'address': ip_address, 'verified': False}

