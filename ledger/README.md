# ledger

Owner: Evan. Task E3 in `docs/TASKS.md`.

`log(event)`, `log_test(...)` and `stats()` per `docs/CONTRACTS.md`, writing to MongoDB Atlas (`MONGODB_URI` in `.env`). Never raises. Buffers to `ledger/buffer.jsonl` when Mongo is down.

Done when: events from a fake run show in Atlas and `stats()` returns the tables.
