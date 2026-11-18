"""Local presentation and download controls for the embedded score library."""

from json import dumps
from string import Template

from bdo_music_composer.app.application_metadata import APP_WEBSITE_URL
from bdo_music_composer.ui.theme import hig_tokens as hig


_DARK_STYLE = Template("""
:root { color-scheme: dark; --bg: $CANVAS; --fg: $TEXT; --fg2: $SECONDARY_TEXT; --line: $SEPARATOR; }
html, body { background-color: var(--bg); color: var(--fg); }
a, .dl, .tools a { color: $ACCENT; }
.nav a, .lang a:hover, .a, .srv .dt { color: var(--fg); }
.inst, .m, #loading, .srv .sub { color: var(--fg2); }
.nav a, .item, .srv td { border-color: var(--line); }
.srv th, .srv-total td { border-color: $CONTROL_BORDER; }
.nav a:hover, .item:hover, .srv tbody tr:hover, .srv-merged td { background: $PANEL; }
.lang select, #q { background: $CONTROL; color: var(--fg); border-color: var(--line); }
#q:focus { outline-color: $ACCENT; }
""").substitute(vars(hig))

_LIBRARY_ORIGIN = dumps(APP_WEBSITE_URL.rstrip("/"))

SETUP_LIBRARY_PAGE = Template(r"""
(() => {
    if (location.origin !== $origin || !document.head) return;
    let style = document.getElementById('bdo-composer-local-style');
    if (!style) {
        style = document.createElement('style');
        style.id = 'bdo-composer-local-style';
        document.head.append(style);
    }
    style.textContent = $style;
    if (typeof window.bdoComposerReadDownloads === 'function') return;
    const downloads = [];
    window.bdoComposerReadDownloads = () => JSON.stringify(downloads.splice(0));
    document.addEventListener('click', event => {
        if (!event.isTrusted || event.button !== 0 || !(event.target instanceof Element)) return;
        const anchor = event.target.closest('a[href]');
        if (!(anchor instanceof HTMLAnchorElement)) return;
        const url = new URL(anchor.href);
        if (url.origin !== $origin || url.username || url.password || url.search || url.hash) return;
        const isScore = /^\/dl\/[0-9]{15,20}$$/.test(url.pathname);
        if (!isScore && url.pathname !== '/bulk/download') return;
        event.preventDefault();
        event.stopImmediatePropagation();
        downloads.push(url.href);
    }, true);
})()
""").substitute(origin=_LIBRARY_ORIGIN, style=dumps(_DARK_STYLE))

READ_LIBRARY_DOWNLOADS = Template("""
location.origin === $origin && typeof window.bdoComposerReadDownloads === 'function'
    ? window.bdoComposerReadDownloads() : '[]'
""").substitute(origin=_LIBRARY_ORIGIN)
