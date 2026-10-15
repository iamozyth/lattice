"""Periodic ping sweeps that keep last_seen and the drift view current."""
import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app import db
from app.models import Subnet
from app.scanner import ScanError, nmap_available, run_scan

logger = logging.getLogger(__name__)

# Above this many documented IPs we don't ping them one list at a time
MAX_TARGETS = 4096

scheduler = BackgroundScheduler(timezone='UTC')


def sweep_subnet(subnet):
    """Ping the whole subnet if it's small enough, otherwise just its documented IPs."""
    from app.discovery import record_hosts
    if subnet.auto_scan:
        targets = [subnet.cidr]
    else:
        targets = [ip.address for ip in subnet.ips if ip.status != 'deprecated']
        if not targets or len(targets) > MAX_TARGETS:
            return 0
    hosts = run_scan('ping', targets)
    return record_hosts(subnet.id, hosts, source='scan', full_sweep=True)


def sweep_all(app):
    with app.app_context():
        subnet_ids = [s.id for s in Subnet.query.order_by(Subnet.id)]
        logger.info('Ping sweep of %d subnets', len(subnet_ids))
        for subnet_id in subnet_ids:
            subnet = db.session.get(Subnet, subnet_id)
            if not subnet:
                continue
            try:
                seen = sweep_subnet(subnet)
                logger.info('Swept %s: %d hosts up', subnet.cidr, seen)
            except ScanError as e:
                logger.warning('Sweep of %s failed: %s', subnet.cidr, e)
            except Exception:
                logger.exception('Sweep of %s failed', subnet.cidr)
                db.session.rollback()


def purge_history(app):
    from app.history import purge
    with app.app_context():
        n = purge(app.config['HISTORY_DAYS'])
        if n:
            logger.info('Dropped %d history entries older than %d days', n, app.config['HISTORY_DAYS'])


def init_scheduler(app):
    if scheduler.running:
        return
    scheduler.add_job(purge_history, 'interval', hours=24, args=[app], id='purge_history',
                      max_instances=1, coalesce=True, replace_existing=True)
    hours = app.config['SCAN_INTERVAL_HOURS']
    if hours <= 0:
        logger.info('Scheduled scans disabled (SCAN_INTERVAL_HOURS=0)')
    elif not nmap_available():
        logger.warning('nmap not found; scheduled scans disabled')
    else:
        scheduler.add_job(sweep_all, 'interval', hours=hours, args=[app], id='sweep_all',
                          max_instances=1, coalesce=True, replace_existing=True)
        logger.info('Scheduled ping sweeps every %s hours', hours)
    scheduler.start()
