import pathlib
import re

STATIC = pathlib.Path(__file__).resolve().parent.parent / 'app'


def test_no_html_injection_sinks():
    """Server data must only reach the DOM through textContent (dom.h)."""
    for path in (STATIC / 'static' / 'js').rglob('*.js'):
        source = path.read_text()
        assert not re.search(r'\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML|document\.write', source), path


def test_templates_have_no_inline_scripts_or_handlers():
    for path in (STATIC / 'templates').glob('*.html'):
        html = path.read_text()
        assert not re.search(r'\son[a-z]+\s*=', html), path
        assert not re.search(r'<script(?![^>]*\bsrc=)', html), path
        assert 'style=' not in html, path
