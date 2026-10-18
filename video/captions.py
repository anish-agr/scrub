"""Camera captions as a second signal for `find`. Ledger events stay the main signal.

Only Perceptron captions count (label_source == "perceptron"); fallback labels are made from the event
itself, so they would only echo the ledger. A caption never makes a failed trial a success: it only
reorders takes that already passed the ledger check.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from .common import ledger_rows, read_json

CLIPS_DIR = Path(__file__).resolve().parents[1] / "vision" / "clips"
SLACK_S = 1.0  # a clip's event time may sit this far outside the trial window
NEGATIVE = re.compile(r"\b(drop(?:s|ped|ping)?|miss(?:ed|es|ing)?|fell|falls?|falling|fail(?:s|ed)?|"
                      r"empty (?:gripper|hand|claw)|(?:gripper|hand|claw) is empty|nothing (?:in|held))\b", re.I)
QA_BAD_FLAGS = {"dropped": "qa: instrument dropped", "grasp_failed": "qa: grasp failed", "dark": "qa: footage dark"}


def _norm(text):
    return re.sub(r"[\s_-]+", " ", str(text or "").strip().lower())


def _is_perceptron(row):
    return row.get("label_source") == "perceptron"


def _list_of_dicts(data):
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def _clips_from_dir(clips_dir, case_ids):
    rows = []
    for case in case_ids:
        try:
            rows += _list_of_dicts(json.loads((Path(clips_dir) / str(case) / "metadata.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return rows


def _clips_from_url(url, case_ids):
    rows = []
    for case in case_ids:
        query = urllib.parse.urlencode({"case_id": case})
        try:
            with urllib.request.urlopen(f"{url.rstrip('/')}/clips?{query}", timeout=5) as reply:
                rows += _list_of_dicts(json.loads(reply.read().decode("utf-8")))
        except (OSError, ValueError):
            continue
    return rows


def load_captions(trials, ledger_path=None, clips_dir=None, vision_url=None):
    """Caption rows for the cases in `trials`: clip metadata, an optional vision service, and ledger
    {"type":"caption"} rows. Missing files and an unreachable service give fewer rows, not an error."""
    cases = sorted({t['case_id'] for t in trials if t.get('case_id')})
    rows = _clips_from_dir(clips_dir or CLIPS_DIR, cases)
    if vision_url:
        rows += _clips_from_url(vision_url, cases)
    if ledger_path:
        try:
            rows += [r for r in ledger_rows(ledger_path) if r.get('type') == 'caption']
        except (OSError, ValueError, KeyError):
            pass
    return rows


def load_qa(path):
    """{episode: row} from a qa_video JSON report."""
    if not path:
        return {}
    return {r['episode']: r for r in read_json(path).get('episodes', []) if isinstance(r, dict) and 'episode' in r}


def _when(row):
    for key in ('timestamp', 't'):
        value = row.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _belongs(row, trial):
    command = row.get('command_id') or (row.get('event') or {}).get('command_id')
    if command:
        return command == trial['command_id']
    when = _when(row)
    if row.get('case_id') != trial.get('case_id') or when is None:
        return False
    return trial['start'] - SLACK_S <= when <= trial['end'] + SLACK_S


def _judge(row, trial):
    """(delta, reason) for one perceptron caption, or None when it says nothing either way."""
    text = row.get('label') or row.get('caption') or ''
    item = trial.get('item') or row.get('item')
    seen = row.get('caption_item')
    said = row.get('event_type') or (row.get('event') or {}).get('type') or 'handover'
    other_item = bool(seen and item and _norm(seen) not in {'none', _norm(item)})
    if row.get('agrees') is False:
        if other_item:
            return -1, f"camera disagrees: saw {_norm(seen)}, controller said {_norm(item)}"
        return -1, f"camera disagrees: saw {_norm(row.get('caption_action')) or 'something else'}, controller said {_norm(said)}"
    if NEGATIVE.search(text):
        return -1, f"camera caption reports a problem: {text}"
    if other_item:
        return -1, f"camera disagrees: saw {_norm(seen)}, controller said {_norm(item)}"
    if row.get('agrees') is True:
        return 1, f"camera agrees: {text}" if text else "camera agrees"
    return None


def assess(trial, captions, qa=None):
    """Caption evidence for one trial: score, reasons and the caption text to show beside it."""
    score, reasons, shown = 0, [], []
    for row in captions:
        if not _is_perceptron(row) or not _belongs(row, trial):
            continue
        shown.append(row.get('label') or row.get('caption') or '')
        verdict = _judge(row, trial)
        if verdict:
            score += verdict[0]
            reasons.append(verdict[1])
    episode = (qa or {}).get(trial.get('episode'))
    if episode:
        flags = [f for f in episode.get('flags', []) if f in QA_BAD_FLAGS]
        for flag in flags:
            score -= 1
            reasons.append(QA_BAD_FLAGS[flag])
        text = episode.get('caption')
        if text:
            shown.append(text)
            if NEGATIVE.search(text) and not flags:
                score -= 1
                reasons.append(f"qa caption reports a problem: {text}")
    return {'caption_score': score, 'caption_reasons': reasons, 'captions': [s for s in shown if s]}
