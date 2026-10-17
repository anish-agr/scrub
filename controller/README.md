# controller

Owner: Caiden. Tasks C1, C2, C5, C6, C8 in `docs/TASKS.md`.

FastAPI on port 8000. Owns the arm and every safety rule. Endpoints and messages are in `docs/CONTRACTS.md`. Serves `dashboard/` at `/`.

Run: `python -m controller --fake-arm` (default) or `python -m controller --real-arm`.

Done when: a handover command sent with curl runs every step on the fake arm and the events show on `WS /events`.
