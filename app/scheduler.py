"""Background job scheduler for periodic network verification"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app import db
from app.models import Subnet, IP
from app.scanner import NetworkScanner
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()
scanner = NetworkScanner()


def verify_subnet_ips(subnet_id):
    """Verify all IPs in a subnet to check if they're still live"""
    try:
        subnet = Subnet.query.get(subnet_id)
        if not subnet:
            return
        
        logger.info(f"Starting verification for subnet {subnet.name} ({subnet.cidr})")
        
        verified_count = 0
        live_count = 0
        
        for ip_obj in subnet.ips:
            result = scanner.verify_ip_status(ip_obj.address, subnet_id)
            verified_count += 1
            
            if result.get('is_live'):
                live_count += 1
        
        logger.info(f"Verification complete for {subnet.name}: {live_count}/{verified_count} IPs live")
    
    except Exception as e:
        logger.error(f"Error during subnet verification for subnet_id {subnet_id}: {str(e)}")


def verify_all_subnets():
    """Verify all subnets periodically"""
    try:
        subnets = Subnet.query.all()
        logger.info(f"Starting verification cycle for {len(subnets)} subnets")
        
        for subnet in subnets:
            verify_subnet_ips(subnet.id)
    
    except Exception as e:
        logger.error(f"Error during all-subnet verification: {str(e)}")


def stale_ip_check(days=30):
    """Mark IPs as potentially deprecated if not seen for N days"""
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        stale_ips = IP.query.filter(
            (IP.status == 'in-use') &
            (IP.last_seen < cutoff_date)
        ).all()
        
        if stale_ips:
            logger.info(f"Found {len(stale_ips)} potentially stale IPs (not seen in {days} days)")
            
            # Mark as deprecated but don't delete
            for ip_obj in stale_ips:
                logger.info(f"Marking {ip_obj.address} as deprecated (last seen: {ip_obj.last_seen})")
                ip_obj.status = 'deprecated'
            
            db.session.commit()
    
    except Exception as e:
        logger.error(f"Error during stale IP check: {str(e)}")


def schedule_verification(interval_hours=6):
    """
    Schedule periodic IP verification
    
    Args:
        interval_hours: How often to run verification (default: every 6 hours)
    """
    if not scanner.is_available():
        logger.warning("Nmap not available - network verification disabled")
        return
    
    job = scheduler.add_job(
        verify_all_subnets,
        'interval',
        hours=interval_hours,
        id='verify_all_subnets',
        name='Periodic IP Verification',
        replace_existing=True
    )
    
    logger.info(f"Scheduled IP verification every {interval_hours} hours")
    return job


def schedule_stale_check(cron_expression='0 2 * * *'):
    """
    Schedule periodic stale IP detection (default: daily at 2 AM UTC)
    
    Args:
        cron_expression: Cron expression for schedule
    """
    job = scheduler.add_job(
        stale_ip_check,
        CronTrigger.from_crontab(cron_expression),
        id='stale_ip_check',
        name='Stale IP Detection',
        replace_existing=True
    )
    
    logger.info(f"Scheduled stale IP check with cron: {cron_expression}")
    return job


def init_scheduler(app):
    """Initialize the scheduler with Flask app context"""
    if scheduler.running:
        return
    
    # Configure scheduler
    scheduler.configure(timezone='UTC')
    
    # Schedule jobs
    if scanner.is_available():
        schedule_verification(interval_hours=6)
        schedule_stale_check()
    
    # Start scheduler
    scheduler.start()
    logger.info("Background scheduler started")
    
    # Prevent scheduler from being started multiple times
    @app.teardown_appcontext
    def shutdown_scheduler(exception=None):
        pass


def shutdown_scheduler():
    """Shutdown the scheduler"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Background scheduler stopped")
