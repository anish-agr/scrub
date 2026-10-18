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

Open http://127.0.0.1:8080/. `PORT` changes the port. Cases are at http://127.0.0.1:8080/cases.html. Brandon deploys this page. The page reads Mongo through this process, so the URI never goes to the browser.

Log one recorded batch (appends a row to `docs/DATA-LOG.md`):

```
python -m ledger log --setting surgical --item hemostat --direction hand-out --lighting bright --demos 5 --dataset local --notes "cadence ok"
```

## Public page on a server

The page is this process. It does not ship the MongoDB URI to the browser.

On the Ubuntu server, from a checkout at `/opt/scrub` that contains `ledger/` and a root `.env` with `MONGODB_URI`:

```
sudo bash ledger/install_public.sh
```

That writes a systemd service, binds port 80, and restarts on failure. From a laptop that can SSH to the server:

```
bash ledger/push_public.sh root@THE_SERVER_IP
```

The exact Vultr and GoDaddy clicks are in the comments at the top of `ledger/install_public.sh`.
