"""Complete portfolio reads over a coherent ledger and injected market sources."""

import datetime

import pandas as pd

from core.daos.portfolio_dao import PortfolioDAO
from core.portfolio_read import AssetRead, PortfolioHistory, PortfolioOverview, PortfolioPlanning
from core.ports import (
    MarketAnalysisPort,
    MarketDataPort,
    PortfolioReadRepositoryPort,
    hybridmethod,
)
from core.utils.formatter import Formatter
from core.utils.market_data import MarketData
from core.utils.ticker import normalize_b3_ticker
from services._portfolio_projection import PortfolioProjection


class PortfolioReadService:
    """Own ledger replay, dividend aggregation, enrichment and read shaping."""

    _default_instance = None

    def __init__(
        self,
        repository: PortfolioReadRepositoryPort = None,
        quotes: MarketDataPort = None,
        analysis: MarketAnalysisPort = None,
        catalog: MarketDataPort = None,
    ):
        self._repository = repository or PortfolioDAO()
        self._quotes = quotes or MarketData
        self._analysis = analysis
        self._catalog = catalog or MarketData

    @classmethod
    def get_default(cls):
        if cls._default_instance is None:
            cls._default_instance = cls()
        return cls._default_instance

    @classmethod
    def set_adapters(cls, *, repository=None, quotes=None, analysis=None, catalog=None):
        instance = cls.get_default()
        for name, value in (
            ("repository", repository),
            ("quotes", quotes),
            ("analysis", analysis),
            ("catalog", catalog),
        ):
            if value is not None:
                setattr(instance, f"_{name}", value)

    def _projection(self):
        return PortfolioProjection(
            self._repository.load_ledger(),
            self._catalog.load_assets_catalog(),
            self._quotes,
            self._analysis,
        )

    @staticmethod
    def _pending_tickers(projection, positions):
        transactions = projection._ledger.transactions
        pending = set(transactions.loc[transactions["cost_status"].eq("PENDING"), "ticker"])
        owned = set(positions["ticker"]) if not positions.empty else set()
        return tuple(sorted(pending & owned))

    @hybridmethod
    def read_portfolio(
        self, *, today_date=None, start_date=None, target_yield=6.0
    ) -> PortfolioOverview:
        projection = self._projection()
        positions = projection.calculate_positions(today_date, start_date)
        pending = self._pending_tickers(projection, positions)
        if not positions.empty:
            positions.loc[positions["ticker"].isin(pending), "cost_pending"] = True
        positions, summary = projection.get_portfolio_summary_metrics(positions)
        holdings, ceilings = projection.get_detailed_holdings_dataframe(positions, target_yield)
        sectors = self._sectors(positions)
        return PortfolioOverview(positions, summary, holdings, ceilings, sectors, pending)

    @staticmethod
    def _sectors(positions):
        rows = []
        if positions.empty or not positions["current_value"].notna().all():
            return pd.DataFrame(columns=["sector", "current_value", "Percentual", "Detalhes"])
        total = positions["current_value"].sum()
        for sector, group in positions.groupby("sector"):
            value = group["current_value"].sum()
            details = []
            for row in group.sort_values("current_value", ascending=False).to_dict("records"):
                asset_value = row["current_value"]
                sector_weight = asset_value / value * 100 if value > 0 else 0
                weight = asset_value / total * 100 if total > 0 else 0
                details.append(
                    f"  • {row['ticker']}: {Formatter.format_currency(asset_value)} ({sector_weight:.2f}% do setor / {weight:.2f}% do total)"
                )
            rows.append(
                {
                    "sector": sector,
                    "current_value": value,
                    "Percentual": value / total * 100 if total > 0 else 0,
                    "Detalhes": "<br>".join(details),
                }
            )
        return pd.DataFrame(rows)

    @hybridmethod
    def read_history(self, start_date=None, include_pending_costs=False) -> PortfolioHistory:
        projection = self._projection()
        return PortfolioHistory(
            projection.calculate_historical_evolution(start_date, include_pending_costs),
            projection.get_monthly_contributions_by_year(start_date),
        )

    @hybridmethod
    def read_planning(
        self, *, start_date=None, year=None, quantity_date=None, today_date=None
    ) -> PortfolioPlanning:
        projection = self._projection()
        positions = projection.calculate_positions(today_date=today_date, start_date=start_date)
        invested = float(positions["invested_amount"].sum()) if not positions.empty else 0.0
        date = quantity_date or f"{year or datetime.date.today().year}-01-01"
        tickers = projection._ledger.transactions["ticker"].unique()
        return PortfolioPlanning(
            positions,
            invested,
            projection.calculate_prior_invested_amount(start_date),
            projection.get_ytd_contributions(year or datetime.date.today().year),
            {ticker: projection.quantity_on_date(ticker, date) for ticker in tickers},
            {ticker: self._transaction_history(projection, ticker) for ticker in tickers},
            self._pending_tickers(projection, positions),
        )

    @staticmethod
    def _transaction_history(projection, ticker):
        transactions = projection._ledger.transactions
        selected = transactions.loc[transactions["ticker"].eq(ticker)].copy()
        selected.loc[selected["event_kind"].eq("CUSTODY"), "transaction_type"] = "TRANSFER_IN"
        return selected.drop(columns=["id", "ticker"]).reset_index(drop=True)

    @hybridmethod
    def read_asset(self, ticker: str, *, today_date=None, target_yield=6.0) -> AssetRead:
        ticker = normalize_b3_ticker(ticker)
        projection = self._projection()
        positions = projection.calculate_positions(today_date)
        selected = (
            positions.loc[positions["ticker"].eq(ticker)] if not positions.empty else positions
        )
        position = selected.iloc[0].to_dict() if not selected.empty else {}
        if position:
            quantity = position["quantity"]
            invested = position["invested_amount"]
            position["adjusted_price"] = (invested - position["total_dividends"]) / quantity
            position["monthly_l12m_yoc"] = (
                position["l12m_dividends"] / invested * 100 / 12 if invested > 0 else 0.0
            )
        market = (
            dict(self._analysis.get_ticker_market_analysis(ticker, target_yield_pct=target_yield))
            if self._analysis
            else {}
        )
        quote = self._quotes.get_batch_quotes([ticker]).get(ticker)
        try:
            price = float(quote)
            market["current_price"] = (
                price if pd.notna(price) and 0 < price < float("inf") else float("nan")
            )
        except (ValueError, TypeError):
            market["current_price"] = float("nan")
        metadata = projection._resolve_asset_metadata(projection._catalog, ticker)
        market["metadata"] = metadata
        receipts = projection._ledger.dividends
        receipts = receipts.loc[receipts["ticker"].eq(ticker)].iloc[::-1].copy()
        dividends = receipts.rename(
            columns={"date": "Data", "dividend_type": "Tipo", "total_value": "Total"}
        )
        dividends["Tipo"] = (
            dividends["Tipo"].map({"DIVIDEND": "Dividendo", "JCP": "JCP"}).fillna("Rendimento")
        )
        dividends = dividends[["Data", "Tipo", "Total", "quantity", "unit_price"]].reset_index(
            drop=True
        )
        unit_values = [
            projection._receipt_unit_value(
                ticker, row["date"], row["total_value"], row["quantity"], row["unit_price"]
            )
            for row in receipts.to_dict("records")
        ]
        dividend_details = dividends[["Data", "Tipo", "Total"]].copy()
        dividend_details["Unitário"] = [
            value if value is not None else 0.0 for value in unit_values
        ]
        dividend_details = dividend_details[["Data", "Tipo", "Unitário", "Total"]]
        annual = {}
        for year in sorted(receipts["date"].str[:4].unique(), reverse=True):
            mask = receipts["date"].str.startswith(year)
            totals = receipts.loc[mask].groupby("dividend_type")["total_value"].sum()
            per_share = sum(
                value
                for value, chosen in zip(unit_values, mask, strict=True)
                if chosen and value is not None
            )
            previous_year = str(int(year) - 1)
            quantity = projection.quantity_on_date(ticker, f"{year}-12-31")
            previous_quantity = projection.quantity_on_date(ticker, f"{previous_year}-12-31")
            pivot = projection._build_dividends_pivot_dataframe(totals.items())
            annual[year] = {
                "pivot": pivot,
                "total_paid_per_share": per_share,
                "qty_end_of_year": quantity,
                "qty_prev_year": previous_quantity,
                "quantity_change": quantity - previous_quantity,
                "prev_year": previous_year,
                "dividends": float(totals.get("DIVIDEND", 0)),
                "jcp": float(totals.get("JCP", 0)),
                "yields": float(totals.drop(labels=["DIVIDEND", "JCP"], errors="ignore").sum()),
                "total": float(totals.sum()),
            }
        history = self._transaction_history(projection, ticker)
        transactions = self._transactions_display(history)
        return AssetRead(
            ticker,
            metadata,
            position,
            market,
            transactions,
            history,
            dividends,
            dividend_details,
            annual,
        )

    @staticmethod
    def _transactions_display(history):
        result = pd.DataFrame(index=history.index)
        result["Data"] = history["date"]
        result["Operação"] = history["transaction_type"].map(
            {
                "BUY": "Compra",
                "SELL": "Venda",
                "GROUP": "Grupamento",
                "TRANSFER_IN": "Transferência recebida",
            }
        )
        result["Quantidade"] = history["quantity"]
        result["Valor Unitário"] = history["unit_price"]
        gross = history["quantity"] * history["unit_price"]
        result["Valor Total"] = gross + history["fees"].where(
            ~history["transaction_type"].eq("SELL"), -history["fees"]
        )
        result["Situação do custo"] = (
            history["cost_status"]
            .map({"PENDING": "Custo pendente", "CORRECTED": "Regularizado"})
            .fillna("Informado")
        )
        return result.iloc[::-1].reset_index(drop=True)
