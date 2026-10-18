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

Open http://127.0.0.1:8080/ for the judge page. Cases are at http://127.0.0.1:8080/cases.html. The printable table card is http://127.0.0.1:8080/card.html. Brandon deploys this page. The page reads Mongo through this process, so the URI never goes to the browser.

```
python -m ledger.qr
```

That writes `ledger/public/qr.png` for `SCRUB_PUBLIC_URL` in `.env`. If the variable is empty, the code points at http://127.0.0.1:8080 until Brandon's domain is set. Run it again after the domain is in `.env`.

```
python -m ledger.shots
```

That runs a fake-arm hemostat handover (starting the controller and `vision --fake` if they are not already up) and saves screenshots in `docs/media/`.

Log one recorded batch (appends a row to `docs/DATA-LOG.md`):

```
python -m ledger log --setting surgical --item hemostat --direction hand-out --lighting bright --demos 5 --dataset local --notes "cadence ok"
```

## Public page on a server

One official path: `deploy/setup_public.sh`. The page is `python -m ledger serve` on 127.0.0.1:8080 (systemd `scrub-public`), nginx answers on port 80, and certbot adds HTTPS. The page does not ship the MongoDB URI to the browser. The Vultr and GoDaddy clicks are in `deploy/README.md`.

From a laptop that can SSH to the server:

```
bash ledger/push_public.sh root@THE_SERVER_IP
```

That copies `ledger/` (without `buffer.jsonl`) and `deploy/`, writes a server `.env` with only `MONGODB_URI` and `SCRUB_PUBLIC_URL`, and runs `deploy/setup_public.sh`. `ledger/install_public.sh` just calls the same script.

Fake-arm and sim runs: the controller may add `"fake_arm": true` (or `"sim": true`) to an event. `stats()` leaves those events out of the rates and the median (`GET /api/stats?sim=1` or `stats(include_sim=True)` counts them). The count `out` always reads every event. Untagged events count as real.

The `/api/*` routes send `Access-Control-Allow-Origin: *` and answer `OPTIONS`. They are read-only GETs.

Each results row also has `wilson_low` and `wilson_high`. `next_likely` is a suggestion only.

## Tested

Saturday Oct 17.

- `python -m unittest ledger.test_ledger` passed, 9 tests. A bad timestamp does not blank the tables. A NaN trial does not put `NaN` in the JSON.
- `MONGODB_URI` was unset. The running public page read `ledger/buffer.jsonl`. A throwaway case showed up on `GET /api/cases` and was then removed from that file.
- Judge page, case list, one real case, a missing case, and the table card, desktop and a 390px phone width. No horizontal overflow. No console errors. The phone judge page uses the numbered steps instead of the wide diagram. The missing case says "That case is not in the ledger."
- A bad `/api/stats` body and an empty body did not throw. Empty tables show "No measured trials yet." An empty `out` list shows "Nothing out."
- `GET /qr.png` is a PNG for the current public URL, with `Cache-Control: no-store`. With no `SCRUB_PUBLIC_URL`, that URL is http://127.0.0.1:8080.
