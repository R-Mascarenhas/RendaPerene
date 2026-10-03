import datetime
import json
import logging
import math
from bisect import bisect_left, bisect_right
from decimal import Decimal
from itertools import groupby

import pandas as pd

from core.activity import ACTIVITY_EVENTS, activity_event
from core.daos.portfolio_dao import PortfolioDAO
from core.ports import (
    ExcelParserPort,
    MarketAnalysisPort,
    MarketDataPort,
    PlanningProviderPort,
    PortfolioPort,
    hybridmethod,
)
from core.strings import MODEL_IPCA_SPREAD, MODEL_SELIC
from core.utils.market_data import MarketData
from core.utils.ticker import normalize_b3_ticker
from services.valuation_service import ValuationService

logger = logging.getLogger(__name__)
_MAX_B3_SUBSET_STATES = 65_536


class AssetService:
    """Domain Service for managing assets, transactions, dividends, and positions (Single Source of Truth)."""

    def __init__(
        self,
        portfolio_repo: PortfolioPort = None,
        market_data_api: MarketDataPort = None,
        market_analysis_api: MarketAnalysisPort = None,
        excel_parser: ExcelParserPort = None,
        planning_provider: PlanningProviderPort = None,
    ):
        self._portfolio_repo = portfolio_repo or PortfolioDAO()
        self._market_data_api = market_data_api or MarketData
        self._market_analysis_api = market_analysis_api
        self._excel_parser = excel_parser
        self._planning_provider = planning_provider

    # Default instance for backwards compatibility in presentation layers
    _default_instance = None

    @classmethod
    def get_default(cls):
        if cls._default_instance is None:
            cls._default_instance = cls()
        return cls._default_instance

    @classmethod
    def set_adapters(
        cls,
        portfolio_repo: PortfolioPort = None,
        market_data_api: MarketDataPort = None,
        market_analysis_api: MarketAnalysisPort = None,
        excel_parser: ExcelParserPort = None,
        planning_provider: PlanningProviderPort = None,
    ):
        """Dynamic dependency injection mechanism for testing and custom environment mocks."""
        inst = cls.get_default()
        if portfolio_repo is not None:
            inst._portfolio_repo = portfolio_repo
        if market_data_api is not None:
            inst._market_data_api = market_data_api
        if market_analysis_api is not None:
            inst._market_analysis_api = market_analysis_api
        if excel_parser is not None:
            inst._excel_parser = excel_parser
        if planning_provider is not None:
            inst._planning_provider = planning_provider

    @hybridmethod
    def get_local_projection_revision(self) -> int:
        """Return the current portfolio revision for temporary local projections."""
        return self._portfolio_repo.get_local_projection_revision()

    @hybridmethod
    def add_transaction(
        self,
        ticker: str,
        date: str,
        transaction_type: str,
        quantity: int,
        unit_price: float,
        fees: float = 0.0,
    ) -> bool:
        """Inserts a Buy (BUY), Sell (SELL), or Group (GROUP) asset transaction into the personal database, avoiding duplicates."""
        ticker = normalize_b3_ticker(ticker)
        if transaction_type in ("Compra", "BUY"):
            transaction_type = "BUY"
        elif transaction_type in ("Venda", "SELL"):
            transaction_type = "SELL"
        elif transaction_type in ("Grupamento", "GROUP"):
            transaction_type = "GROUP"

        if quantity <= 0:
            return False  # Quantity must be strictly positive

        if self._portfolio_repo.find_transaction(
            date, ticker, transaction_type, quantity, unit_price, fees
        ):
            return False  # Skipped duplicate

        success = self._portfolio_repo.insert_transaction(
            date, ticker, transaction_type, quantity, unit_price, fees
        )
        if success:
            logger.info("portfolio.transaction_saved")
            logger.debug(
                "portfolio.transaction_context type=%s",
                transaction_type,
            )
        if success and transaction_type == "SELL":
            try:
                df_positions = self.calculate_positions()
                if df_positions.empty or ticker not in df_positions["ticker"].values:
                    # Seamlessly transition a zeroed out owned stock to manual tracking so it stays on radar but is removable
                    self.add_tracked_market_asset(ticker)
            except Exception as error:
                logger.warning(
                    "portfolio.auto_tracking_failed error_type=%s",
                    type(error).__name__,
                )
        return success

    @hybridmethod
    def add_dividend(
        self,
        ticker: str,
        date: str,
        dividend_type: str,
        total_value: float,
        quantity: float | None = None,
        unit_price: float | None = None,
    ) -> bool:
        """Save a receipt or complete its missing B3 metadata without duplicating its total."""
        ticker = ticker.strip().upper()
        if dividend_type in ("Dividendo", "DIVIDEND"):
            dividend_type = "DIVIDEND"
        elif dividend_type in ("JCP", "JCP"):
            dividend_type = "JCP"
        elif dividend_type in ("Rendimento", "YIELD"):
            dividend_type = "YIELD"

        success = self._portfolio_repo.insert_dividend(
            date,
            ticker,
            dividend_type,
            total_value,
            self._positive_number(quantity),
            self._positive_number(unit_price),
        )
        if success:
            logger.info("portfolio.dividend_saved")
            logger.debug(
                "portfolio.dividend_context type=%s",
                dividend_type,
            )
        return success

    @hybridmethod
    def process_b3_import(
        self,
        df: pd.DataFrame,
        progress_callback=None,
        manual_trade_links: dict[str, int | list[int]] | None = None,
    ) -> tuple[int, int]:
        """Processes a DataFrame imported from B3, routing and translating row categories to English."""
        if self._excel_parser is None:
            raise RuntimeError("No ExcelParserPort adapter was injected into AssetService.")

        transactions_df, dividends_df = self._excel_parser.parse_b3_excel(
            df, progress_callback=progress_callback
        )

        processed_transactions = 0
        processed_dividends = 0
        reconciliation_context = set()
        import_occurrence_counts = {}
        for record in transactions_df.to_dict("records"):
            if not record.get("source_key") or not record.get("source_record"):
                continue
            source = json.loads(record["source_record"])
            identity = (
                record["date"],
                record["ticker"],
                record["transaction_type"],
                record["quantity"],
                source.get("movement", ""),
                source.get("direction", ""),
                source.get("institution", ""),
            )
            import_occurrence_counts[identity] = import_occurrence_counts.get(identity, 0) + 1

        # Record standardized transactions
        if not transactions_df.empty:
            transactions_df = transactions_df.sort_values("date", kind="stable")
        for _, row in transactions_df.iterrows():
            if row.get("source_key"):
                record = row.to_dict()
                record["_reconciliation_context"] = reconciliation_context
                if manual_trade_links:
                    record["_manual_transaction_id"] = manual_trade_links.get(record["source_key"])
                if not record.get("source_record"):
                    continue
                source = json.loads(record["source_record"])
                identity = (
                    record["date"],
                    record["ticker"],
                    record["transaction_type"],
                    record["quantity"],
                    source.get("movement", ""),
                    source.get("direction", ""),
                    source.get("institution", ""),
                )
                record["_import_occurrence_count"] = import_occurrence_counts[identity]
                success = self._portfolio_repo.import_b3_transaction(
                    record, self._has_sufficient_cost_history
                )
                if (
                    success
                    and row["transaction_type"] == "SELL"
                    and self.get_quantity_on_date(row["ticker"], row["date"]) == 0
                ):
                    self.add_tracked_market_asset(row["ticker"])
            else:
                success = self.add_transaction(
                    ticker=row["ticker"],
                    date=row["date"],
                    transaction_type=row["transaction_type"],
                    quantity=row["quantity"],
                    unit_price=row["unit_price"],
                    fees=row["fees"],
                )
            if success:
                processed_transactions += 1

        # Record standardized dividends
        for _, row in dividends_df.iterrows():
            success = self.add_dividend(
                ticker=row["ticker"],
                date=row["date"],
                dividend_type=row["dividend_type"],
                total_value=row["total_value"],
                quantity=row.get("quantity"),
                unit_price=row.get("unit_price"),
            )
            if success:
                processed_dividends += 1

        logger.info(
            "b3_import.completed transactions=%s dividends=%s",
            processed_transactions,
            processed_dividends,
        )
        return processed_transactions, processed_dividends

    @hybridmethod
    def find_b3_manual_trade_candidates(self, df: pd.DataFrame) -> list[dict]:
        """Find reviewable manual trade candidates without changing the portfolio."""
        if self._excel_parser is None:
            raise RuntimeError("No ExcelParserPort adapter was injected into AssetService.")
        transactions, _ = self._excel_parser.parse_b3_excel(df)
        candidates = []
        for record in transactions.to_dict("records"):
            if record.get("event_kind") != "TRADE" or record.get("cost_status") != "KNOWN":
                continue
            source = json.loads(record["source_record"])
            manual_records = self._portfolio_repo.get_manual_trade_candidates(record)
            groups = self._find_matching_manual_groups(manual_records, record, source)
            if groups:
                candidates.append(
                    {
                        "source_key": record["source_key"],
                        "b3": {
                            "date": record["date"],
                            "ticker": record["ticker"],
                            "transaction_type": record["transaction_type"],
                            "quantity": record["quantity"],
                            "unit_price": record["unit_price"],
                            "value": source.get("value"),
                            "institution": source.get("institution", ""),
                        },
                        "manual_candidates": [
                            group["transactions"][0]
                            for group in groups
                            if len(group["transactions"]) == 1
                        ],
                        "manual_groups": groups,
                    }
                )
        return candidates

    @staticmethod
    def _find_matching_manual_groups(manual_records, record, source):
        """Match bounded half-subsets; abort rather than report an incomplete search as unmatched."""
        ordered = sorted(manual_records, key=lambda item: (item["date"], item["id"]))
        quantity = int(record["quantity"])
        groups = []
        reported_value = source.get("value")
        tolerance = max(0.02, quantity * 0.0005 + 0.01)
        price = Decimal(str(record["unit_price"]))
        price_margin = Decimal("0.0005") + Decimal("1e-12")
        lower_value = quantity * (price - price_margin)
        upper_value = quantity * (price + price_margin)
        if reported_value is not None:
            value = Decimal(str(reported_value))
            lower_value = max(lower_value, value - Decimal(str(tolerance)))
            upper_value = min(upper_value, value + Decimal(str(tolerance)))
        # Widen only the lookup range; final validation uses the DAO's float comparisons.
        lower_value -= Decimal("1e-8")
        upper_value += Decimal("1e-8")

        def search_limit_reached():
            raise ValueError(
                "Há muitos lançamentos manuais para comparar com segurança. "
                "A importação foi interrompida antes de gravar qualquer linha. "
                "Revise os lançamentos desse ativo antes de tentar novamente."
            )

        def subsets(rows):
            states = [(0, Decimal(0), ())]
            visited_states = 0
            for item in rows:
                item_quantity = int(item["quantity"])
                item_value = item_quantity * Decimal(str(item["unit_price"]))
                previous_count = len(states)
                for index in range(previous_count):
                    visited_states += 1
                    if visited_states > _MAX_B3_SUBSET_STATES:
                        search_limit_reached()
                    selected_quantity, selected_value, selected = states[index]
                    combined_quantity = selected_quantity + item_quantity
                    if combined_quantity > quantity:
                        continue
                    if len(states) >= _MAX_B3_SUBSET_STATES:
                        search_limit_reached()
                    states.append(
                        (combined_quantity, selected_value + item_value, (*selected, item))
                    )
            return states

        inspected_pairs = 0
        for _, dated_records in groupby(ordered, key=lambda item: item["date"]):
            rows = [item for item in dated_records if int(item["quantity"]) <= quantity]
            middle = len(rows) // 2
            left_states = subsets(rows[:middle])
            right_by_quantity = {}
            for selected_quantity, selected_value, selected in subsets(rows[middle:]):
                right_by_quantity.setdefault(selected_quantity, []).append(
                    (selected_value, selected)
                )
            right_values = {}
            for selected_quantity, selections in right_by_quantity.items():
                selections.sort(key=lambda selection: selection[0])
                right_values[selected_quantity] = [selection[0] for selection in selections]
            for selected_quantity, selected_value, selected in left_states:
                complementary_quantity = quantity - selected_quantity
                selections = right_by_quantity.get(complementary_quantity, [])
                values = right_values.get(complementary_quantity, [])
                start = bisect_left(values, lower_value - selected_value)
                end = bisect_right(values, upper_value - selected_value)
                for index in range(start, end):
                    inspected_pairs += 1
                    if inspected_pairs > _MAX_B3_SUBSET_STATES:
                        search_limit_reached()
                    transactions = [*selected, *selections[index][1]]
                    total_value = sum(
                        int(tx["quantity"]) * float(tx["unit_price"]) for tx in transactions
                    )
                    average = total_value / quantity
                    if abs(average - float(record["unit_price"])) > 0.0005 + 1e-12:
                        continue
                    if (
                        reported_value is not None
                        and abs(float(reported_value) - total_value) > tolerance
                    ):
                        continue
                    groups.append(
                        {
                            "ids": [int(tx["id"]) for tx in transactions],
                            "transactions": transactions,
                            "quantity": quantity,
                            "weighted_unit_price": average,
                            "total_value": total_value,
                        }
                    )
                    if len(groups) == 25:
                        return groups
        return groups

    @staticmethod
    def _has_sufficient_cost_history(history: pd.DataFrame, required_quantity: int) -> bool:
        quantity, known_quantity, known_zero_cost_quantity, cost = 0, 0.0, 0.0, 0.0
        for row in history.to_dict("records"):
            qty = row["quantity"]
            if row["transaction_type"] == "BUY":
                if row.get("cost_status") != "PENDING":
                    is_zero_cost_deposit = (
                        row.get("event_kind") == "TRADE" and row["unit_price"] == 0
                    )
                    quantity_factor = known_quantity / quantity if quantity > 0 else 1.0
                    known_quantity += (
                        qty
                        if is_zero_cost_deposit
                        else qty * quantity_factor
                        if row["unit_price"] == 0
                        else qty
                    )
                    if is_zero_cost_deposit:
                        known_zero_cost_quantity += qty
                    elif row.get("event_kind") != "TRADE" and row["unit_price"] == 0:
                        known_zero_cost_quantity += (
                            qty * quantity_factor if known_zero_cost_quantity > 0 else 0.0
                        )
                    cost += qty * row["unit_price"] + row["fees"]
                quantity += qty
            elif row["transaction_type"] == "SELL":
                remaining = max(0, quantity - qty)
                cost = cost * remaining / quantity if quantity else 0.0
                known_quantity = known_quantity * remaining / quantity if quantity else 0.0
                known_zero_cost_quantity = (
                    known_zero_cost_quantity * remaining / quantity if quantity else 0.0
                )
                quantity = remaining
            elif row["transaction_type"] == "GROUP":
                known_quantity = known_quantity * qty / quantity if quantity else 0.0
                known_zero_cost_quantity = (
                    known_zero_cost_quantity * qty / quantity if quantity else 0.0
                )
                quantity = qty
        return known_quantity >= required_quantity and (
            cost > 0 or known_zero_cost_quantity >= required_quantity
        )

    @hybridmethod
    def get_pending_costs(self) -> pd.DataFrame:
        pending = self._portfolio_repo.get_pending_costs()
        for field in ("movement", "institution"):
            pending[field] = pending["source_record"].map(
                lambda source: json.loads(source).get(field, "")
            )
        return pending

    @hybridmethod
    def get_pending_tickers(self) -> str:
        pending_costs = self.get_pending_costs()
        if pending_costs.empty:
            return ""
        active_positions = self.calculate_positions()
        active_pending = set(active_positions.loc[active_positions["cost_pending"], "ticker"])
        return ", ".join(sorted(set(pending_costs["ticker"]) & active_pending))

    @hybridmethod
    def regularize_cost(
        self, transaction_id: int, value: float, *, value_is_total: bool = False, fees: float = 0.0
    ) -> bool:
        if not math.isfinite(value) or value <= 0 or not math.isfinite(fees) or fees < 0:
            raise ValueError(
                "Informe um custo positivo e taxas não negativas, com valores finitos."
            )
        pending = self.get_pending_costs()
        selected = pending[pending["id"] == transaction_id]
        if selected.empty:
            return False
        quantity = int(selected.iloc[0]["quantity"])
        price = value / quantity if value_is_total else value
        if not math.isfinite(price * quantity + fees):
            raise ValueError("O custo total informado excede o limite permitido.")
        return self._portfolio_repo.resolve_pending_cost(transaction_id, price, fees)

    @hybridmethod
    def get_quantity_on_date(self, ticker: str, date_str: str, conn=None) -> int:
        """Returns the accumulated quantity owned of a specific ticker on a given date."""
        return self._portfolio_repo.get_quantity_on_date(ticker, date_str, conn=conn)

    @hybridmethod
    def get_owned_tickers(self) -> list[str]:
        """Returns tickers with a positive current position."""
        df_positions = self.calculate_positions()
        if df_positions.empty or "ticker" not in df_positions.columns:
            return []
        if "quantity" not in df_positions.columns:
            return df_positions["ticker"].tolist()
        return df_positions.loc[df_positions["quantity"] > 0, "ticker"].tolist()

    @staticmethod
    def _positive_number(value) -> float | None:
        """Accept usable numeric metadata without converting missing values to zero."""
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) and number > 0 else None

    def _receipt_unit_value(
        self, ticker, date, total, quantity=None, unit_price=None, conn=None
    ) -> float | None:
        """Prefer reported prices, then reported quantities, then the legacy historical basis."""
        price = self._positive_number(unit_price)
        if price is not None:
            return price
        total = self._positive_number(total)
        if total is None:
            return None
        basis = self._positive_number(quantity)
        if basis is None:
            basis = self._positive_number(
                self._portfolio_repo.get_quantity_on_date(ticker, date, conn=conn)
            )
        return self._positive_number(total / basis) if basis is not None else None

    @hybridmethod
    def get_portfolio_activity(self, limit: int | None = 10) -> pd.DataFrame:
        """Return recent financial activities without changing portfolio calculations.

        Dates descend; same-day ties use transactions before dividends, then newest ID.
        A None limit returns the full history. Read failures propagate to the caller.
        """
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit < 0
        ):
            raise ValueError("Activity limit must be a non-negative integer or None")
        records = self._portfolio_repo.get_activity_records(limit)
        return self._prepare_activity(records)

    @hybridmethod
    def get_activity_filter_options(self) -> dict:
        """Expose recorded tickers without loading or calculating historical activities."""
        return {"tickers": self._portfolio_repo.get_activity_tickers(), "events": ACTIVITY_EVENTS}

    @hybridmethod
    def get_activity_page(
        self,
        page: int = 1,
        start_date=None,
        end_date=None,
        event=None,
        ticker=None,
    ) -> dict:
        """Read one filtered page; date bounds include both endpoints."""
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise ValueError("A página deve ser um inteiro positivo.")
        dates = []
        for value in (start_date, end_date):
            if value is None:
                dates.append(None)
                continue
            try:
                dates.append(datetime.date.fromisoformat(str(value)).isoformat())
            except (TypeError, ValueError):
                raise ValueError("Informe uma data válida.") from None
        start_date, end_date = dates
        if start_date and end_date and start_date > end_date:
            raise ValueError("A data inicial deve ser anterior ou igual à data final.")
        if event is not None and event not in ACTIVITY_EVENTS:
            raise ValueError("Selecione um evento válido.")
        if ticker is not None:
            ticker = normalize_b3_ticker(ticker)
        result = self._portfolio_repo.get_activity_page_records(
            page,
            start_date,
            end_date,
            event,
            ticker,
        )
        result["activity"] = self._prepare_activity(result.pop("records"))
        return result

    def _prepare_activity(self, records: pd.DataFrame) -> pd.DataFrame:
        """Calculate values and receipt estimates only for the records being displayed."""
        activities = []
        for row in records.to_dict("records"):
            event = activity_event(row)
            value_status = "known"
            quantity = row["quantity"]
            quantity_status = "reported"
            if row["source"] == "dividend":
                value = row["total_value"]
                quantity = self._positive_number(quantity)
                if quantity is None:
                    price = self._receipt_unit_value(
                        row["ticker"], row["date"], value, unit_price=row["unit_price"]
                    )
                    quantity = self._positive_number(value / price) if price is not None else None
                    quantity_status = "estimated" if quantity is not None else "unavailable"
            elif row["event_kind"] == "CUSTODY":
                value = None
                value_status = "not_applicable"
            elif row["cost_status"] == "PENDING":
                value = None
                value_status = "pending"
            elif (
                row["event_type"] == "GROUP"
                or row["event_kind"] == "CORPORATE"
                or (
                    row["event_type"] == "BUY"
                    and pd.isna(row["event_kind"])
                    and row["unit_price"] == 0
                    and row["fees"] == 0
                )
            ):
                value = 0.0
            else:
                gross = row["quantity"] * row["unit_price"]
                value = gross - row["fees"] if row["event_type"] == "SELL" else gross + row["fees"]
            activities.append(
                {
                    "date": row["date"],
                    "event": event,
                    "ticker": row["ticker"],
                    "quantity": quantity,
                    "quantity_status": quantity_status,
                    "value": value,
                    "value_status": value_status,
                }
            )
        return pd.DataFrame(
            activities,
            columns=[
                "date",
                "event",
                "ticker",
                "quantity",
                "quantity_status",
                "value",
                "value_status",
            ],
        )

    @hybridmethod
    def get_asset_transactions(self, ticker: str) -> pd.DataFrame:
        """Returns all transactions for a specific asset ordered by date descending."""
        return self._portfolio_repo.get_transactions_by_ticker_desc(ticker)

    @hybridmethod
    def get_asset_dividends(self, ticker: str) -> pd.DataFrame:
        """Returns all dividend receipts for a specific asset."""
        return self._portfolio_repo.get_dividends_by_ticker(ticker)

    @hybridmethod
    def get_asset_dividends_detailed(self, ticker: str) -> pd.DataFrame:
        """
        Returns all dividend receipts for a specific asset, pre-calculating the
        exact unit value owned on each receipt date.
        """
        df_div = self._portfolio_repo.get_dividends_by_ticker(ticker)
        if df_div.empty:
            return df_div

        unit_vals = []
        conn_shared = self._portfolio_repo.get_personal_connection()
        try:
            for _, row in df_div.iterrows():
                dt = row["Data"]
                total = row["Total"]
                unit_value = self._receipt_unit_value(
                    ticker,
                    dt,
                    total,
                    quantity=row.get("quantity"),
                    unit_price=row.get("unit_price"),
                    conn=conn_shared,
                )
                unit_vals.append(unit_value if unit_value is not None else 0.0)
        finally:
            conn_shared.close()

        df_div_display = df_div.copy()
        df_div_display["Unitário"] = unit_vals
        df_div_display = df_div_display[["Data", "Tipo", "Unitário", "Total"]]
        return df_div_display

    @hybridmethod
    def get_annual_dividends_metrics(
        self, ticker: str, chosen_year: str, df_div: pd.DataFrame
    ) -> dict:
        """
        Calculates annual dividend metrics including total paid per share and
        end of year/previous year quantities for comparison.
        """
        total_paid_per_share = 0.0
        conn_shared = self._portfolio_repo.get_personal_connection()
        try:
            if not df_div.empty:
                df_div_year = df_div[df_div["Data"].str.startswith(chosen_year)]
                for _, row in df_div_year.iterrows():
                    unit_value = self._receipt_unit_value(
                        ticker,
                        row["Data"],
                        row["Total"],
                        quantity=row.get("quantity"),
                        unit_price=row.get("unit_price"),
                        conn=conn_shared,
                    )
                    if unit_value is not None:
                        total_paid_per_share += unit_value

            qty_end_of_year = self._portfolio_repo.get_quantity_on_date(
                ticker, f"{chosen_year}-12-31", conn=conn_shared
            )
            prev_year = str(int(chosen_year) - 1)
            qty_prev_year = self._portfolio_repo.get_quantity_on_date(
                ticker, f"{prev_year}-12-31", conn=conn_shared
            )
        finally:
            conn_shared.close()

        return {
            "total_paid_per_share": total_paid_per_share,
            "qty_end_of_year": qty_end_of_year,
            "qty_prev_year": qty_prev_year,
            "prev_year": prev_year,
        }

    @hybridmethod
    def get_raw_transactions_for_chart(self, ticker: str) -> pd.DataFrame:
        """Returns raw historical transactions sorted by date ascending for charts."""
        return self._portfolio_repo.get_transactions_by_ticker(ticker)

    @hybridmethod
    def get_asset_metadata(self, ticker: str) -> dict:
        """Return catalog metadata or neutral display metadata for an uncatalogued ticker."""
        ticker = ticker.strip().upper()
        catalog = self._market_data_api.load_assets_catalog()
        return self._resolve_asset_metadata(catalog, ticker)

    @staticmethod
    def _resolve_asset_metadata(catalog: pd.DataFrame, ticker: str) -> dict:
        if not catalog.empty and ticker in catalog.index:
            row = catalog.loc[ticker]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            return {
                "name": str(row.get("NOME", "Nome não disponível")),
                "image": str(row.get("IMAGEM", "")) if pd.notna(row.get("IMAGEM")) else "",
                "cnpj": str(row.get("CNPJ", "N/D")) if pd.notna(row.get("CNPJ")) else "N/D",
                "sector": str(row.get("SETOR ECONÔMICO", "Outros"))
                if pd.notna(row.get("SETOR ECONÔMICO"))
                else "Outros",
                "sub_sector": str(row.get("SUBSETOR", "")) if pd.notna(row.get("SUBSETOR")) else "",
                "segment": str(row.get("SEGMENTO / ADM / PAÍS", ""))
                if pd.notna(row.get("SEGMENTO / ADM / PAÍS"))
                else "",
                "asset_type": str(row.get("TIPO", "Ação")) if pd.notna(row.get("TIPO")) else "Ação",
            }
        return {
            "name": f"Ativo não catalogado ({ticker})",
            "image": "",
            "cnpj": "N/D",
            "sector": "Não informado",
            "sub_sector": "Não informado",
            "segment": "Não informado",
            "asset_type": "Não informado",
        }

    @hybridmethod
    def get_asset_catalog_entries(self) -> list[tuple[str, str]]:
        """Return unique catalog tickers and names sorted for UI consumers."""
        catalog = self._market_data_api.load_assets_catalog()
        if catalog.empty:
            return []

        catalog = catalog.loc[~catalog.index.duplicated(keep="first")]
        entries = [
            (str(ticker), str(row.get("NOME", "Nome não disponível")))
            for ticker, row in catalog.iterrows()
        ]
        return sorted(entries, key=lambda entry: entry[0])

    @hybridmethod
    def get_bazin_target_context(
        self,
        model: str,
        *,
        classic_target_yield: float = 6.0,
        target_spread: float = 3.0,
    ) -> dict:
        """Resolve the active Bazin target and the macro rate shown by the UI."""
        reference_rate = None
        if model == MODEL_SELIC:
            reference_rate = self._market_data_api.get_current_selic()
            target_yield = ValuationService.calculate_target_yield(model, selic_rate=reference_rate)
        elif model == MODEL_IPCA_SPREAD:
            reference_rate = self._market_data_api.get_current_ipca_l12m()
            target_yield = ValuationService.calculate_target_yield(
                model, ipca_rate=reference_rate, target_spread=target_spread
            )
        else:
            target_yield = ValuationService.calculate_target_yield(
                model, classic_target_yield=classic_target_yield
            )
        return {"target_yield": target_yield, "reference_rate": reference_rate}

    @hybridmethod
    def get_asset_market_analysis(self, ticker: str, target_yield: float = 6.0) -> dict:
        """Return catalog metadata and Bazin valuation data for any catalog ticker."""
        ticker = ticker.strip().upper()
        details = self._market_analysis_api.get_ticker_market_analysis(
            ticker, target_yield_pct=target_yield
        )
        if not details:
            return {}

        details["metadata"] = self.get_asset_metadata(ticker)
        return details

    @hybridmethod
    def get_years_with_dividends(self) -> list:
        """Returns a sorted list of all unique years available in the dividends database."""
        return self._portfolio_repo.get_years_with_dividends()

    @hybridmethod
    def get_asset_years_with_dividends(self, ticker: str) -> list:
        """Returns a sorted list of unique years in which a specific asset paid dividends."""
        return self._portfolio_repo.get_asset_years_with_dividends(ticker)

    def _build_dividends_pivot_dataframe(self, rows) -> pd.DataFrame:
        """Converts raw database rows into a structured PT-BR dividends pivot DataFrame (DRY helper)."""
        data = {"DIVIDEND": 0.0, "JCP": 0.0, "YIELD": 0.0}
        for row in rows:
            div_type, total = row
            if div_type in data:
                data[div_type] = float(total)
            else:
                data["YIELD"] = data.get("YIELD", 0.0) + float(total)

        total_sum = sum(data.values())

        df = pd.DataFrame(
            [
                {"Categoria": "Total de Dividendos", "Valor (R$)": data["DIVIDEND"]},
                {"Categoria": "Total de JCP", "Valor (R$)": data["JCP"]},
                {"Categoria": "Total de Rendimentos", "Valor (R$)": data["YIELD"]},
                {"Categoria": "Total de Proventos (Soma de todos)", "Valor (R$)": total_sum},
            ]
        )
        return df

    @hybridmethod
    def get_annual_dividends_pivot(self, year: str) -> pd.DataFrame:
        """Returns aggregated totals for dividends, JCP, and rendimentos for a specific year."""
        rows = self._portfolio_repo.get_annual_dividend_types_sum(year)
        return self._build_dividends_pivot_dataframe(rows)

    @hybridmethod
    def get_asset_annual_dividends_pivot(self, ticker: str, year: str) -> pd.DataFrame:
        """Returns aggregated totals for dividends, JCP, and rendimentos for a specific asset and year."""
        rows = self._portfolio_repo.get_asset_annual_dividend_types_sum(ticker, year)
        return self._build_dividends_pivot_dataframe(rows)

    @hybridmethod
    def get_tracked_market_assets(self, include_owned: bool = True) -> list:
        """Returns the list of tracked tickers from the database, automatically merged with owned stocks."""
        db_tracked = self._portfolio_repo.get_tracked_assets()

        try:
            df_positions = self.calculate_positions()
            if not df_positions.empty:
                # Include owned stocks and uncatalogued positions whose type is unknown.
                owned_stocks = df_positions[
                    df_positions["asset_type"]
                    .str.strip()
                    .str.lower()
                    .isin(["ação", "acao", "ações", "acoes", "não informado"])
                ]["ticker"].tolist()
            else:
                owned_stocks = []
        except Exception:
            owned_stocks = []

        if not include_owned:
            # Return database tracked assets minus any currently owned stocks
            return sorted(list(set(db_tracked) - set(owned_stocks)))

        # Merge and deduplicate while keeping alphabetical order
        all_tickers = sorted(list(set(db_tracked + owned_stocks)))
        return all_tickers

    @hybridmethod
    def add_tracked_market_asset(self, ticker: str) -> bool:
        """Adds a ticker to the watchlist in the database."""
        return self._portfolio_repo.insert_tracked_asset(ticker)

    @hybridmethod
    def remove_tracked_market_asset(self, ticker: str) -> bool:
        """Removes a ticker from the watchlist in the database."""
        return self._portfolio_repo.delete_tracked_asset(ticker)

    @hybridmethod
    def save_dividend_correction(self, ticker: str, year: int, total_value: float) -> bool:
        """Saves or updates a manual dividend correction inside the SQLite database."""
        return self._portfolio_repo.insert_dividend_correction(ticker, year, total_value)

    @hybridmethod
    def get_dividend_corrections(self, ticker: str) -> dict:
        """Returns all custom dividend corrections registered for a specific ticker."""
        try:
            return self._portfolio_repo.get_dividend_corrections(ticker)
        except Exception:
            return {}

    @hybridmethod
    def calculate_prior_invested_amount(self, start_date) -> float | None:
        """Calculates the prior net investment, or None when a prior cost is pending."""
        if start_date is None:
            return 0.0
        df_all_tx = self._portfolio_repo.get_all_transactions()
        if df_all_tx.empty:
            return 0.0

        df_prev_tx = df_all_tx[df_all_tx["date"] < start_date]
        if df_prev_tx.empty:
            return 0.0
        if "cost_status" in df_prev_tx and df_prev_tx["cost_status"].eq("PENDING").any():
            return None

        from core.constants import FEES, QUANTITY, TRANSACTION_TYPE, UNIT_PRICE

        prior_amount = 0.0
        for _, row in df_prev_tx.iterrows():
            txn_type = row[TRANSACTION_TYPE]
            qty = row[QUANTITY]
            price = row[UNIT_PRICE]
            fees = row[FEES]
            if txn_type == "BUY":
                prior_amount += qty * price + fees
            elif txn_type == "SELL":
                prior_amount -= qty * price - fees

        return max(0.0, prior_amount)

    @hybridmethod
    def calculate_positions(self, today_date=None, start_date=None) -> pd.DataFrame:
        """
        Consolidates active portfolio holdings, calculating average price (PM),
        invested totals, and received dividends. Optional start_date filters out older transactions.
        """
        catalog = self._market_data_api.load_assets_catalog()

        if today_date is None:
            today_date = datetime.date.today()

        l12m_limit = (today_date - datetime.timedelta(days=365)).strftime("%Y-%m-%d")
        ytd_limit = f"{today_date.year}-01-01"

        df_transactions = self._portfolio_repo.get_all_transactions()
        if start_date is not None:
            df_transactions = df_transactions[df_transactions["date"] >= start_date]

        portfolio_state = {}

        from core.constants import (
            ASSET_TYPE,
            AVERAGE_PRICE,
            FEES,
            INVESTED_AMOUNT,
            L12M_DIVIDENDS,
            NAME,
            QUANTITY,
            SECTOR,
            TICKER,
            TOTAL_DIVIDENDS,
            TRANSACTION_TYPE,
            UNIT_PRICE,
            YTD_DIVIDENDS,
        )

        for _, row in df_transactions.iterrows():
            ticker = row[TICKER]
            txn_type = row[TRANSACTION_TYPE]
            qty = row[QUANTITY]
            price = row[UNIT_PRICE]
            fees = row[FEES]

            if ticker not in portfolio_state:
                portfolio_state[ticker] = {
                    QUANTITY: 0,
                    AVERAGE_PRICE: 0.0,
                    INVESTED_AMOUNT: 0.0,
                }

            current_state = portfolio_state[ticker]
            old_qty = current_state[QUANTITY]
            old_avg_price = current_state[AVERAGE_PRICE]

            if txn_type == "BUY":
                new_qty = old_qty + qty
                if row.get("cost_status") == "PENDING":
                    new_avg_price = old_avg_price
                    new_invested_amount = current_state[INVESTED_AMOUNT]
                else:
                    new_invested_amount = current_state[INVESTED_AMOUNT] + qty * price + fees
                    new_avg_price = new_invested_amount / new_qty if new_qty > 0 else 0.0
                portfolio_state[ticker] = {
                    QUANTITY: new_qty,
                    AVERAGE_PRICE: new_avg_price,
                    INVESTED_AMOUNT: new_invested_amount,
                }
            elif txn_type == "SELL":
                new_qty = max(0, old_qty - qty)
                portfolio_state[ticker] = {
                    QUANTITY: new_qty,
                    AVERAGE_PRICE: old_avg_price if new_qty > 0 else 0.0,
                    INVESTED_AMOUNT: max(
                        0.0,
                        current_state[INVESTED_AMOUNT]
                        - qty * current_state[INVESTED_AMOUNT] / old_qty
                        if old_qty > 0
                        else current_state[INVESTED_AMOUNT],
                    ),
                }
            elif txn_type == "GROUP":
                new_qty = qty
                new_avg_price = current_state[INVESTED_AMOUNT] / qty if qty > 0 else 0.0
                portfolio_state[ticker] = {
                    QUANTITY: new_qty,
                    AVERAGE_PRICE: new_avg_price,
                    INVESTED_AMOUNT: current_state[INVESTED_AMOUNT],
                }

            pending = (
                current_state.get("cost_pending", False) or row.get("cost_status") == "PENDING"
            )
            portfolio_state[ticker]["cost_pending"] = (
                pending and portfolio_state[ticker][QUANTITY] > 0
            )

        active_assets = []
        for ticker, info in portfolio_state.items():
            if info[QUANTITY] > 0:
                metadata = self._resolve_asset_metadata(catalog, ticker)
                name = metadata["name"]
                asset_type = metadata["asset_type"]
                sector = metadata["sector"]
                segment = metadata["segment"]
                asset_type_clean = asset_type.strip().lower()
                if asset_type_clean in ["ação", "acao"]:
                    display_sector = segment if segment else sector
                elif asset_type_clean == "etf":
                    display_sector = "-"
                else:
                    display_sector = sector

                if start_date is not None:
                    total_dividends = self._portfolio_repo.get_dividends_by_ticker_since_date(
                        ticker, start_date
                    )
                else:
                    total_dividends = self._portfolio_repo.get_total_dividends_by_ticker(ticker)

                l12m_dividends = self._portfolio_repo.get_dividends_by_ticker_since_date(
                    ticker, l12m_limit
                )
                ytd_dividends = self._portfolio_repo.get_dividends_by_ticker_since_date(
                    ticker, ytd_limit
                )

                active_assets.append(
                    {
                        TICKER: ticker,
                        NAME: name,
                        ASSET_TYPE: asset_type,
                        SECTOR: display_sector,
                        QUANTITY: info[QUANTITY],
                        "cost_pending": info.get("cost_pending", False),
                        AVERAGE_PRICE: float("nan")
                        if info.get("cost_pending")
                        else info[AVERAGE_PRICE],
                        INVESTED_AMOUNT: info[INVESTED_AMOUNT],
                        TOTAL_DIVIDENDS: total_dividends,
                        L12M_DIVIDENDS: l12m_dividends,
                        YTD_DIVIDENDS: ytd_dividends,
                    }
                )

        return pd.DataFrame(active_assets)

    @hybridmethod
    def calculate_historical_evolution(
        self, start_date=None, include_pending_costs: bool = False
    ) -> pd.DataFrame:
        """
        Consolidates a month-by-month chronological sequence of your portfolio evolution.
        Ensures a seamless monthly series without gaps since the first transaction or custom start_date.
        """
        df_transactions = self._portfolio_repo.get_all_transactions()
        df_dividends = self._portfolio_repo.get_all_dividends()

        from core.constants import (
            CUMULATIVE_DIVIDENDS,
            CUMULATIVE_INVESTED,
            DATE,
            FEES,
            MONTH_STR,
            MONTHLY_DIVIDEND,
            NET_CASHFLOW,
            QUANTITY,
            TOTAL_VALUE,
            TRANSACTION_TYPE,
            UNIT_PRICE,
        )

        if start_date is not None:
            df_transactions = df_transactions[df_transactions[DATE] >= start_date]
            df_dividends = df_dividends[df_dividends[DATE] >= start_date]

        if df_transactions.empty and df_dividends.empty:
            return pd.DataFrame()

        pending_trade = df_transactions.get(
            "cost_status", pd.Series(False, index=df_transactions.index)
        ).eq("PENDING") & df_transactions.get(
            "event_kind", pd.Series("TRADE", index=df_transactions.index)
        ).ne("CUSTODY")
        if pending_trade.any() and not include_pending_costs:
            return pd.DataFrame()

        df_transactions[MONTH_STR] = df_transactions[DATE].str[:7]
        df_dividends[MONTH_STR] = df_dividends[DATE].str[:7]

        df_transactions[NET_CASHFLOW] = df_transactions.apply(
            lambda r: (
                0.0
                if r.get("event_kind") == "CUSTODY"
                else (r[QUANTITY] * r[UNIT_PRICE] + r[FEES])
                if r[TRANSACTION_TYPE] == "BUY"
                else -(r[QUANTITY] * r[UNIT_PRICE] - r[FEES])
                if r[TRANSACTION_TYPE] == "SELL"
                else 0.0
            ),
            axis=1,
        )

        monthly_t = df_transactions.groupby(MONTH_STR)[NET_CASHFLOW].sum().reset_index()
        monthly_d = (
            df_dividends.groupby(MONTH_STR)[TOTAL_VALUE]
            .sum()
            .reset_index()
            .rename(columns={TOTAL_VALUE: MONTHLY_DIVIDEND})
        )

        if start_date is not None:
            start_date_str = start_date
        else:
            min_date_transactions = (
                df_transactions[DATE].min() if not df_transactions.empty else None
            )
            min_date_dividends = df_dividends[DATE].min() if not df_dividends.empty else None

            dates = [d for d in [min_date_transactions, min_date_dividends] if d is not None]
            if not dates:
                return pd.DataFrame()

            start_date_str = min(dates)

        start_date_dt = pd.to_datetime(start_date_str).replace(day=1)
        today = datetime.date.today()

        date_range = pd.date_range(start=start_date_dt, end=today, freq="MS")
        all_months = date_range.strftime("%Y-%m").tolist()

        if not all_months:
            all_months = [start_date_dt.strftime("%Y-%m")]

        timeline = pd.DataFrame({MONTH_STR: all_months})
        timeline = timeline.merge(monthly_t, on=MONTH_STR, how="left")
        timeline[NET_CASHFLOW] = pd.to_numeric(timeline[NET_CASHFLOW], errors="coerce").fillna(0.0)
        timeline = timeline.merge(monthly_d, on=MONTH_STR, how="left")
        timeline[MONTHLY_DIVIDEND] = pd.to_numeric(
            timeline[MONTHLY_DIVIDEND], errors="coerce"
        ).fillna(0.0)

        timeline[CUMULATIVE_INVESTED] = timeline[NET_CASHFLOW].cumsum()
        timeline[CUMULATIVE_DIVIDENDS] = timeline[MONTHLY_DIVIDEND].cumsum()

        return timeline

    @hybridmethod
    def get_ytd_contributions(self, current_year: int) -> float | None:
        """Calculates total net contributions made in the current year."""
        contributions = self._get_net_contributions(f"{current_year}-01-01")
        if contributions is None:
            return None
        return float(contributions["amount"].sum())

    def _get_net_contributions(self, start_date=None) -> pd.DataFrame | None:
        """Returns trade cash flows, or None when a selected trade has pending cost."""
        transactions = self._portfolio_repo.get_all_transactions()
        trades = transactions["transaction_type"].isin(["BUY", "SELL"])
        custody = transactions["event_kind"].eq("CUSTODY")
        transactions = transactions.loc[trades & ~custody].copy()
        if start_date is not None:
            transactions = transactions.loc[transactions["date"] >= start_date].copy()
        if transactions["cost_status"].eq("PENDING").any():
            return None

        direction = transactions["transaction_type"].map({"BUY": 1.0, "SELL": -1.0})
        transactions["amount"] = (
            direction * transactions["quantity"] * transactions["unit_price"] + transactions["fees"]
        )
        return transactions

    @hybridmethod
    def get_monthly_contributions_by_year(self, start_date=None) -> pd.DataFrame:
        """Returns monthly contributions grouped by year for the bar chart. Optional start_date filters out older transactions."""
        df_transactions = self._get_net_contributions(start_date)
        if df_transactions is None or df_transactions.empty:
            return pd.DataFrame()
        df_transactions["year"] = df_transactions["date"].str[:4]
        df_transactions["month"] = df_transactions["date"].str[5:7]

        grouped = df_transactions.groupby(["year", "month"])["amount"].sum().reset_index()
        return grouped

    @hybridmethod
    def get_market_analysis_data(
        self, tracked_tickers: list[str], target_yield: float
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Aggregates real-time Yahoo Finance indicators and local metadata
        for tracked watchlist tickers, returning a tuple of (df_display, df_market).
        """
        from core.constants import (
            CEILING_PRICE,
            CURRENT_DY,
            CURRENT_PRICE,
            MARKET_AVG_DIV_5Y,
            MARKET_AVG_DY_5Y,
            MARKET_DIVIDENDS_5Y,
            MARKET_HIGH_52W,
            MARKET_LOW_52W,
            MARKET_NAME,
            MARKET_PB,
            MARKET_PE,
            MARKET_ROE,
            NAME,
        )
        from core.strings import (
            DISPLAY_AVG_5Y,
            DISPLAY_CEILING,
            DISPLAY_COMPANY,
            DISPLAY_DY_AVG_5Y,
            DISPLAY_DY_CURRENT,
            DISPLAY_P_L,
            DISPLAY_P_VP,
            DISPLAY_QUOTE,
            DISPLAY_ROE,
            DISPLAY_TICKER,
        )

        catalog = self._market_data_api.load_assets_catalog()
        market_rows = []
        prefetch = getattr(self._market_analysis_api, "prefetch_tickers", None)
        if callable(prefetch):
            prefetch(tracked_tickers)
        for t in tracked_tickers:
            details = self._market_analysis_api.get_ticker_market_analysis(
                t, target_yield_pct=target_yield
            )
            metadata = self._resolve_asset_metadata(catalog, t)

            if details:
                current_year = datetime.date.today().year
                last_5_years = [current_year - i for i in range(1, 6)]

                row_data = {
                    DISPLAY_TICKER: t,
                    DISPLAY_COMPANY: details.get(MARKET_NAME, metadata.get(NAME, t))
                    if not catalog.empty and t in catalog.index
                    else metadata["name"],
                    DISPLAY_QUOTE: details.get(CURRENT_PRICE, 0.0),
                    DISPLAY_CEILING: details.get(CEILING_PRICE, 0.0),
                    DISPLAY_P_VP: details.get(MARKET_PB, 0.0),
                    DISPLAY_P_L: details.get(MARKET_PE, 0.0),
                    DISPLAY_DY_CURRENT: details.get(CURRENT_DY, 0.0),
                    DISPLAY_ROE: details.get(MARKET_ROE, 0.0),
                    MARKET_LOW_52W: details.get(MARKET_LOW_52W, 0.0),
                    MARKET_HIGH_52W: details.get(MARKET_HIGH_52W, 0.0),
                    MARKET_AVG_DIV_5Y: details.get(MARKET_AVG_DIV_5Y, 0.0),
                    MARKET_AVG_DY_5Y: details.get(MARKET_AVG_DY_5Y, 0.0),
                }

                for yr in last_5_years:
                    row_data[f"Div {yr}"] = details.get(MARKET_DIVIDENDS_5Y, {}).get(yr, 0.0)

                market_rows.append(row_data)

        if not market_rows:
            return pd.DataFrame(), pd.DataFrame()

        df_market = pd.DataFrame(market_rows)

        df_display = pd.DataFrame()
        df_display[DISPLAY_TICKER] = df_market[DISPLAY_TICKER]
        df_display[DISPLAY_COMPANY] = df_market[DISPLAY_COMPANY]
        df_display[DISPLAY_QUOTE] = df_market[DISPLAY_QUOTE]
        df_display[DISPLAY_CEILING] = df_market[DISPLAY_CEILING]

        current_year = datetime.date.today().year
        last_5_years = [current_year - i for i in range(1, 6)]
        for yr in last_5_years:
            df_display[f"Div {yr}"] = df_market[f"Div {yr}"]

        df_display[DISPLAY_AVG_5Y] = df_market[MARKET_AVG_DIV_5Y]
        df_display[DISPLAY_DY_AVG_5Y] = df_market[MARKET_AVG_DY_5Y]
        df_display[DISPLAY_P_VP] = df_market[DISPLAY_P_VP]
        df_display[DISPLAY_P_L] = df_market[DISPLAY_P_L]
        df_display[DISPLAY_DY_CURRENT] = df_market[DISPLAY_DY_CURRENT]
        df_display[DISPLAY_ROE] = df_market[DISPLAY_ROE]

        return df_display, df_market

    @hybridmethod
    def get_portfolio_summary_metrics(
        self, df_positions: pd.DataFrame
    ) -> tuple[pd.DataFrame, dict]:
        """
        Calculates all portfolio-wide KPI summary metrics, returning the updated
        df_positions and a dictionary of ready-to-render formatted metrics.
        """
        from core.constants import (
            CURRENT_PRICE,
            CURRENT_VALUE,
            INVESTED_AMOUNT,
            L12M_DIVIDENDS,
            PROFIT_LOSS,
            QUANTITY,
            TICKER,
            TOTAL_DIVIDENDS,
            YTD_DIVIDENDS,
        )

        if df_positions.empty:
            return df_positions, {}

        tickers = df_positions[TICKER].tolist()
        quote_map = self._market_data_api.get_batch_quotes(tickers)

        prices = pd.to_numeric(df_positions[TICKER].map(quote_map), errors="coerce")
        df_positions[CURRENT_PRICE] = prices.where(prices.map(lambda x: math.isfinite(x) and x > 0))
        df_positions[CURRENT_VALUE] = df_positions[QUANTITY] * df_positions[CURRENT_PRICE]
        df_positions[PROFIT_LOSS] = df_positions[CURRENT_VALUE] - df_positions[INVESTED_AMOUNT]

        df_positions["return_pct"] = (
            df_positions[PROFIT_LOSS] / df_positions[INVESTED_AMOUNT]
        ) * 100
        df_positions["total_yoc"] = (
            df_positions[TOTAL_DIVIDENDS] / df_positions[INVESTED_AMOUNT]
        ) * 100
        df_positions["l12m_yoc"] = (
            df_positions[L12M_DIVIDENDS] / df_positions[INVESTED_AMOUNT]
        ) * 100

        cost_pending = bool(
            df_positions.get("cost_pending", pd.Series(False, index=df_positions.index)).any()
        )
        total_invested_init = df_positions[INVESTED_AMOUNT].sum(skipna=False)
        market_complete = bool(df_positions[CURRENT_PRICE].notna().all())
        total_equity = df_positions[CURRENT_VALUE].sum(skipna=False)

        total_dividends = df_positions[TOTAL_DIVIDENDS].sum()
        l12m_dividends = df_positions[L12M_DIVIDENDS].sum()
        ytd_dividends = df_positions[YTD_DIVIDENDS].sum()

        total_profit = total_equity - total_invested_init
        ratios_available = total_invested_init > 0
        overall_return = (
            (total_profit / total_invested_init * 100) if ratios_available else float("nan")
        )
        overall_yoc = (
            (total_dividends / total_invested_init * 100) if ratios_available else float("nan")
        )
        overall_l12m_yoc = (
            (l12m_dividends / total_invested_init * 100) if ratios_available else float("nan")
        )
        if cost_pending:
            overall_return = overall_yoc = overall_l12m_yoc = float("nan")
        if not market_complete:
            overall_return = float("nan")

        # Pull the invested capital parameter used in PMT calculations from the planning service if available
        if self._planning_provider is not None:
            sim = self._planning_provider.get_current_simulation()
            total_invested_sim = sim["total_invested"] if sim else total_invested_init
        else:
            total_invested_sim = total_invested_init

        return df_positions, {
            "total_equity": total_equity,
            "cost_pending": cost_pending,
            "market_complete": market_complete,
            "total_invested": total_invested_sim,
            "total_dividends": total_dividends,
            "l12m_dividends": l12m_dividends,
            "ytd_dividends": ytd_dividends,
            "overall_return": overall_return,
            "overall_yoc": overall_yoc,
            "overall_l12m_yoc": overall_l12m_yoc,
            "ratios_available": ratios_available,
        }

    @hybridmethod
    def get_detailed_holdings_dataframe(
        self, df_positions: pd.DataFrame, target_yield: float
    ) -> tuple[pd.DataFrame, dict]:
        """
        Calculates detailed holding metrics, retrieves Bazin ceilings,
        and compiles a structured, pre-formatted display DataFrame ready for the view.
        """
        from core.constants import (
            ADJUSTED_PRICE,
            AVERAGE_PRICE,
            CEILING_PRICE_GRID,
            CURRENT_PRICE,
            CURRENT_VALUE,
            INVESTED_AMOUNT,
            L12M_DIVIDENDS,
            NAME,
            PROFIT_LOSS,
            QUANTITY,
            RETURN_PCT_CUSTOM,
            SECTOR,
            TICKER,
            TOTAL_DIVIDENDS,
            WEIGHT_PCT,
            YOC_12_CUSTOM,
            YOC_CUSTOM,
        )
        from core.strings import (
            DISPLAY_ADJ_PRICE,
            DISPLAY_AVG_PRICE,
            DISPLAY_CEILING,
            DISPLAY_CODE,
            DISPLAY_CURRENT,
            DISPLAY_EARNINGS,
            DISPLAY_INVESTED,
            DISPLAY_NAME,
            DISPLAY_QTY,
            DISPLAY_QUOTE_TODAY,
            DISPLAY_RESULT,
            DISPLAY_RETURN_PCT,
            DISPLAY_SECTOR,
            DISPLAY_WEIGHT,
            DISPLAY_YOC,
            DISPLAY_YOC_12,
        )
        from core.utils.formatter import Formatter

        if df_positions.empty:
            return pd.DataFrame(), {}

        total_equity = df_positions[CURRENT_VALUE].sum(skipna=False)

        df_positions[ADJUSTED_PRICE] = (
            df_positions[INVESTED_AMOUNT] - df_positions[TOTAL_DIVIDENDS]
        ) / df_positions[QUANTITY]
        invested_base = df_positions[INVESTED_AMOUNT].where(df_positions[INVESTED_AMOUNT] > 0)
        df_positions[RETURN_PCT_CUSTOM] = df_positions[PROFIT_LOSS] / invested_base * 100
        df_positions[YOC_CUSTOM] = df_positions[TOTAL_DIVIDENDS] / invested_base * 100
        df_positions[YOC_12_CUSTOM] = df_positions[L12M_DIVIDENDS] / invested_base * 100
        df_positions[WEIGHT_PCT] = (
            (df_positions[CURRENT_VALUE] / total_equity * 100)
            if total_equity > 0
            else float("nan")
            if pd.isna(total_equity)
            else 0.0
        )

        ceilings = {}
        prefetch = getattr(self._market_analysis_api, "prefetch_tickers", None)
        if callable(prefetch):
            prefetch(df_positions[TICKER].tolist())
        for t in df_positions[TICKER]:
            details = self._market_analysis_api.get_ticker_market_analysis(
                t, target_yield_pct=target_yield
            )
            ceilings[t] = details.get("ceiling_price", float("nan")) if details else float("nan")

        df_positions[CEILING_PRICE_GRID] = df_positions[TICKER].map(lambda t: ceilings.get(t, 0.0))

        df_display = pd.DataFrame()
        df_display[DISPLAY_CODE] = df_positions[TICKER]
        df_display[DISPLAY_NAME] = df_positions[NAME]
        df_display[DISPLAY_SECTOR] = df_positions[SECTOR]
        df_display[DISPLAY_WEIGHT] = df_positions[WEIGHT_PCT].map(lambda x: f"{x:.2f}%")
        df_display[DISPLAY_QTY] = df_positions[QUANTITY]
        df_display[DISPLAY_AVG_PRICE] = df_positions[AVERAGE_PRICE].map(Formatter.format_currency)
        df_display[DISPLAY_ADJ_PRICE] = df_positions[ADJUSTED_PRICE].map(Formatter.format_currency)
        df_display[DISPLAY_CEILING] = df_positions[CEILING_PRICE_GRID].map(
            Formatter.format_currency
        )
        df_display[DISPLAY_QUOTE_TODAY] = df_positions[CURRENT_PRICE].map(Formatter.format_currency)
        df_display[DISPLAY_INVESTED] = df_positions[INVESTED_AMOUNT].map(Formatter.format_currency)
        df_display[DISPLAY_CURRENT] = df_positions[CURRENT_VALUE].map(Formatter.format_currency)
        df_display[DISPLAY_RETURN_PCT] = df_positions[RETURN_PCT_CUSTOM].map(lambda x: f"{x:.2f}%")
        df_display[DISPLAY_RESULT] = df_positions[PROFIT_LOSS].map(Formatter.format_currency)
        df_display[DISPLAY_EARNINGS] = df_positions[TOTAL_DIVIDENDS].map(Formatter.format_currency)
        df_display[DISPLAY_YOC] = df_positions[YOC_CUSTOM].map(lambda x: f"{x:.2f}%")
        df_display[DISPLAY_YOC_12] = df_positions[YOC_12_CUSTOM].map(lambda x: f"{x:.2f}%")

        pending = df_positions.get("cost_pending", pd.Series(False, index=df_positions.index))
        zero_basis = df_positions[INVESTED_AMOUNT] <= 0
        for column in (DISPLAY_RETURN_PCT, DISPLAY_YOC, DISPLAY_YOC_12):
            df_display.loc[zero_basis, column] = "N/D"
        if pending.any():
            df_display["Situação do custo"] = pending.map(
                {True: "Custo pendente", False: "Informado"}
            )
            for column in (
                DISPLAY_AVG_PRICE,
                DISPLAY_ADJ_PRICE,
                DISPLAY_RETURN_PCT,
                DISPLAY_RESULT,
                DISPLAY_YOC,
                DISPLAY_YOC_12,
            ):
                df_display.loc[pending, column] = "Custo pendente"

        # Missing remote inputs are never rendered as zero or literal "nan".
        for display_column, source_column in (
            (DISPLAY_WEIGHT, WEIGHT_PCT),
            (DISPLAY_CEILING, CEILING_PRICE_GRID),
            (DISPLAY_QUOTE_TODAY, CURRENT_PRICE),
            (DISPLAY_CURRENT, CURRENT_VALUE),
            (DISPLAY_RETURN_PCT, RETURN_PCT_CUSTOM),
            (DISPLAY_RESULT, PROFIT_LOSS),
        ):
            missing = df_positions[source_column].isna() & ~pending
            df_display.loc[missing, display_column] = "N/D"
        for display_column, source_column in (
            (DISPLAY_WEIGHT, WEIGHT_PCT),
            (DISPLAY_CEILING, CEILING_PRICE_GRID),
            (DISPLAY_QUOTE_TODAY, CURRENT_PRICE),
            (DISPLAY_CURRENT, CURRENT_VALUE),
        ):
            df_display.loc[df_positions[source_column].isna(), display_column] = "N/D"

        return df_display, ceilings
