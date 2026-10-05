import datetime
import json
import logging
import math
from bisect import bisect_left, bisect_right
from decimal import Decimal
from itertools import groupby, islice

import pandas as pd

from core.activity import ACTIVITY_EVENTS, activity_event
from core.daos.portfolio_dao import PortfolioDAO
from core.ports import (
    ExcelParserPort,
    MarketAnalysisPort,
    MarketDataPort,
    PortfolioPort,
    PortfolioReadPort,
    hybridmethod,
)
from core.strings import MODEL_IPCA_SPREAD, MODEL_SELIC
from core.utils.market_data import MarketData
from core.utils.ticker import normalize_b3_ticker
from services.valuation_service import ValuationService

logger = logging.getLogger(__name__)
_MAX_B3_SUBSET_STATES = 65_536


class AssetService:
    """Own portfolio writes, B3 import, operation history, watchlist and catalog use cases."""

    def __init__(
        self,
        portfolio_repo: PortfolioPort = None,
        market_data_api: MarketDataPort = None,
        market_analysis_api: MarketAnalysisPort = None,
        excel_parser: ExcelParserPort = None,
        read_provider: PortfolioReadPort = None,
    ):
        self._portfolio_repo = portfolio_repo or PortfolioDAO()
        self._market_data_api = market_data_api or MarketData
        self._market_analysis_api = market_analysis_api
        self._excel_parser = excel_parser
        self._read_provider = read_provider

    @property
    def _reads(self):
        if self._read_provider is not None:
            return self._read_provider
        from services.portfolio_read_service import PortfolioReadService

        return PortfolioReadService(
            self._portfolio_repo,
            self._market_data_api,
            self._market_analysis_api,
            self._market_data_api,
        )

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
        read_provider: PortfolioReadPort = None,
    ):
        """Dynamic dependency injection mechanism for testing and custom environment mocks."""
        inst = cls.get_default()
        if read_provider is not None:
            inst._read_provider = read_provider
        if portfolio_repo is not None:
            inst._portfolio_repo = portfolio_repo
        if market_data_api is not None:
            inst._market_data_api = market_data_api
        if market_analysis_api is not None:
            inst._market_analysis_api = market_analysis_api
        if excel_parser is not None:
            inst._excel_parser = excel_parser

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
                df_positions = self._reads.read_planning().positions
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
                    and self._portfolio_repo.get_quantity_on_date(row["ticker"], row["date"]) == 0
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
        search_inputs = []
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
                search_inputs.append((manual_records, record, source))
        self._preserve_disjoint_manual_groups(candidates, search_inputs)
        return candidates

    @staticmethod
    def _find_matching_manual_groups(manual_records, record, source):
        return list(
            islice(AssetService._iter_matching_manual_groups(manual_records, record, source), 25)
        )

    @staticmethod
    def _raise_b3_search_limit():
        raise ValueError(
            "Há muitos lançamentos manuais para comparar com segurança. "
            "A importação foi interrompida antes de gravar qualquer linha. "
            "Revise os lançamentos desse ativo antes de tentar novamente."
        )

    @staticmethod
    def _consume_b3_search_work(work_budget):
        if work_budget is not None:
            work_budget[0] -= 1
            if work_budget[0] < 0:
                AssetService._raise_b3_search_limit()

    @staticmethod
    def _preserve_disjoint_manual_groups(candidates, search_inputs):
        """Keep a jointly feasible choice in each bounded list of overlapping suggestions."""
        parents = list(range(len(candidates)))

        def root(index):
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index

        owners = {}
        for index, (manual_records, _, _) in enumerate(search_inputs):
            for row in manual_records:
                previous = owners.setdefault(row["id"], index)
                parents[root(index)] = root(previous)
        components = {}
        for index in range(len(candidates)):
            components.setdefault(root(index), []).append(index)
        work_budget = [_MAX_B3_SUBSET_STATES * 8]
        for indices in components.values():
            if len(indices) < 2:
                continue
            indices.sort(key=lambda index: len(candidates[index]["manual_groups"]))
            pool = {row["id"]: row for index in indices for row in search_inputs[index][0]}
            if sum(int(row["quantity"]) for row in pool.values()) < sum(
                int(search_inputs[index][1]["quantity"]) for index in indices
            ):
                continue
            assignment = []
            used_ids = set()
            for index in indices:
                group = next(
                    (
                        group
                        for group in candidates[index]["manual_groups"]
                        if used_ids.isdisjoint(group["ids"])
                    ),
                    None,
                )
                if group is None:
                    assignment = []
                    break
                assignment.append(group)
                used_ids.update(group["ids"])
            if not assignment:
                used_ids = set()

                def available_groups(index):
                    rows, record, source = search_inputs[index]
                    remaining = [row for row in rows if row["id"] not in used_ids]
                    if sum(int(row["quantity"]) for row in remaining) < int(record["quantity"]):
                        return iter(())
                    return AssetService._iter_matching_manual_groups(
                        remaining, record, source, work_budget
                    )

                # Stream full searches only when the displayed lists cannot form an assignment.
                # Exhaustion means no joint match; exhausting the work budget raises explicitly.
                searches = [available_groups(indices[0])]
                while searches:
                    AssetService._consume_b3_search_work(work_budget)
                    group = next(searches[-1], None)
                    if group is None:
                        searches.pop()
                        if assignment:
                            used_ids.difference_update(assignment.pop()["ids"])
                        continue
                    assignment.append(group)
                    used_ids.update(group["ids"])
                    if len(assignment) == len(indices):
                        break
                    searches.append(available_groups(indices[len(assignment)]))
            if len(assignment) != len(indices):
                continue
            for index, group in zip(indices, assignment, strict=True):
                existing = candidates[index]["manual_groups"]
                candidates[index]["manual_groups"] = [
                    group,
                    *(item for item in existing if item["ids"] != group["ids"]),
                ][:25]
                candidates[index]["manual_candidates"] = [
                    item["transactions"][0]
                    for item in candidates[index]["manual_groups"]
                    if len(item["transactions"]) == 1
                ]

    @staticmethod
    def _iter_matching_manual_groups(manual_records, record, source, work_budget=None):
        """Match bounded half-subsets; abort rather than report an incomplete search as unmatched."""
        ordered = sorted(manual_records, key=lambda item: (item["date"], item["id"]))
        quantity = int(record["quantity"])
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

        def subsets(rows):
            states = [(0, Decimal(0), ())]
            visited_states = 0
            for item in rows:
                item_quantity = int(item["quantity"])
                item_value = item_quantity * Decimal(str(item["unit_price"]))
                previous_count = len(states)
                for index in range(previous_count):
                    AssetService._consume_b3_search_work(work_budget)
                    visited_states += 1
                    if visited_states > _MAX_B3_SUBSET_STATES:
                        AssetService._raise_b3_search_limit()
                    selected_quantity, selected_value, selected = states[index]
                    combined_quantity = selected_quantity + item_quantity
                    if combined_quantity > quantity:
                        continue
                    if len(states) >= _MAX_B3_SUBSET_STATES:
                        AssetService._raise_b3_search_limit()
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
                    AssetService._consume_b3_search_work(work_budget)
                    inspected_pairs += 1
                    if inspected_pairs > _MAX_B3_SUBSET_STATES:
                        AssetService._raise_b3_search_limit()
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
                    yield {
                        "ids": [int(tx["id"]) for tx in transactions],
                        "transactions": transactions,
                        "quantity": quantity,
                        "weighted_unit_price": average,
                        "total_value": total_value,
                    }

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
        active_positions = self._reads.read_planning().positions
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
    def get_owned_tickers(self) -> list[str]:
        """Returns tickers with a positive current position."""
        df_positions = self._reads.read_planning().positions
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
        self, ticker, date, total, quantity=None, unit_price=None
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
            basis = self._positive_number(self._portfolio_repo.get_quantity_on_date(ticker, date))
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
    def get_tracked_market_assets(self, include_owned: bool = True) -> list:
        """Returns the list of tracked tickers from the database, automatically merged with owned stocks."""
        db_tracked = self._portfolio_repo.get_tracked_assets()

        try:
            df_positions = self._reads.read_planning().positions
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
