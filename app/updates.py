"""Check GitHub for a newer Lattice release."""
import logging
import os
import threading
import time

import requests

logger = logging.getLogger(__name__)

GITHUB_REPO = 'iamozyth/lattice'
RELEASES_URL = f'https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=1'
CACHE_SECONDS = 3600

_cache = {'at': 0.0, 'release': None}
_lock = threading.Lock()


def parse_version(value):
    """'v1.2.3-beta.1' -> (1, 2, 3, 0, 1); a final release sorts above its pre-releases."""
    value = (value or '').lstrip('v')
    core, _, pre = value.partition('-')
    try:
        numbers = tuple(int(p) for p in core.split('.')[:3])
    except ValueError:
        return (0, 0, 0, 0, 0)
    numbers += (0,) * (3 - len(numbers))
    if not pre:
        return numbers + (1, 0)
    digits = ''.join(ch for ch in pre if ch.isdigit())
    return numbers + (0, int(digits) if digits else 0)


def _fetch_latest():
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'lattice-update-checker'}
    token = os.environ.get('GITHUB_TOKEN')
    if token:
        headers['Authorization'] = f'Bearer {token}'
    resp = requests.get(RELEASES_URL, headers=headers, timeout=5)
    resp.raise_for_status()
    releases = resp.json()
    return releases[0] if releases else {}


def latest_release():
    with _lock:
        if _cache['release'] is not None and time.time() - _cache['at'] < CACHE_SECONDS:
            return _cache['release']
    release = _fetch_latest()
    with _lock:
        _cache.update(at=time.time(), release=release)
    return release


def check_for_updates(current_version):
    result = {'current_version': current_version, 'latest_version': None,
              'update_available': False, 'release_url': None, 'published_at': None,
              'error': None}
    try:
        release = latest_release()
    except (requests.RequestException, ValueError) as e:
        logger.warning('Update check failed: %s', e)
        result['error'] = 'Could not reach GitHub'
        return result
    if not release:
        result['error'] = 'No releases published yet'
        return result
    tag = release.get('tag_name') or ''
    result.update(
        latest_version=tag,
        release_url=release.get('html_url'),
        published_at=release.get('published_at'),
        update_available=parse_version(tag) > parse_version(current_version),
    )
    return result
