"""Handoff time series for the Tiger Data track.

`TIGER_DATABASE_URL` is a Postgres connection string (Tiger Cloud uses
`sslmode=require`). When it is set, each handoff is inserted into the
`scrub_handoff` hypertable. The series page still works without it: the same
buckets are counted from the ledger.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from ledger import _is_sim, _median, _num

_READY = False


def url() -> str:
    return os.environ.get("TIGER_DATABASE_URL", "").strip()


def _connect():
    import psycopg

    return psycopg.connect(url(), connect_timeout=3)


def _ensure(connection) -> None:
    global _READY
    if _READY:
        return
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS scrub_handoff (
                t timestamptz NOT NULL,
                item text,
                setting text,
                lighting text,
                seconds double precision,
                sim boolean NOT NULL
            )
            """
        )
    connection.commit()
    try:
        with connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
            cursor.execute(
                "SELECT create_hypertable('scrub_handoff', 't', if_not_exists => TRUE)"
            )
        connection.commit()
    except Exception:
        connection.rollback()
    _READY = True


def remember_event(event: dict) -> None:
    """Insert one handed event. Never raises. No URL means nothing to do."""
    if not url() or not isinstance(event, dict) or event.get("type") != "handed":
        return
    stamp = _num(event.get("t"))
    if stamp is None:
        return
    try:
        with _connect() as connection:
            _ensure(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO scrub_handoff (t, item, setting, lighting, seconds, sim)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        datetime.fromtimestamp(stamp, timezone.utc),
                        event.get("item"),
                        event.get("setting"),
                        event.get("lighting"),
                        _num(event.get("request_to_hand_s")),
                        _is_sim(event),
                    ),
                )
            connection.commit()
    except Exception:
        return


def _from_tiger() -> list[dict] | None:
    if not url():
        return None
    try:
        with _connect() as connection:
            _ensure(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        EXTRACT(EPOCH FROM time_bucket('1 minute', t)) AS bucket,
                        COUNT(*)::int,
                        COUNT(*) FILTER (WHERE NOT sim)::int,
                        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY seconds)
                    FROM scrub_handoff
                    GROUP BY 1
                    ORDER BY 1
                    """
                )
                rows = cursor.fetchall()
    except Exception:
        return None
    buckets = []
    for bucket, count, real, median in rows:
        buckets.append(
            {
                "t": float(bucket),
                "n": int(count),
                "real": int(real),
                "median_s": None if median is None else float(median),
            }
        )
    return buckets[-24:]


def series_from(events: list[dict]) -> list[dict]:
    """One bucket per minute of handed events, oldest first, at most 24."""
    groups: dict[int, dict] = {}
    for event in events:
        if not isinstance(event, dict) or event.get("type") != "handed":
            continue
        stamp = _num(event.get("t"))
        if stamp is None:
            continue
        key = int(stamp // 60) * 60
        row = groups.setdefault(key, {"t": key, "n": 0, "real": 0, "seconds": []})
        row["n"] += 1
        if not _is_sim(event):
            row["real"] += 1
        number = _num(event.get("request_to_hand_s"))
        if number is not None:
            row["seconds"].append(number)
    buckets = []
    for key in sorted(groups):
        row = groups[key]
        buckets.append(
            {
                "t": key,
                "n": row["n"],
                "real": row["real"],
                "median_s": _median(row["seconds"]),
            }
        )
    return buckets[-24:]


def series(events: list[dict]) -> dict:
    remote = _from_tiger()
    if remote is not None:
        return {"source": "tiger", "buckets": remote}
    return {"source": "local", "buckets": series_from(events)}
