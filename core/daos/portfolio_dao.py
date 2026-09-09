import json
import unicodedata

import pandas as pd

from core.database import db


class PortfolioDAO:
    """Data Access Object (DAO) for managing SQLite database access on database/portfolio.db."""

    def __init__(self, db_manager=None):
        self.db = db_manager or db

    def get_personal_connection(self):
        """Delegates and returns an active SQLite database connection."""
        return self.db.get_personal_connection()

    @staticmethod
    def _canonical_source_text(value) -> str:
        return (
            unicodedata.normalize("NFKD", str(value).strip())
            .encode("ascii", "ignore")
            .decode()
            .casefold()
        )

    def import_b3_transaction(self, record: dict, transfer_classifier) -> bool:
        """Persist source identity and ledger effect together under a SQLite write lock."""
        conn = self.get_personal_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing_source = conn.execute(
                "SELECT transaction_id FROM b3_import_records WHERE source_key = ?",
                (record["source_key"],),
            ).fetchone()
            if existing_source:
                if existing_source[0] is not None:
                    record.get("_reconciliation_context", set()).add(existing_source[0])
                return False
            ignored = record["transaction_type"] == "TRANSFER_OUT" or record.get(
                "matched_custody_transfer", False
            )
            if record["event_kind"] == "CUSTODY" and not ignored:
                history = pd.read_sql_query(
                    """
                    SELECT t.*, b.event_kind
                    FROM transactions t
                    LEFT JOIN b3_import_records b ON b.transaction_id = t.id
                    WHERE t.ticker = ? AND t.date < ?
                    ORDER BY t.date, t.id
                    """,
                    conn,
                    params=(record["ticker"], record["date"]),
                )
                ignored = transfer_classifier(history, record["quantity"])
            transaction_id = None
            created = False
            reconciled_legacy = False
            reconciled_b3 = None
            if not ignored:
                values = tuple(
                    record[key]
                    for key in (
                        "date",
                        "ticker",
                        "transaction_type",
                        "quantity",
                        "unit_price",
                        "fees",
                    )
                )
                exact_query = """
                    SELECT id FROM transactions
                    WHERE date=? AND ticker=? AND transaction_type=? AND quantity=?
                      AND unit_price=? AND fees=?
                      AND id NOT IN (SELECT transaction_id FROM b3_import_records WHERE transaction_id IS NOT NULL)
                """
                if record["event_kind"] == "TRADE" and record["cost_status"] == "KNOWN":
                    exact_query += (
                        " AND NOT (transaction_origin='MANUAL' AND unit_price=0 AND fees=0)"
                    )
                if record["cost_status"] == "PENDING":
                    exact_query += " AND transaction_origin NOT IN ('MANUAL', 'LEGACY')"
                existing = conn.execute(exact_query, values).fetchone()
                legacy_custody = None
                if record["event_kind"] == "CUSTODY" and record["cost_status"] == "PENDING":
                    legacy_custody = self._find_legacy_custody_transaction(conn, record)
                    if legacy_custody is not None:
                        existing = (legacy_custody,)
                        reconciled_legacy = True
                elif record["event_kind"] == "TRADE" and record["cost_status"] == "PENDING":
                    legacy_correction = self._find_legacy_parser_correction(conn, record)
                    if legacy_correction is not None:
                        existing = (legacy_correction,)
                        reconciled_legacy = True
                reconciled_b3 = self._find_reconcilable_b3_transaction(conn, record)
                if reconciled_b3 is not None:
                    existing = (reconciled_b3[0],)
                    record.get("_reconciliation_context", set()).add(reconciled_b3[0])
                    conn.execute(
                        "UPDATE transactions SET transaction_origin='B3' WHERE id=? AND transaction_origin='LEGACY'",
                        (reconciled_b3[0],),
                    )
                if existing:
                    transaction_id = existing[0]
                    if record["cost_status"] == "PENDING":
                        conn.execute(
                            "UPDATE transactions SET transaction_origin='B3' WHERE id=? AND transaction_origin='LEGACY'",
                            (transaction_id,),
                        )
                    if reconciled_b3 is not None and (
                        reconciled_b3[1] == "PENDING"
                        or (reconciled_b3[1] == "KNOWN" and reconciled_b3[2])
                    ):
                        conn.execute(
                            "UPDATE transactions SET unit_price=?, fees=?, cost_status=? WHERE id=?",
                            (
                                record["unit_price"],
                                record["fees"],
                                record["cost_status"],
                                transaction_id,
                            ),
                        )
                        if record["cost_status"] == "KNOWN":
                            conn.execute(
                                "UPDATE b3_import_records SET source_key=?, source_record=?, event_kind=?, status=? WHERE transaction_id=?",
                                (
                                    record["source_key"],
                                    record["source_record"],
                                    record["event_kind"],
                                    "IMPORTED",
                                    transaction_id,
                                ),
                            )
                    elif legacy_custody is None and reconciled_b3 is None:
                        conn.execute(
                            "UPDATE transactions SET cost_status=? WHERE id=?",
                            (record["cost_status"], transaction_id),
                        )
                else:
                    cursor = conn.execute(
                        "INSERT INTO transactions (date, ticker, transaction_type, quantity, unit_price, fees, cost_status, transaction_origin) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (*values, record["cost_status"], "B3"),
                    )
                    transaction_id = cursor.lastrowid
                    created = True
            if reconciled_legacy:
                conn.execute(
                    "UPDATE transactions SET transaction_origin='B3' WHERE id=?",
                    (transaction_id,),
                )
                updated = conn.execute(
                    "UPDATE b3_import_records SET source_key=?, source_record=?, event_kind=?, status=? WHERE transaction_id=?",
                    (
                        record["source_key"],
                        record["source_record"],
                        record["event_kind"],
                        "IMPORTED",
                        transaction_id,
                    ),
                ).rowcount
                if updated == 0:
                    conn.execute(
                        "INSERT INTO b3_import_records (source_key, source_record, event_kind, transaction_id, status) VALUES (?, ?, ?, ?, ?)",
                        (
                            record["source_key"],
                            record["source_record"],
                            record["event_kind"],
                            transaction_id,
                            "IMPORTED",
                        ),
                    )
            elif reconciled_b3 is None:
                conn.execute(
                    "INSERT INTO b3_import_records (source_key, source_record, event_kind, transaction_id, status) VALUES (?, ?, ?, ?, ?)",
                    (
                        record["source_key"],
                        record["source_record"],
                        record["event_kind"],
                        transaction_id,
                        "IGNORED" if ignored else "IMPORTED",
                    ),
                )
            conn.commit()
            return created
        finally:
            conn.close()

    @staticmethod
    def _find_legacy_custody_transaction(conn, record: dict) -> int | None:
        """Finds an already-provenanced custody entry with a superseded source key."""
        source = json.loads(record["source_record"])
        candidates = conn.execute(
            """
            SELECT t.id, b.source_record
            FROM transactions t
            JOIN b3_import_records b ON b.transaction_id = t.id
            WHERE t.date = ? AND t.ticker = ? AND t.transaction_type = 'BUY'
              AND t.quantity = ? AND t.unit_price > 0 AND b.event_kind = 'CUSTODY'
            ORDER BY t.id
            """,
            (record["date"], record["ticker"], record["quantity"]),
        ).fetchall()
        for candidate_id, old_source_json in candidates:
            if candidate_id in record.get("_reconciliation_context", set()):
                continue
            old_source = json.loads(old_source_json)
            stable_fields = ("date", "ticker", "quantity", "direction", "institution")
            if all(
                (
                    old_source.get(field) == source.get(field)
                    if field == "quantity"
                    else PortfolioDAO._canonical_source_text(old_source.get(field, ""))
                    == PortfolioDAO._canonical_source_text(source.get(field, ""))
                )
                for field in stable_fields
            ):
                return candidate_id
        return None

    @staticmethod
    def _find_reconcilable_b3_transaction(conn, record: dict) -> tuple[int, str, bool] | None:
        """Finds a B3 transaction whose stable source fields still match."""
        source = json.loads(record["source_record"])
        candidates = conn.execute(
            """
            SELECT t.id, t.cost_status, t.unit_price, t.fees, b.source_record
            FROM transactions t
            JOIN b3_import_records b ON b.transaction_id = t.id
            WHERE t.date = ? AND t.ticker = ? AND t.transaction_type = ?
              AND t.quantity = ? AND t.cost_status IN ('PENDING', 'CORRECTED', 'KNOWN')
              AND b.event_kind = ?
            ORDER BY t.id
            """,
            (
                record["date"],
                record["ticker"],
                record["transaction_type"],
                record["quantity"],
                record["event_kind"],
            ),
        ).fetchall()
        stable_fields = ("date", "ticker", "movement", "direction", "institution")
        matches = []
        for candidate_id, cost_status, unit_price, fees, old_source_json in candidates:
            if candidate_id in record.get("_reconciliation_context", set()):
                continue
            old_source = json.loads(old_source_json)
            same_occurrence = (
                "occurrence" not in old_source
                or "occurrence" not in source
                or old_source["occurrence"] == source["occurrence"]
            )
            same_current_cost = (
                abs(unit_price - record["unit_price"]) < 1e-9 and abs(fees - record["fees"]) < 1e-9
            )
            same_reported_total = (
                old_source.get("price", 0) == 0
                and source.get("price", 0) > 0
                and abs(old_source.get("value", 0) - source.get("value", 0)) < 1e-9
            )
            if (
                cost_status == "KNOWN"
                and record["cost_status"] == "KNOWN"
                and not same_current_cost
                and not same_reported_total
                and not same_occurrence
            ):
                continue
            if all(
                PortfolioDAO._canonical_source_text(old_source.get(field, ""))
                == PortfolioDAO._canonical_source_text(source.get(field, ""))
                for field in stable_fields
            ) and old_source.get("quantity") == source.get("quantity"):
                matches.append(
                    {
                        "id": candidate_id,
                        "status": cost_status,
                        "same_occurrence": same_occurrence,
                        "same_current_cost": same_current_cost,
                        "same_reported_total": same_reported_total,
                        "same_corrected_cost": cost_status == "CORRECTED" and same_current_cost,
                    }
                )
        if record["cost_status"] == "KNOWN":
            exact_known = [
                match
                for match in matches
                if match["status"] == "KNOWN"
                and match["same_current_cost"]
                and match["same_occurrence"]
            ]
            if len(exact_known) == 1:
                return exact_known[0]["id"], exact_known[0]["status"], False
            known_price_population = [
                match
                for match in matches
                if match["status"] == "KNOWN"
                and match["same_reported_total"]
                and match["same_occurrence"]
            ]
            if len(known_price_population) == 1:
                return (
                    known_price_population[0]["id"],
                    known_price_population[0]["status"],
                    True,
                )
            # A changed known cost has no stable identity in a partial export:
            # occurrence numbers are recomputed for each import. Keep the new
            # trade instead of overwriting an existing one without evidence.
            exact_correction = [
                match
                for match in matches
                if match["same_corrected_cost"] and match["same_occurrence"]
            ]
            if len(exact_correction) == 1:
                return exact_correction[0]["id"], exact_correction[0]["status"], False
            corrected_cost = [match for match in matches if match["same_corrected_cost"]]
            if len(corrected_cost) == 1:
                return corrected_cost[0]["id"], corrected_cost[0]["status"], False
            pending_occurrence = [
                match
                for match in matches
                if match["status"] == "PENDING" and match["same_occurrence"]
            ]
            if len(pending_occurrence) == 1:
                return pending_occurrence[0]["id"], pending_occurrence[0]["status"], False
            pending = [match for match in matches if match["status"] == "PENDING"]
            if len(pending) == 1:
                return pending[0]["id"], pending[0]["status"], False
        occurrence_matches = [
            match
            for match in matches
            if match["same_occurrence"]
            and not (
                match["status"] == "KNOWN"
                and record["cost_status"] == "KNOWN"
                and not match["same_current_cost"]
                and not match["same_reported_total"]
            )
        ]
        if len(occurrence_matches) == 1:
            return occurrence_matches[0]["id"], occurrence_matches[0]["status"], False
        return None

    @staticmethod
    def _find_legacy_parser_correction(conn, record: dict) -> int | None:
        """Finds a transaction produced by a known correction in the old B3 parser."""
        legacy_signature = {
            "date": "2021-04-30",
            "ticker": "CXSE3",
            "transaction_type": "BUY",
            "quantity": 340,
            "unit_price": 9.67,
        }
        if any(
            record[field] != legacy_signature[field]
            for field in legacy_signature
            if field != "unit_price"
        ):
            return None
        candidates = conn.execute(
            """
            SELECT t.id
            FROM transactions t
            WHERE t.date = ? AND t.ticker = ? AND t.transaction_type = ?
              AND t.quantity = ? AND t.unit_price = ? AND t.fees = 0
              AND t.transaction_origin = 'LEGACY'
              AND NOT EXISTS (
                  SELECT 1 FROM b3_import_records b WHERE b.transaction_id = t.id
              )
            ORDER BY t.id
            """,
            (
                record["date"],
                record["ticker"],
                record["transaction_type"],
                record["quantity"],
                legacy_signature["unit_price"],
            ),
        ).fetchall()
        return candidates[0][0] if len(candidates) == 1 else None

    def get_pending_costs(self) -> pd.DataFrame:
        conn = self.get_personal_connection()
        try:
            return pd.read_sql_query(
                "SELECT t.id, t.date, t.ticker, t.quantity, b.source_record FROM transactions t JOIN b3_import_records b ON b.transaction_id=t.id WHERE t.cost_status='PENDING' ORDER BY t.date, t.id",
                conn,
            )
        finally:
            conn.close()

    def resolve_pending_cost(self, transaction_id: int, unit_price: float, fees: float) -> bool:
        conn = self.get_personal_connection()
        try:
            cursor = conn.execute(
                "UPDATE transactions SET unit_price=?, fees=?, cost_status='CORRECTED' WHERE id=? AND cost_status='PENDING'",
                (unit_price, fees, transaction_id),
            )
            conn.commit()
            return cursor.rowcount == 1
        finally:
            conn.close()

    def find_transaction(
        self,
        date: str,
        ticker: str,
        transaction_type: str,
        quantity: int,
        unit_price: float,
        fees: float,
    ) -> bool:
        """Returns True if a matching transaction exists in the database."""
        conn = self.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id FROM transactions
                WHERE date = ? AND ticker = ? AND transaction_type = ? AND quantity = ? AND unit_price = ? AND fees = ?
            """,
                (date, ticker, transaction_type, quantity, unit_price, fees),
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def insert_transaction(
        self,
        date: str,
        ticker: str,
        transaction_type: str,
        quantity: int,
        unit_price: float,
        fees: float,
    ) -> bool:
        """Inserts a new transaction into the transactions table."""
        conn = self.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO transactions (date, ticker, transaction_type, quantity, unit_price, fees, transaction_origin)
                VALUES (?, ?, ?, ?, ?, ?, 'MANUAL')
            """,
                (date, ticker, transaction_type, quantity, unit_price, fees),
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def find_dividend(self, date: str, ticker: str, dividend_type: str, total_value: float) -> bool:
        """Returns True if a matching dividend receipt exists in the database."""
        conn = self.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id FROM dividends
                WHERE date = ? AND ticker = ? AND dividend_type = ? AND total_value = ?
            """,
                (date, ticker, dividend_type, total_value),
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def insert_dividend(
        self, date: str, ticker: str, dividend_type: str, total_value: float
    ) -> bool:
        """Inserts a new dividend into the dividends table."""
        conn = self.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO dividends (date, ticker, dividend_type, total_value)
                VALUES (?, ?, ?, ?)
            """,
                (date, ticker, dividend_type, total_value),
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def get_quantity_on_date(self, ticker: str, date_str: str, conn=None) -> int:
        """Returns the sum of quantities owned of a specific ticker on or before a given date."""
        ticker = ticker.upper().strip()
        local_conn = conn if conn is not None else self.get_personal_connection()
        cursor = local_conn.cursor()
        try:
            cursor.execute(
                """
                SELECT transaction_type, quantity
                FROM transactions
                WHERE ticker = ? AND date <= ?
                ORDER BY date ASC, id ASC
            """,
                (ticker, date_str),
            )
            rows = cursor.fetchall()
            qty = 0
            for t_type, q in rows:
                if t_type == "BUY":
                    qty += q
                elif t_type == "SELL":
                    qty = max(0, qty - q)
                elif t_type == "GROUP":
                    qty = q
            return qty
        finally:
            if conn is None:
                local_conn.close()

    def get_transactions_by_ticker(self, ticker: str) -> pd.DataFrame:
        """Returns all transactions for a ticker as a DataFrame."""
        ticker = ticker.upper().strip()
        conn = self.get_personal_connection()
        try:
            return pd.read_sql_query(
                "SELECT t.date, CASE WHEN b.event_kind='CUSTODY' THEN 'TRANSFER_IN' ELSE t.transaction_type END AS transaction_type, t.quantity, t.unit_price, t.fees, t.cost_status, b.event_kind FROM transactions t LEFT JOIN b3_import_records b ON b.transaction_id=t.id WHERE t.ticker = ? ORDER BY t.date, t.id",
                conn,
                params=(ticker,),
            )
        finally:
            conn.close()

    def get_transactions_by_ticker_desc(self, ticker: str) -> pd.DataFrame:
        """Returns all transactions for a specific asset ordered by date descending."""
        ticker = ticker.upper().strip()
        conn = self.get_personal_connection()
        try:
            return pd.read_sql_query(
                "SELECT date as Data, "
                "CASE WHEN EXISTS (SELECT 1 FROM b3_import_records b WHERE b.transaction_id=transactions.id AND b.event_kind='CUSTODY') THEN 'Transferência recebida' "
                "     WHEN transaction_type='BUY' THEN 'Compra' "
                "     WHEN transaction_type='SELL' THEN 'Venda' "
                "     ELSE 'Grupamento' END as Operação, "
                "quantity as Quantidade, unit_price as [Valor Unitário], "
                "CASE WHEN transaction_type='SELL' "
                "     THEN (quantity * unit_price - fees) "
                "     ELSE (quantity * unit_price + fees) END as [Valor Total], "
                "CASE WHEN cost_status='PENDING' THEN 'Custo pendente' WHEN cost_status='CORRECTED' THEN 'Regularizado' ELSE 'Informado' END AS [Situação do custo] "
                "FROM transactions WHERE ticker = ? ORDER BY date DESC",
                conn,
                params=(ticker,),
            )
        finally:
            conn.close()

    def get_dividends_by_ticker(self, ticker: str) -> pd.DataFrame:
        """Returns all dividends for a ticker as a DataFrame."""
        ticker = ticker.upper().strip()
        conn = self.get_personal_connection()
        try:
            return pd.read_sql_query(
                "SELECT date as Data, CASE WHEN dividend_type='DIVIDEND' THEN 'Dividendo' WHEN dividend_type='JCP' THEN 'JCP' ELSE 'Rendimento' END as Tipo, total_value as Total FROM dividends WHERE ticker = ? ORDER BY date DESC",
                conn,
                params=(ticker,),
            )
        finally:
            conn.close()

    def get_years_with_dividends(self) -> list:
        """Returns a sorted list of unique years in dividends table."""
        conn = self.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT DISTINCT strftime('%Y', date) as yr FROM dividends WHERE date IS NOT NULL ORDER BY yr DESC"
            )
            return [row[0] for row in cursor.fetchall() if row[0] is not None]
        finally:
            conn.close()

    def get_asset_years_with_dividends(self, ticker: str) -> list:
        """Returns unique dividend years for a specific ticker."""
        ticker = ticker.upper().strip()
        conn = self.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT DISTINCT strftime('%Y', date) as yr FROM dividends WHERE ticker = ? AND date IS NOT NULL ORDER BY yr DESC",
                (ticker,),
            )
            return [row[0] for row in cursor.fetchall() if row[0] is not None]
        finally:
            conn.close()

    def get_annual_dividend_types_sum(self, year: str) -> list:
        """Returns aggregated SUM of dividend types for a specific year."""
        conn = self.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT dividend_type, SUM(total_value)
                FROM dividends
                WHERE strftime('%Y', date) = ?
                GROUP BY dividend_type
            """,
                (year,),
            )
            return cursor.fetchall()
        finally:
            conn.close()

    def get_asset_annual_dividend_types_sum(self, ticker: str, year: str) -> list:
        """Returns aggregated SUM of dividend types for a specific ticker and year."""
        ticker = ticker.upper().strip()
        conn = self.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT dividend_type, SUM(total_value)
                FROM dividends
                WHERE ticker = ? AND strftime('%Y', date) = ?
                GROUP BY dividend_type
            """,
                (ticker, year),
            )
            return cursor.fetchall()
        finally:
            conn.close()

    def get_tracked_assets(self) -> list:
        """Returns watchlist tickers from tracked_market_assets."""
        conn = self.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT ticker FROM tracked_market_assets ORDER BY ticker ASC")
            return [row[0] for row in cursor.fetchall()]
        finally:
            conn.close()

    def insert_tracked_asset(self, ticker: str) -> bool:
        """Inserts or replaces a tracked asset in the database."""
        conn = self.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT OR REPLACE INTO tracked_market_assets (ticker) VALUES (?)",
                (ticker.upper().strip(),),
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def delete_tracked_asset(self, ticker: str) -> bool:
        """Removes a tracked asset from tracked_market_assets."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "DELETE FROM tracked_market_assets WHERE ticker = ?", (ticker.upper().strip(),)
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def insert_dividend_correction(self, ticker: str, year: int, total_value: float) -> bool:
        """Inserts or replaces a manual dividend correction."""
        conn = self.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT OR REPLACE INTO dividend_corrections (ticker, year, total_value) VALUES (?, ?, ?)",
                (ticker.upper().strip(), int(year), float(total_value)),
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def get_dividend_corrections(self, ticker: str) -> dict:
        """Returns registered dividend corrections for a specific ticker."""
        conn = self.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT year, total_value FROM dividend_corrections WHERE ticker = ? ORDER BY year DESC",
                (ticker.upper().strip(),),
            )
            return {row[0]: row[1] for row in cursor.fetchall()}
        except Exception:
            return {}
        finally:
            conn.close()

    def get_all_transactions(self) -> pd.DataFrame:
        """Returns all transactions in the database."""
        conn = self.get_personal_connection()
        try:
            return pd.read_sql_query(
                "SELECT t.date, t.ticker, t.transaction_type, t.quantity, t.unit_price, t.fees, t.cost_status, b.event_kind FROM transactions t LEFT JOIN b3_import_records b ON b.transaction_id=t.id ORDER BY t.date, t.id",
                conn,
            )
        finally:
            conn.close()

    def get_total_dividends_by_ticker(self, ticker: str) -> float:
        """Returns total dividends sum for a specific ticker."""
        ticker = ticker.upper().strip()
        conn = self.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT SUM(total_value) FROM dividends WHERE ticker = ?", (ticker,))
            res = cursor.fetchone()
            return res[0] if res and res[0] is not None else 0.0
        finally:
            conn.close()

    def get_dividends_by_ticker_since_date(self, ticker: str, limit_date: str) -> float:
        """Returns dividends sum since a specific date for a ticker."""
        ticker = ticker.upper().strip()
        conn = self.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT SUM(total_value) FROM dividends WHERE ticker = ? AND date >= ?",
                (ticker, limit_date),
            )
            res = cursor.fetchone()
            return res[0] if res and res[0] is not None else 0.0
        finally:
            conn.close()

    def get_all_dividends(self) -> pd.DataFrame:
        """Returns all dividends in the database."""
        conn = self.get_personal_connection()
        try:
            return pd.read_sql_query("SELECT date, dividend_type, total_value FROM dividends", conn)
        finally:
            conn.close()

    def get_ytd_contributions_sum(self, limit_date: str) -> float:
        """Returns sum of net buy transactions on or after a given date."""
        conn = self.get_personal_connection()
        cursor = conn.cursor()
        try:
            pending = cursor.execute(
                """
                SELECT 1 FROM transactions
                WHERE transaction_type = 'BUY' AND date >= ? AND cost_status = 'PENDING'
                  AND NOT EXISTS (
                      SELECT 1 FROM b3_import_records b
                      WHERE b.transaction_id = transactions.id AND b.event_kind = 'CUSTODY'
                  )
                LIMIT 1
                """,
                (limit_date,),
            ).fetchone()
            if pending:
                return None
            cursor.execute(
                "SELECT SUM(quantity * unit_price + fees) FROM transactions WHERE transaction_type = 'BUY' AND date >= ? AND NOT EXISTS (SELECT 1 FROM b3_import_records b WHERE b.transaction_id=transactions.id AND b.event_kind='CUSTODY')",
                (limit_date,),
            )
            res = cursor.fetchone()
            return res[0] if res and res[0] is not None else 0.0
        finally:
            conn.close()

    def get_all_buy_transactions(self) -> pd.DataFrame:
        """Returns all buy transactions in the database."""
        conn = self.get_personal_connection()
        try:
            return pd.read_sql_query(
                "SELECT date, quantity, unit_price, fees, cost_status FROM transactions WHERE transaction_type = 'BUY' AND NOT EXISTS (SELECT 1 FROM b3_import_records b WHERE b.transaction_id=transactions.id AND b.event_kind='CUSTODY')",
                conn,
            )
        finally:
            conn.close()

    def initialize_tables(self, conn) -> None:
        """Creates tables, runs migrations, and seeds defaults for the Portfolio/Transaction domain."""
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                ticker TEXT NOT NULL,
                transaction_type TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                fees REAL DEFAULT 0.0,
                transaction_origin TEXT NOT NULL DEFAULT 'LEGACY'
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dividends (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                ticker TEXT NOT NULL,
                dividend_type TEXT NOT NULL,
                total_value REAL NOT NULL
            )
        """)

        columns = {row[1] for row in cursor.execute("PRAGMA table_info(transactions)")}
        if "cost_status" not in columns:
            cursor.execute(
                "ALTER TABLE transactions ADD COLUMN cost_status TEXT NOT NULL DEFAULT 'KNOWN'"
            )
        if "transaction_origin" not in columns:
            cursor.execute(
                "ALTER TABLE transactions ADD COLUMN transaction_origin TEXT NOT NULL DEFAULT 'LEGACY'"
            )
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS b3_import_records (
                source_key TEXT PRIMARY KEY,
                source_record TEXT NOT NULL,
                event_kind TEXT NOT NULL,
                transaction_id INTEGER UNIQUE,
                status TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tracked_market_assets (
                ticker TEXT PRIMARY KEY
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dividend_corrections (
                ticker TEXT NOT NULL,
                year INTEGER NOT NULL,
                total_value REAL NOT NULL,
                PRIMARY KEY (ticker, year)
            )
        """)

        # Pre-seed BBAS3 and BBDC3 values if empty to keep out-of-the-box accuracy without Python hardcoding
        cursor.execute("SELECT COUNT(*) FROM dividend_corrections")
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "INSERT OR REPLACE INTO dividend_corrections (ticker, year, total_value) VALUES ('BBAS3', 2023, 2.29)"
            )
            cursor.execute(
                "INSERT OR REPLACE INTO dividend_corrections (ticker, year, total_value) VALUES ('BBAS3', 2024, 2.61)"
            )
            cursor.execute(
                "INSERT OR REPLACE INTO dividend_corrections (ticker, year, total_value) VALUES ('BBDC3', 2023, 1.54)"
            )
            cursor.execute(
                "INSERT OR REPLACE INTO dividend_corrections (ticker, year, total_value) VALUES ('BBDC3', 2024, 1.01)"
            )


# Register schema self-registration provider
db.register_schema(PortfolioDAO())
