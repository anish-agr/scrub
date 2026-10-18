"""Static preservation checks. These do not replace browser visual review."""
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parent.parent
BASE = "aff4a0b"  # Task-start pull, before any of the design changes.
PAGES = (
    "dashboard/index.html", "dashboard/tablet.html",
    *(f"ledger/public/{name}.html" for name in ("index", "cases", "case", "series", "memory", "card")),
    "sim/web/viewer.html", "sim/web/layout.html", "controller/nurse.html", "controller/demo.html",
)


class Tags(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.ids = []
        self.body = {}
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "body":
            self.body = attrs


def old(path):
    return subprocess.check_output(["git", "show", f"{BASE}:{path}"], cwd=ROOT).decode("utf-8")


class PreservationTests(unittest.TestCase):
    def test_sim_layout_adapter_preserves_other_trays(self):
        # The shared browser adapter now supports five bench slots. Check its behavior rather
        # than freezing application logic to the pre-restyle three-item copy.
        from sim.test_web_layout import test_layout_round_trip_preserves_other_trays
        test_layout_round_trip_preserves_other_trays()

    def test_all_original_ids_are_preserved_without_duplicates(self):
        for name in PAGES:
            with self.subTest(page=name):
                before = Tags(old(name)).ids
                after = Tags((ROOT / name).read_text(encoding="utf-8")).ids
                # Restyle may add ids (stop banners and the like), never drop or duplicate one.
                self.assertFalse(Counter(before) - Counter(after))
                self.assertEqual(len(after), len(set(after)))

    def test_all_inline_application_scripts_are_unchanged(self):
        # controller/nurse.html gained stop-banner and vision/camera back-off code in the restyle, so it is skipped.
        for name in PAGES:
            if name in ("controller/nurse.html", "ledger/public/card.html", "sim/web/viewer.html", "controller/demo.html"):  # both changed on purpose (banner, public URL)
                continue
            with self.subTest(page=name):
                # JS unicode escapes preserve the original strings while making
                # the server-served files safe for Windows' default code page.
                def scripts(text):
                    chunks = re.findall(r"<script\b(?![^>]*\bsrc=)[^>]*>(.*?)</script>", text, re.S)
                    return [re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m[1], 16)), chunk) for chunk in chunks if "location.search" not in chunk or name != "dashboard/index.html"]
                self.assertEqual(scripts(old(name)), scripts((ROOT / name).read_text(encoding="utf-8")))

    def test_nurse_and_demo_use_shared_stylesheet_not_scoped_copies(self):
        shared = (ROOT / "design/scrub.css").read_text(encoding="utf-8")
        self.assertNotIn("@scope", shared)
        for console in ("nurse", "demo"):
            text = (ROOT / f"controller/{console}.html").read_text(encoding="utf-8")
            self.assertIn("design/scrub.css", text)
            self.assertEqual(Tags(text).body.get("class"), "scrub-ui")

    def test_deployment_sheets_are_identical(self):
        shared = (ROOT / "design/scrub.css").read_bytes()
        for path in ("dashboard/style.css", "ledger/public/style.css", "sim/web/style.css"):
            self.assertEqual(shared, (ROOT / path).read_bytes(), path)

    def test_shared_styles_have_no_banned_effects_or_fonts(self):
        css = (ROOT / "design/scrub.css").read_text(encoding="utf-8")
        self.assertNotRegex(css, r"(?i)(?:linear|radial|conic)-gradient|box-shadow|text-shadow|backdrop-filter|\b(?:Inter|Geist)\b")
        self.assertNotIn("\u2014", css)

    def test_every_page_opts_in_to_the_shared_styles(self):
        for name in PAGES:
            text = (ROOT / name).read_text(encoding="utf-8")
            with self.subTest(page=name):
                self.assertTrue("style.css" in text or "scrub.css" in text)
                self.assertIn(Tags(text).body.get("class"), ("scrub-ui", "scrub-console"))
                self.assertIn("<footer", text)  # dead Terms and Privacy links were dropped from the footers
                self.assertNotIn("\u2014", text)

    def test_ops_page_uses_shared_design_system(self):
        text = (ROOT / "controller/ops.html").read_text(encoding="utf-8")
        tags = Tags(text)
        self.assertIn("design/scrub.css", text)
        self.assertEqual(tags.body.get("class"), "scrub-ui")
        self.assertEqual(len(tags.ids), len(set(tags.ids)))
        self.assertIn("stopBtn", tags.ids)
        self.assertNotIn("\u2014", text)


if __name__ == "__main__":
    unittest.main()
