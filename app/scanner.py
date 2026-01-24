"""Network scanning and discovery module for IPAM"""
import subprocess
import socket
import logging
import ipaddress
import threading
import uuid
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


class ScanJobManager:
    """Manages asynchronous scan jobs with live logs and incremental results"""

    def __init__(self):
        self._jobs = {}
        self._lock = threading.Lock()

    @staticmethod
    def _is_valid_ip(ip_str):
        try:
            ipaddress.ip_address(ip_str)
            return True
        except Exception:
            return False

    def start_scan(self, subnet_cidr, scan_type='ping'):
        job_id = uuid.uuid4().hex
        job = {
            'id': job_id,
            'status': 'running',
            'subnet': subnet_cidr,
            'scan_type': scan_type,
            'logs': [],
            'discovered': [],
            'started_at': datetime.utcnow().isoformat(),
            'finished_at': None,
            'total_discovered': 0,
            'error': None
        }
        with self._lock:
            self._jobs[job_id] = job

        thread = threading.Thread(target=self._run_scan, args=(job_id, subnet_cidr, scan_type), daemon=True)
        thread.start()
        return job_id

    def get_job(self, job_id):
        with self._lock:
            return self._jobs.get(job_id)

    def _append_log(self, job, line):
        job['logs'].append(line)
        # Trim to last 500 lines to avoid unbounded memory
        if len(job['logs']) > 500:
            job['logs'] = job['logs'][-500:]

    def _run_scan(self, job_id, subnet_cidr, scan_type):
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            return

        # Build nmap command
        if scan_type == 'ping':
            cmd = ['nmap', '-sn', subnet_cidr]
        else:
            # Detailed: service versions, OS detection, open ports
            cmd = ['nmap', '-sV', '-O', '--open', subnet_cidr]

        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

            current_host = None
            current_entry = None

            for raw_line in proc.stdout:
                line = raw_line.rstrip('\n')
                with self._lock:
                    self._append_log(job, line)

                s = line.strip()
                # Detect host header
                if s.startswith('Nmap scan report for'):
                    # finalize previous entry
                    if current_entry:
                        with self._lock:
                            job['discovered'].append(current_entry)
                    # start new entry
                    parts = s.split()
                    host_info = parts[-1].strip('()') if parts else ''
                    ip_str = host_info
                    if self._is_valid_ip(ip_str):
                        current_host = ip_str
                        current_entry = {
                            'address': ip_str,
                            'status': 'discovered',
                            'hostname': None,
                            'mac_address': None,
                            'manufacturer': None,
                            'os_info': None,
                            'open_ports': []
                        }
                        # Try reverse DNS
                        try:
                            current_entry['hostname'] = socket.gethostbyaddr(ip_str)[0]
                        except (socket.herror, socket.gaierror):
                            pass
                    else:
                        current_host = None
                        current_entry = None
                    continue

                if current_entry:
                    # MAC Address line
                    if s.startswith('MAC Address:'):
                        try:
                            after = s.split('MAC Address:')[1].strip()
                            mac_part, vendor = after.split(' ', 1)
                            current_entry['mac_address'] = mac_part.strip()
                            vendor = vendor.strip('() ').strip()
                            if vendor:
                                current_entry['manufacturer'] = vendor
                        except Exception:
                            pass
                        continue

                    # OS details
                    if s.startswith('OS details:'):
                        current_entry['os_info'] = s.split('OS details:')[1].strip()
                        continue

                    # Port lines (e.g., "22/tcp open ssh OpenSSH 8.2p1")
                    if '/' in s and ' open ' in s and not s.lower().startswith(('nmap done', 'service info', 'warning')):
                        try:
                            port_proto, rest = s.split(' ', 1)
                            port = port_proto.split('/')[0]
                            proto = port_proto.split('/')[1]
                            # rest may be like "open ssh OpenSSH 8.2p1"
                            rest = rest.strip()
                            if rest.startswith('open'):
                                rest = rest[len('open'):].strip()
                            parts = rest.split(' ', 1)
                            service = parts[0]
                            version = parts[1] if len(parts) > 1 else ''
                            current_entry['open_ports'].append({
                                'port': int(port) if port.isdigit() else port,
                                'proto': proto,
                                'service': service,
                                'version': version.strip()
                            })
                        except Exception:
                            pass
                        continue

            # Finalize last entry
            if current_entry:
                with self._lock:
                    job['discovered'].append(current_entry)

            proc.wait(timeout=5)

            with self._lock:
                job['status'] = 'completed'
                job['finished_at'] = datetime.utcnow().isoformat()
                job['total_discovered'] = len(job['discovered'])
        except Exception as e:
            with self._lock:
                job['status'] = 'error'
                job['error'] = str(e)
                job['finished_at'] = datetime.utcnow().isoformat()


# Singleton for async scan jobs
scan_jobs = ScanJobManager()

