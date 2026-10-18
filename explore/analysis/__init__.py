"""MongoDB analysis: training data, handoffs, heat and reading, for the other chats and the pitch.

`python -m explore.analysis` reads the `scrub` database (read-only) and writes docs/DATA.md,
charts in docs/media/data/ and data/analysis.json.

Each report module has `build(data, charts_dir) -> dict` with keys:
  title     section heading
  summary   JSON-able dict for analysis.json (the data page reads this)
  markdown  section for docs/DATA.md
  notes     what to do next about this section (returned, not written to a file)
  numbers   [{"name", "value", "query"}] pitch and Devpost numbers; value "no real data yet" when there is none
"""

REPORTS = ("episodes", "handoffs", "heat", "reads")
