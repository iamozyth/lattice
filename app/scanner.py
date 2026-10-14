"""nmap wrapper: one validated command builder, one output parser, bounded scan jobs."""
import ipaddress
import logging
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

SCAN_TYPES = {
    'ping': (['-sn'], 900),
    'full': (['-sV', '-O', '--open', '-T4'], 3600),
}
MAX_CONCURRENT_JOBS = 2
JOB_TTL_SECONDS = 3600
MAX_LOG_LINES = 500

_REPORT_RE = re.compile(r'^Nmap scan report for (?:(?P<name>\S+) \((?P<ip1>[^)]+)\)|(?P<ip2>\S+))$')
_MAC_RE = re.compile(r'^MAC Address: (?P<mac>[0-9A-Fa-f:]{17})(?: \((?P<vendor>.*)\))?$')
_PORT_RE = re.compile(r'^(?P<port>\d+)/(?P<proto>tcp|udp)\s+open\s+(?P<service>\S+)\s*(?P<version>.*)$')


class ScanError(Exception):
    """A scan could not run; the message is safe to show."""


def nmap_available():
    return shutil.which('nmap') is not None


def nmap_targets(values):
    """Validate targets and return (version, [normalized strings]).

    Anything that isn't an IP address or network is rejected, so a value
    can never be read as an nmap option.
    """
    targets, versions = [], set()
    for value in values:
        try:
            net = ipaddress.ip_network(str(value).strip(), strict=False)
        except ValueError:
            raise ScanError(f'Not a valid scan target: {value}')
        versions.add(net.version)
        targets.append(str(net.network_address) if net.num_addresses == 1 else str(net))
    if not targets:
        raise ScanError('Nothing to scan')
    if len(versions) > 1:
        raise ScanError('Cannot mix IPv4 and IPv6 targets in one scan')
    return versions.pop(), targets


def build_command(scan_type, values):
    if scan_type not in SCAN_TYPES:
        raise ScanError(f'Unknown scan type: {scan_type}')
    version, targets = nmap_targets(values)
    args, _ = SCAN_TYPES[scan_type]
    cmd = ['nmap', *args]
    if version == 6:
        cmd.append('-6')
    return cmd + ['--', *targets]


class OutputParser:
    """Turns nmap's normal output, line by line, into host dicts."""

    def __init__(self):
        self.hosts = []
        self._current = None

    def feed(self, line):
        s = line.strip()
        m = _REPORT_RE.match(s)
        if m:
            self._finish()
            address = m.group('ip1') or m.group('ip2')
            try:
                address = str(ipaddress.ip_address(address))
            except ValueError:
                self._current = None
                return
            self._current = {'address': address, 'hostname': m.group('name'),
                             'mac_address': None, 'vendor': None, 'os_info': None,
                             'open_ports': []}
            return
        if not self._current:
            return
        if (m := _MAC_RE.match(s)):
            self._current['mac_address'] = m.group('mac').upper()
            vendor = (m.group('vendor') or '').strip()
            self._current['vendor'] = vendor if vendor and vendor != 'Unknown' else None
        elif s.startswith('OS details:'):
            self._current['os_info'] = s.split(':', 1)[1].strip()[:255]
        elif (m := _PORT_RE.match(s)):
            self._current['open_ports'].append({
                'port': int(m.group('port')), 'proto': m.group('proto'),
                'service': m.group('service'), 'version': m.group('version').strip()})
        elif s.startswith('Host seems down') or s.startswith('Host is down'):
            self._current = None

    def _finish(self):
        if self._current:
            self.hosts.append(self._current)
        self._current = None

    def close(self):
        self._finish()
        return self.hosts


def run_scan(scan_type, values, on_line=None, should_stop=None):
    """Run nmap and return the hosts that are up."""
    cmd = build_command(scan_type, values)
    timeout = SCAN_TYPES[scan_type][1]
    parser = OutputParser()
    deadline = time.monotonic() + timeout
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            bufsize=1)
    watchdog = threading.Timer(timeout, proc.kill)
    watchdog.start()
    try:
        for raw in proc.stdout:
            line = raw.rstrip('\n')
            parser.feed(line)
            if on_line:
                on_line(line)
            if should_stop and should_stop():
                proc.kill()
                raise ScanError('Scan cancelled')
        proc.wait()
    finally:
        watchdog.cancel()
    if time.monotonic() >= deadline:
        raise ScanError(f'Scan stopped after {timeout // 60} minutes')
    if proc.returncode not in (0, 1):
        raise ScanError(f'nmap exited with code {proc.returncode}')
    return parser.close()


class ScanJobs:
    """Background scans with live logs. Lives in the single gunicorn worker."""

    def __init__(self):
        self._jobs = {}
        self._lock = threading.Lock()

    def _prune(self):
        cutoff = time.time() - JOB_TTL_SECONDS
        for job_id in [j for j, job in self._jobs.items()
                       if job['status'] != 'running' and job['_finished'] < cutoff]:
            del self._jobs[job_id]

    def start(self, app, subnet, scan_type, user=None):
        # Validate before creating the job so bad input fails the request
        build_command(scan_type, [subnet.cidr])
        with self._lock:
            self._prune()
            running = sum(1 for j in self._jobs.values() if j['status'] == 'running')
            if running >= MAX_CONCURRENT_JOBS:
                raise ScanError('Two scans are already running. Try again when one finishes.')
            if any(j['status'] == 'running' and j['subnet_id'] == subnet.id for j in self._jobs.values()):
                raise ScanError('This subnet is already being scanned')
            job_id = uuid.uuid4().hex
            self._jobs[job_id] = {
                'id': job_id, 'status': 'running', 'subnet_id': subnet.id,
                'subnet': subnet.cidr, 'scan_type': scan_type, 'logs': [],
                'discovered': [], 'error': None, 'started_by': user,
                'started_at': datetime.utcnow().isoformat(), 'finished_at': None,
                '_finished': 0.0,
            }
        thread = threading.Thread(target=self._run, args=(app, job_id, subnet.id, subnet.cidr, scan_type),
                                  daemon=True, name=f'scan-{job_id[:8]}')
        thread.start()
        return job_id

    def get(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            snapshot = {k: v for k, v in job.items() if not k.startswith('_')}
            snapshot['logs'] = list(job['logs'])
            snapshot['discovered'] = list(job['discovered'])
            return snapshot

    def _log(self, job_id, line):
        with self._lock:
            logs = self._jobs[job_id]['logs']
            logs.append(line)
            del logs[:-MAX_LOG_LINES]

    def _run(self, app, job_id, subnet_id, cidr, scan_type):
        from app.discovery import record_hosts
        try:
            hosts = run_scan(scan_type, [cidr], on_line=lambda line: self._log(job_id, line))
            with app.app_context():
                record_hosts(subnet_id, hosts, source='scan', full_sweep=True)
            status, error = 'completed', None
        except ScanError as e:
            hosts, status, error = [], 'error', str(e)
        except Exception:
            logger.exception('Scan job %s failed', job_id)
            hosts, status, error = [], 'error', 'Scan failed, see server log'
        with self._lock:
            job = self._jobs[job_id]
            job.update(status=status, error=error, discovered=hosts,
                       finished_at=datetime.utcnow().isoformat(), _finished=time.time())


scan_jobs = ScanJobs()
