"""Regenerate index.html from gallery.template.html + metadata comments in each NN-*.html prototype."""
import glob, json, os, re

here = os.path.dirname(os.path.abspath(__file__))
items = []
for path in sorted(glob.glob(os.path.join(here, "[0-9][0-9]-*.html"))):
    s = open(path, encoding="utf-8").read()
    head = s[:20000]
    def grab(pat, default=""):
        m = re.search(pat, head, re.S | re.I)
        return m.group(1).strip() if m else default
    feats = grab(r"<!--\s*FEATURES:(.*?)-->")
    items.append({
        "id": os.path.basename(path)[:2],
        "file": os.path.basename(path),
        "title": grab(r"<title>(.*?)</title>", os.path.basename(path)),
        "desc": grab(r'<meta name="description" content="(.*?)"'),
        "features": [re.sub(r"^[-*]\s*", "", l).strip() for l in feats.splitlines() if l.strip()],
        "sponsors": grab(r"<!--\s*SPONSORS:(.*?)-->"),
        "hooks": grab(r"<!--\s*BACKEND HOOKS:(.*?)-->"),
    })
tpl = open(os.path.join(here, "gallery.template.html"), encoding="utf-8").read()
out = tpl.replace("/*DATA*/[]", json.dumps(items, ensure_ascii=False).replace("</", "<\\/"))
open(os.path.join(here, "index.html"), "w", encoding="utf-8").write(out)
print(f"index.html: {len(items)} prototypes")
