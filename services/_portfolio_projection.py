"""Private calculations over one coherent ledger; callers use PortfolioReadService."""

import datetime
import math

import pandas as pd


class PortfolioProjection:
    def __init__(self, ledger, catalog, quotes, analysis):
        self._ledger = ledger
        self._market_data_api = quotes
        self._market_analysis_api = analysis
        self._catalog = catalog

    def _dividends_sum(self, ticker, start_date=None):
        records = self._ledger.dividends
        selected = records["ticker"].eq(ticker)
        if start_date is not None:
            selected &= records["date"].ge(start_date)
        return float(records.loc[selected, "total_value"].sum())

    def quantity_on_date(self, ticker, date):
        transactions = self._ledger.transactions
        selected = transactions[transactions["ticker"].eq(ticker) & transactions["date"].le(date)]
        qty = 0
        for row in selected.to_dict("records"):
            if row["transaction_type"] == "BUY":
                qty += row["quantity"]
            elif row["transaction_type"] == "SELL":
                qty = max(0, qty - row["quantity"])
            elif row["transaction_type"] == "GROUP":
                qty = row["quantity"]
        return qty

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
            basis = self._positive_number(self.quantity_on_date(ticker, date))
        return self._positive_number(total / basis) if basis is not None else None

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

    def _build_dividends_pivot_dataframe(self, rows) -> pd.DataFrame:
        """Converts raw database rows into a structured PT-BR dividends pivot DataFrame (DRY helper)."""
        data = {"DIVIDEND": 0.0, "JCP": 0.0, "YIELD": 0.0}
        for row in rows:
            div_type, total = row
            if div_type in data:
                data[div_type] += float(total)
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

    def calculate_prior_invested_amount(self, start_date) -> float | None:
        """Calculates the prior net investment, or None when a prior cost is pending."""
        if start_date is None:
            return 0.0
        df_all_tx = self._ledger.transactions.copy()
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

    def calculate_positions(self, today_date=None, start_date=None) -> pd.DataFrame:
        """
        Consolidates active portfolio holdings, calculating average price (PM),
        invested totals, and received dividends. Optional start_date filters out older transactions.
        """
        catalog = self._catalog

        if today_date is None:
            today_date = datetime.date.today()

        l12m_limit = (today_date - datetime.timedelta(days=365)).strftime("%Y-%m-%d")
        ytd_limit = f"{today_date.year}-01-01"

        df_transactions = self._ledger.transactions.copy()
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
                    total_dividends = self._dividends_sum(ticker, start_date)
                else:
                    total_dividends = self._dividends_sum(ticker)

                l12m_dividends = self._dividends_sum(ticker, l12m_limit)
                ytd_dividends = self._dividends_sum(ticker, ytd_limit)

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

    def calculate_historical_evolution(
        self, start_date=None, include_pending_costs: bool = False
    ) -> pd.DataFrame:
        """
        Consolidates a month-by-month chronological sequence of your portfolio evolution.
        Ensures a seamless monthly series without gaps since the first transaction or custom start_date.
        """
        df_transactions = self._ledger.transactions.copy()
        df_dividends = self._ledger.dividends.copy()

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

    def get_ytd_contributions(self, current_year: int) -> float | None:
        """Calculates total net contributions made in the current year."""
        contributions = self._get_net_contributions(f"{current_year}-01-01")
        if contributions is None:
            return None
        return float(contributions["amount"].sum())

    def _get_net_contributions(self, start_date=None) -> pd.DataFrame | None:
        """Returns trade cash flows, or None when a selected trade has pending cost."""
        transactions = self._ledger.transactions.copy()
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

    def get_monthly_contributions_by_year(self, start_date=None) -> pd.DataFrame:
        """Returns monthly contributions grouped by year for the bar chart. Optional start_date filters out older transactions."""
        df_transactions = self._get_net_contributions(start_date)
        if df_transactions is None or df_transactions.empty:
            return pd.DataFrame()
        df_transactions["year"] = df_transactions["date"].str[:4]
        df_transactions["month"] = df_transactions["date"].str[5:7]

        grouped = df_transactions.groupby(["year", "month"])["amount"].sum().reset_index()
        return grouped

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

        return df_positions, {
            "total_equity": total_equity,
            "cost_pending": cost_pending,
            "market_complete": market_complete,
            "total_invested": total_invested_init,
            "total_dividends": total_dividends,
            "l12m_dividends": l12m_dividends,
            "ytd_dividends": ytd_dividends,
            "overall_return": overall_return,
            "overall_yoc": overall_yoc,
            "overall_l12m_yoc": overall_l12m_yoc,
            "ratios_available": ratios_available,
        }

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
