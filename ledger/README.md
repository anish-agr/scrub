# ledger

Owner: Evan. Task E3 in `docs/TASKS.md`.

`log(event)`, `log_test(...)` and `stats()` per `docs/CONTRACTS.md`. The controller should return `stats()` from `GET /stats` unchanged.

`MONGODB_URI` in the repo-root `.env` points at MongoDB Atlas, database name `scrub`, collections `events` and `tests`. If the URI is missing or Atlas is down, calls still succeed and append to `ledger/buffer.jsonl` (git-ignored). A later successful connection flushes that file.

`stats()` shape:

```json
{
  "by_item": [
    {"item": "hemostat", "attempts": 4, "successes": 3, "success_rate": 0.75, "median_request_to_hand_s": 6.4}
  ],
  "by_lighting": [
    {"lighting": "normal", "attempts": 4, "successes": 3, "success_rate": 0.8, "median_request_to_hand_s": 6.1}
  ],
  "median_request_to_hand_s": 6.4,
  "out": ["hemostat"],
  "t": 1760731200.12
}
```

Success rates come from `log_test`. The median comes from `handed` events' `request_to_hand_s`, and from `log_test` seconds only when no handed events are stored. `out` is the count: `handed` or `set_down` marks an item out, `returned` clears it.

Run from the repo root:

```
pip install -r ledger/requirements.txt
python -m ledger
```

That prints the current tables. Never raises.

The public read-only page (the count and the tables, no arm controls):

```
python -m ledger serve
```

Open http://127.0.0.1:8080/. `PORT` changes the port. On Vultr, run that command and point the GoDaddy domain at the server. The page reads Mongo through this process, so the URI never goes to the browser.
