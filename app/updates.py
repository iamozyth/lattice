"""
Update checking module - checks GitHub for new releases
"""
import requests
import logging
from functools import lru_cache
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

GITHUB_REPO = 'iamozyth/netdoc-ipam'
GITHUB_API_URL = f'https://api.github.com/repos/{GITHUB_REPO}/releases/latest'


def parse_version(version_string):
    """
    Parse semantic version string into tuple for comparison.
    e.g., '2.0.0' -> (2, 0, 0)
    """
    try:
        # Remove 'v' prefix if present
        version_string = version_string.lstrip('v')
        parts = version_string.split('.')
        return tuple(int(p) for p in parts[:3])
    except (ValueError, AttributeError):
        return (0, 0, 0)


@lru_cache(maxsize=1)
def get_latest_release(cache_timeout=3600):
    """
    Fetch latest release info from GitHub with caching.
    Returns None if unable to fetch or on error.
    """
    try:
        response = requests.get(
            GITHUB_API_URL,
            timeout=5,
            headers={'Accept': 'application/vnd.github.v3+json'}
        )
        response.raise_for_status()
        
        data = response.json()
        return {
            'tag_name': data.get('tag_name', ''),
            'name': data.get('name', ''),
            'html_url': data.get('html_url', ''),
            'body': data.get('body', ''),
            'published_at': data.get('published_at', ''),
            'draft': data.get('draft', False),
            'prerelease': data.get('prerelease', False),
        }
    except requests.RequestException as e:
        logger.warning(f"Failed to fetch latest release from GitHub: {e}")
        return None
    except Exception as e:
        logger.error(f"Error parsing GitHub release data: {e}")
        return None


def check_for_updates(current_version):
    """
    Check if a newer version is available on GitHub.
    
    Args:
        current_version (str): Current application version (e.g., '2.0.0')
    
    Returns:
        dict: {
            'update_available': bool,
            'current_version': str,
            'latest_version': str,
            'release_url': str,
            'release_notes': str,
            'published_at': str,
            'is_prerelease': bool,
        }
    """
    release = get_latest_release()
    
    if not release:
        return {
            'update_available': False,
            'current_version': current_version,
            'latest_version': None,
            'release_url': None,
            'release_notes': None,
            'published_at': None,
            'is_prerelease': False,
            'error': 'Unable to check for updates'
        }
    
    current = parse_version(current_version)
    latest = parse_version(release['tag_name'])
    update_available = latest > current
    
    return {
        'update_available': update_available,
        'current_version': current_version,
        'latest_version': release['tag_name'],
        'release_url': release['html_url'],
        'release_notes': release['body'],
        'published_at': release['published_at'],
        'is_prerelease': release['prerelease'],
        'error': None
    }


def clear_cache():
    """Clear the cached release info"""
    get_latest_release.cache_clear()
