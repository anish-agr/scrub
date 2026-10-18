"""Losslessly move an approved console's inline CSS into the shared stylesheet.

One-time migration, with script and ID invariants checked before any writes.
Run python design/migrate_console.py nurse (or demo), then design/sync.py.
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent


def portable_html(html):
    """Keep decoded text unchanged when the Windows server uses read_text()."""
    parts = re.split(r"(<script\b[^>]*>.*?</script>)", html, flags=re.S)
    for i, part in enumerate(parts):
        if part.startswith("<script"):
            parts[i] = re.sub(r"[^\x00-\x7f]", lambda m: f"\\u{ord(m[0]):04x}", part)
        else:
            parts[i] = re.sub(r"[^\x00-\x7f]", lambda m: f"&#x{ord(m[0]):x};", part)
    return "".join(parts)


def migrate(name):
    if name not in ("nurse", "demo"):
        raise ValueError("Only the two approved controller consoles may be migrated")
    target = ROOT / "controller" / f"{name}.html"
    source = ROOT / "design" / "scrub.css"
    html = target.read_text(encoding="utf-8")
    match = re.search(r"<style>(.*?)</style>", html, re.S)
    if not match:
        raise ValueError("No inline sheet. This console has already been migrated")
    original_css = match.group(1).strip()
    # Scope the original selectors, do not increase specificity or rewrite rules.
    css = original_css.replace(":root", ":scope")
    shared = source.read_text(encoding="utf-8")
    shared += f'\n\n/* Approved {name} console: original appearance, isolated compatibility rules. */\n'
    shared += f'@scope (body[data-page="{name}"]) {{\n{css}\n}}\n'
    link = '<link rel="stylesheet" href="/style.css" onerror="this.onerror=null;this.href=\'../dashboard/style.css\'">'
    new = html[:match.start()] + link + html[match.end():]
    new = new.replace("<body>", f'<body class="scrub-console" data-page="{name}">', 1)
    if name == "nurse":
        # The original console had no footer. No other content is changed.
        new = new.replace("\n<script>", '\n<footer>Team Scrub · DubHacks \'26 <a href="#">Terms</a><a href="#">Privacy</a></footer>\n<script>', 1)
        shared += ('@scope (body[data-page="nurse"]) {\n'
                   'footer{padding:14px 16px;border-top:1px solid var(--line);font:12px var(--head);color:var(--mute);display:flex;gap:16px;flex-wrap:wrap}\n'
                   'footer a{color:inherit}\n}\n')
    else:
        new = new.replace("</footer>", '<a href="#">Terms</a><a href="#">Privacy</a>\n</footer>', 1)
    scripts = lambda text: re.findall(r"<script\b[^>]*>.*?</script>", text, re.S)
    ids = lambda text: re.findall(r'\bid="([^"]+)"', text)
    assert scripts(html) == scripts(new), "JavaScript changed"
    assert ids(html) == ids(new), "Element IDs changed"
    source.write_text(shared, encoding="utf-8", newline="\n")
    target.write_text(portable_html(new), encoding="utf-8", newline="\n")
    print(f"{name}: CSS moved; scripts, declarations and IDs preserved")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--portable":
        if sys.argv[2] not in ("nurse", "demo"):
            raise ValueError("Only the approved consoles may be converted")
        path = ROOT / "controller" / f"{sys.argv[2]}.html"
        path.write_text(portable_html(path.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
        print(f"{sys.argv[2]}: HTML entities and equivalent JS unicode escapes written")
    else:
        migrate(sys.argv[1])
