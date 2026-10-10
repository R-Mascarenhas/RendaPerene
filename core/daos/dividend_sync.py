"""Atomic dividend decisions using the existing source registry and receipt schema."""

import datetime
import hashlib
import json
import sqlite3
from contextlib import closing


class DividendSyncRepository:
    """Internal portfolio DAO implementation; all connections belong to the owning DAO."""

    def reschedule_dividend(self, receipt_id, date, expected_revision):
        with closing(self.get_personal_connection()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._check_dividend_revision(conn, expected_revision)
            changed = conn.execute(
                "UPDATE dividends SET date=? WHERE id=?",
                (date, receipt_id),
            ).rowcount
            if not changed:
                raise ValueError("O provento não está mais disponível. Atualize a carteira.")
            conn.commit()
            return True

    def get_dividend_reviews(self) -> dict:
        with closing(self.get_personal_connection()) as conn:
            rows = conn.execute(
                "SELECT source_key, source_record FROM b3_import_records "
                "WHERE event_kind='DIVIDEND' AND source_key LIKE 'yahoo-dividend:%'"
            ).fetchall()
        return {key: json.loads(record) for key, record in rows}

    def save_dividend_review(self, event, kind, payments, expected_revision) -> bool:
        with closing(self.get_personal_connection()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute(
                "SELECT 1 FROM b3_import_records WHERE source_key=?", (event.source_key,)
            ).fetchone():
                return False
            self._check_dividend_revision(conn, expected_revision)
            ids = []
            for payment in payments:
                receipt_id = payment["existing_id"]
                if receipt_id is not None:
                    found = conn.execute(
                        "SELECT id FROM dividends WHERE id=? AND ticker=? AND dividend_type=?",
                        (receipt_id, event.ticker, kind),
                    ).fetchone()
                    if found is None:
                        raise ValueError(
                            "O pagamento escolhido mudou. Revise os proventos novamente."
                        )
                else:
                    receipt_id = conn.execute(
                        "INSERT INTO dividends "
                        "(date,ticker,dividend_type,total_value,quantity,unit_price) "
                        "VALUES (?,?,?,?,?,?)",
                        (
                            payment["date"],
                            event.ticker,
                            kind,
                            payment["total_value"],
                            payment["quantity"],
                            payment["unit_price"],
                        ),
                    ).lastrowid
                ids.append(receipt_id)
            record = {
                "ticker": event.ticker,
                "ex_date": event.ex_date,
                "unit_value": event.unit_value,
                "receipt_ids": ids,
            }
            self._record_dividend_source(
                conn,
                event.source_key,
                record,
                "DIVIDEND_CONFIRMED" if payments else "DIVIDEND_IGNORED",
            )
            conn.commit()
            return True

    @staticmethod
    def _check_dividend_revision(conn, expected_revision):
        revision = conn.execute("SELECT revision FROM portfolio_projection_state").fetchone()[0]
        if revision != expected_revision:
            raise ValueError("A carteira mudou. Atualize e revise os proventos novamente.")

    @staticmethod
    def _record_dividend_source(conn, key, record, status):
        conn.execute(
            "INSERT INTO b3_import_records "
            "(source_key,source_record,event_kind,transaction_id,status) "
            "VALUES (?,?,'DIVIDEND',NULL,?)",
            (key, json.dumps(record, sort_keys=True), status),
        )
        conn.execute("UPDATE portfolio_projection_state SET revision=revision+1 WHERE id=1")

    @staticmethod
    def dividend_b3_key(record):
        identity = {
            key: record.get(key)
            for key in (
                "ticker",
                "date",
                "dividend_type",
                "total_value",
                "quantity",
                "unit_price",
                "institution",
                "occurrence",
            )
        }
        return (
            "b3-dividend:"
            + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        )

    @staticmethod
    def _dividend_candidates(conn, record, batch_sources=()):
        origins = conn.execute(
            "SELECT source_record, status, source_key FROM b3_import_records "
            "WHERE event_kind='DIVIDEND'"
        ).fetchall()
        yahoo_ids = set()
        b3_ids = set()
        b3_institutions = {}
        batch_ids = set()
        previous_ids = set()
        for source, status, key in origins:
            origin = json.loads(source)
            ids = origin.get("receipt_ids", [])
            (batch_ids if key in batch_sources else previous_ids).update(ids)
            (b3_ids if status == "DIVIDEND_B3" else yahoo_ids).update(ids)
            if status == "DIVIDEND_B3":
                institution = origin.get("b3", {}).get("institution")
                b3_institutions.update(dict.fromkeys(ids, institution))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, date, ticker, dividend_type, total_value, quantity, unit_price "
            "FROM dividends WHERE ticker=? ORDER BY date,id",
            (record["ticker"],),
        ).fetchall()
        batch_ids.difference_update(previous_ids)
        return [
            dict(row)
            for row in rows
            if row["id"] not in batch_ids
            and (
                row["dividend_type"] == record["dividend_type"]
                or (row["id"] in yahoo_ids and row["id"] not in b3_ids)
            )
            and (
                (
                    row["id"] not in b3_ids
                    and (
                        row["id"] in yahoo_ids
                        or row["date"] > datetime.date.today().isoformat()
                        or row["date"] != record["date"]
                        or row["total_value"] != record["total_value"]
                        or DividendSyncRepository._dividend_metadata_differs(row, record)
                    )
                )
                or (
                    row["id"] in b3_ids
                    and row["date"] == record["date"]
                    and (
                        row["total_value"] != record["total_value"]
                        or DividendSyncRepository._dividend_metadata_differs(row, record)
                    )
                    and (
                        not b3_institutions.get(row["id"])
                        or not record.get("institution")
                        or b3_institutions[row["id"]] == record["institution"]
                    )
                )
            )
        ]

    @staticmethod
    def _dividend_metadata_differs(payment, record):
        return any(
            payment[field] is not None
            and record.get(field) is not None
            and payment[field] != record[field]
            for field in ("quantity", "unit_price")
        )

    def find_b3_dividend_candidates(self, record):
        with closing(self.get_personal_connection()) as conn:
            if conn.execute(
                "SELECT 1 FROM b3_import_records WHERE source_key=?",
                (self.dividend_b3_key(record),),
            ).fetchone():
                return []
            return self._dividend_candidates(conn, record)

    @staticmethod
    def _has_distinct_b3_credit(conn, record):
        origins = conn.execute(
            "SELECT source_record FROM b3_import_records "
            "WHERE event_kind='DIVIDEND' AND status='DIVIDEND_B3'"
        ).fetchall()
        for (source,) in origins:
            previous = json.loads(source).get("b3", {})
            if all(
                previous.get(field) == record[field]
                for field in (
                    "date",
                    "ticker",
                    "dividend_type",
                    "total_value",
                )
            ) and any(
                previous.get(field) != record.get(field)
                for field in (
                    "institution",
                    "occurrence",
                )
            ):
                return True
        return False

    def import_b3_dividend(self, record, choices, batch_sources=()) -> bool:
        key = self.dividend_b3_key(record)
        with closing(self.get_personal_connection()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute(
                "SELECT 1 FROM b3_import_records WHERE source_key=?", (key,)
            ).fetchone():
                return False
            candidates = self._dividend_candidates(conn, record, batch_sources)
            if candidates and key not in choices:
                raise ValueError("Confirme se o pagamento B3 já foi cadastrado antes de importar.")
            choice = choices.get(key)
            receipt_id = choice["id"] if choice else None
            if receipt_id is not None:
                actual = next((row for row in candidates if row["id"] == receipt_id), None)
                if actual is None or actual != choice["expected"]:
                    raise ValueError("O provento escolhido mudou. Revise a importação B3.")
                conn.execute(
                    "UPDATE dividends SET date=?, dividend_type=?, total_value=?, "
                    "quantity=COALESCE(?,quantity), unit_price=COALESCE(?,unit_price) WHERE id=?",
                    (
                        record["date"],
                        record["dividend_type"],
                        record["total_value"],
                        record["quantity"],
                        record["unit_price"],
                        receipt_id,
                    ),
                )
                self._record_dividend_source(
                    conn, key, {"receipt_ids": [receipt_id], "b3": record}, "DIVIDEND_B3"
                )
                conn.commit()
                return True
            conn.row_factory = None
            if (candidates and key in choices) or self._has_distinct_b3_credit(conn, record):
                # "Separate payment" is an explicit user decision, including equal-looking parcels.
                receipt_id = conn.execute(
                    "INSERT INTO dividends "
                    "(date,ticker,dividend_type,total_value,quantity,unit_price) VALUES (?,?,?,?,?,?)",
                    tuple(
                        record[field]
                        for field in (
                            "date",
                            "ticker",
                            "dividend_type",
                            "total_value",
                            "quantity",
                            "unit_price",
                        )
                    ),
                ).lastrowid
                changed = True
            else:
                changed, receipt_id = self._upsert_dividend_receipt(
                    conn,
                    record["date"],
                    record["ticker"],
                    record["dividend_type"],
                    record["total_value"],
                    record["quantity"],
                    record["unit_price"],
                )
            if receipt_id is not None:
                self._record_dividend_source(
                    conn, key, {"receipt_ids": [receipt_id], "b3": record}, "DIVIDEND_B3"
                )
            conn.commit()
            return changed
