import datetime

import pandas as pd

from core.daos.assets_catalog_dao import AssetsCatalogDAO
from core.daos.portfolio_dao import PortfolioDAO
from core.ports import AssetsCatalogPort, MarketDataPort, PortfolioPort, hybridmethod
from core.utils.market_data import MarketData


class AssetService:
    """Domain Service for managing assets, transactions, dividends, and positions (Single Source of Truth)."""

    def __init__(
        self,
        portfolio_repo: PortfolioPort = None,
        catalog_repo: AssetsCatalogPort = None,
        market_data_api: MarketDataPort = None,
    ):
        self._portfolio_repo = portfolio_repo or PortfolioDAO()
        self._catalog_repo = catalog_repo or AssetsCatalogDAO()
        self._market_data_api = market_data_api or MarketData

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
        catalog_repo: AssetsCatalogPort = None,
        market_data_api: MarketDataPort = None,
    ):
        """Dynamic dependency injection mechanism for testing and custom environment mocks."""
        inst = cls.get_default()
        if portfolio_repo is not None:
            inst._portfolio_repo = portfolio_repo
        if catalog_repo is not None:
            inst._catalog_repo = catalog_repo
        if market_data_api is not None:
            inst._market_data_api = market_data_api

    @hybridmethod
    def register_fallback_asset(self, ticker: str):
        """Appends a fallback asset to assets.csv if not found in the catalog."""
        self._catalog_repo.add_fallback_asset(ticker)

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
        ticker = ticker.strip().upper()
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

        catalog = self._market_data_api.load_assets_catalog()
        if catalog.empty or ticker not in catalog.index:
            self.register_fallback_asset(ticker)

        success = self._portfolio_repo.insert_transaction(
            date, ticker, transaction_type, quantity, unit_price, fees
        )
        if success and transaction_type == "SELL":
            try:
                df_positions = self.calculate_positions()
                if df_positions.empty or ticker not in df_positions["ticker"].values:
                    # Seamlessly transition a zeroed out owned stock to manual tracking so it stays on radar but is removable
                    self.add_tracked_market_asset(ticker)
            except Exception:
                pass
        return success

    @hybridmethod
    def add_dividend(self, ticker: str, date: str, dividend_type: str, total_value: float) -> bool:
        """Inserts a Dividend, JCP, or Yield receipt into the database, avoiding duplicates."""
        ticker = ticker.strip().upper()
        if dividend_type in ("Dividendo", "DIVIDEND"):
            dividend_type = "DIVIDEND"
        elif dividend_type in ("JCP", "JCP"):
            dividend_type = "JCP"
        elif dividend_type in ("Rendimento", "YIELD"):
            dividend_type = "YIELD"

        if self._portfolio_repo.find_dividend(date, ticker, dividend_type, total_value):
            return False

        catalog = self._market_data_api.load_assets_catalog()
        if catalog.empty or ticker not in catalog.index:
            self.register_fallback_asset(ticker)

        return self._portfolio_repo.insert_dividend(date, ticker, dividend_type, total_value)

    @hybridmethod
    def process_b3_import(self, df: pd.DataFrame, progress_callback=None) -> tuple[int, int]:
        """Processes a DataFrame imported from B3, routing and translating row categories to English."""
        df.columns = df.columns.str.strip()

        processed_transactions = 0
        processed_dividends = 0
        total_rows = len(df)

        for idx, (_, row) in enumerate(df.iterrows()):
            if progress_callback and total_rows > 0:
                progress_callback(idx + 1, total_rows)
            try:
                movement = str(row.get("Tipo de Movimentação", row.get("Movimentação", ""))).strip()
                entry_exit = str(row.get("Entrada/Saída", "")).strip().lower()
                date_str = str(row.get("Data do Negócio", row.get("Data", ""))).strip()

                date_parts = date_str.split("/")
                if len(date_parts) == 3:
                    date = f"{date_parts[2]}-{date_parts[1]}-{date_parts[0]}"
                else:
                    date = date_str

                raw_product = str(row.get("Código de Negociação", row.get("Produto", ""))).strip()
                ticker = raw_product.split("-")[0].strip()

                if not ticker or len(ticker) < 5 or not ticker[:4].isalpha():
                    continue

                quantity = int(row.get("Quantidade", 0))
                raw_price = row.get("Preço", row.get("Preço unitário", 0.0))
                price = 0.0 if raw_price == "-" else float(raw_price)

                if ticker == "CXSE3" and date == "2021-04-30" and price == 0.0:
                    price = 9.67

                raw_value = row.get("Valor", row.get("Valor da Operação", 0.0))
                total_value = 0.0 if raw_value == "-" else float(raw_value)

                transaction_type = None
                if "Compra" in movement:
                    transaction_type = "BUY"
                elif "Venda" in movement:
                    transaction_type = "SELL"
                elif (
                    "Desdobro" in movement or "Bonificação" in movement or "Bonificacao" in movement
                ):
                    if "credito" in entry_exit or "crédito" in entry_exit:
                        transaction_type = "SPLIT"
                elif "Grupamento" in movement:
                    transaction_type = "GROUP"
                elif (
                    "Transferência - Liquidação" in movement
                    or "Transferência" in movement
                    or "Transferencia" in movement
                    or "Depósito" in movement
                    or "Deposito" in movement
                ):
                    # Ignore custodian transfers at zero cost (typically labeled as 'Transferência' or 'Transferência - Liquidação' with zero price)
                    is_transfer = (
                        "Transfer" in movement
                        or "Transferência" in movement
                        or "Transferencia" in movement
                    )
                    if is_transfer and (price == 0.0 or raw_price == "-"):
                        continue
                    if "credito" in entry_exit or "crédito" in entry_exit:
                        transaction_type = "BUY"
                    elif "debito" in entry_exit or "débito" in entry_exit:
                        transaction_type = "SELL"
                elif "Resgate" in movement:
                    transaction_type = "SELL"

                if transaction_type == "BUY":
                    success = self.add_transaction(ticker, date, "BUY", quantity, price)
                    if success:
                        processed_transactions += 1
                elif transaction_type == "SELL":
                    success = self.add_transaction(ticker, date, "SELL", quantity, price)
                    if success:
                        processed_transactions += 1
                elif transaction_type == "SPLIT":
                    success = self.add_transaction(ticker, date, "BUY", quantity, 0.0)
                    if success:
                        processed_transactions += 1
                elif transaction_type == "GROUP":
                    success = self.add_transaction(ticker, date, "GROUP", quantity, 0.0)
                    if success:
                        processed_transactions += 1
                elif any(term in movement for term in ["Dividendo", "Juros", "Rendimento"]):
                    dividend_type = "DIVIDEND" if "Dividendo" in movement else "JCP"
                    if "Rendimento" in movement:
                        dividend_type = "YIELD"
                    success = self.add_dividend(ticker, date, dividend_type, total_value)
                    if success:
                        processed_dividends += 1

            except Exception:
                continue

        return processed_transactions, processed_dividends

    @hybridmethod
    def get_quantity_on_date(self, ticker: str, date_str: str, conn=None) -> int:
        """Returns the accumulated quantity owned of a specific ticker on a given date."""
        return self._portfolio_repo.get_quantity_on_date(ticker, date_str, conn=conn)

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
                qty_owned = self._portfolio_repo.get_quantity_on_date(ticker, dt, conn=conn_shared)
                unit_vals.append(total / qty_owned if qty_owned > 0 else 0.0)
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
                    dt = row["Data"]
                    tot = row["Total"]
                    qty_on_date = self._portfolio_repo.get_quantity_on_date(
                        ticker, dt, conn=conn_shared
                    )
                    if qty_on_date > 0:
                        total_paid_per_share += tot / qty_on_date

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
        """Returns static metadata for a specific ticker from the local assets.csv catalog."""
        catalog = self._market_data_api.load_assets_catalog()
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
                "sub_sector": str(row.get("SUBSETOR ", ""))
                if pd.notna(row.get("SUBSETOR "))
                else "",
                "segment": str(row.get("SEGMENTO / ADM / PAÍS", ""))
                if pd.notna(row.get("SEGMENTO / ADM / PAÍS"))
                else "",
                "asset_type": str(row.get("TIPO", "Ação")) if pd.notna(row.get("TIPO")) else "Ação",
            }
        return {
            "name": f"Asset {ticker}",
            "image": "",
            "cnpj": "N/D",
            "sector": "Outros",
            "sub_sector": "",
            "segment": "",
            "asset_type": "Ação",
        }

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
                # Filter positions that have positive quantity and are of type 'Ação'
                owned_stocks = df_positions[
                    df_positions["asset_type"]
                    .str.strip()
                    .str.lower()
                    .isin(["ação", "acao", "ações", "acoes"])
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
        return self._portfolio_repo.get_dividend_corrections(ticker)

    @hybridmethod
    def calculate_prior_invested_amount(self, start_date) -> float:
        """Calculates the net sum of all transactions prior to start_date, bounded to >= 0."""
        if start_date is None:
            return 0.0
        df_all_tx = self._portfolio_repo.get_all_transactions()
        if df_all_tx.empty:
            return 0.0

        df_prev_tx = df_all_tx[df_all_tx["date"] < start_date]
        if df_prev_tx.empty:
            return 0.0

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
                portfolio_state[ticker] = {QUANTITY: 0, AVERAGE_PRICE: 0.0}

            current_state = portfolio_state[ticker]
            old_qty = current_state[QUANTITY]
            old_avg_price = current_state[AVERAGE_PRICE]

            if txn_type == "BUY":
                new_qty = old_qty + qty
                new_avg_price = (
                    (old_qty * old_avg_price + qty * price + fees) / new_qty if new_qty > 0 else 0.0
                )
                portfolio_state[ticker] = {QUANTITY: new_qty, AVERAGE_PRICE: new_avg_price}
            elif txn_type == "SELL":
                new_qty = max(0, old_qty - qty)
                portfolio_state[ticker] = {
                    QUANTITY: new_qty,
                    AVERAGE_PRICE: old_avg_price if new_qty > 0 else 0.0,
                }
            elif txn_type == "GROUP":
                new_qty = qty
                new_avg_price = (old_qty * old_avg_price) / qty if qty > 0 else 0.0
                portfolio_state[ticker] = {QUANTITY: new_qty, AVERAGE_PRICE: new_avg_price}

        active_assets = []
        for ticker, info in portfolio_state.items():
            if info[QUANTITY] > 0:
                if not catalog.empty and ticker in catalog.index:
                    row = catalog.loc[ticker]
                    if isinstance(row, pd.DataFrame):
                        row = row.iloc[0]
                    name = str(row.get("NOME", f"Asset {ticker}"))
                    asset_type = str(row.get("TIPO", "Ação"))
                    sector = str(row.get("SETOR ECONÔMICO", "Outros"))
                    segment = str(row.get("SEGMENTO / ADM / PAÍS", ""))
                    asset_type_clean = asset_type.strip().lower()
                    if asset_type_clean in ["ação", "acao"]:
                        display_sector = segment if segment else sector
                    elif asset_type_clean == "etf":
                        display_sector = "-"
                    else:
                        display_sector = sector
                else:
                    name, asset_type, display_sector = f"Asset {ticker}", "Ação", "Outros"

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
                        AVERAGE_PRICE: info[AVERAGE_PRICE],
                        INVESTED_AMOUNT: info[QUANTITY] * info[AVERAGE_PRICE],
                        TOTAL_DIVIDENDS: total_dividends,
                        L12M_DIVIDENDS: l12m_dividends,
                        YTD_DIVIDENDS: ytd_dividends,
                    }
                )

        return pd.DataFrame(active_assets)

    @hybridmethod
    def calculate_historical_evolution(self, start_date=None) -> pd.DataFrame:
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

        df_transactions[MONTH_STR] = df_transactions[DATE].str[:7]
        df_dividends[MONTH_STR] = df_dividends[DATE].str[:7]

        df_transactions[NET_CASHFLOW] = df_transactions.apply(
            lambda r: (
                (r[QUANTITY] * r[UNIT_PRICE] + r[FEES])
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
    def get_ytd_contributions(self, current_year: int) -> float:
        """Calculates total net contributions made in the current year."""
        limit_date = f"{current_year}-01-01"
        return self._portfolio_repo.get_ytd_contributions_sum(limit_date)

    @hybridmethod
    def get_monthly_contributions_by_year(self, start_date=None) -> pd.DataFrame:
        """Returns monthly contributions grouped by year for the bar chart. Optional start_date filters out older transactions."""
        df_transactions = self._portfolio_repo.get_all_buy_transactions()
        if start_date is not None:
            df_transactions = df_transactions[df_transactions["date"] >= start_date]
        if df_transactions.empty:
            return pd.DataFrame()

        df_transactions["amount"] = (
            df_transactions["quantity"] * df_transactions["unit_price"] + df_transactions["fees"]
        )
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

        market_rows = []
        for t in tracked_tickers:
            details = self._market_data_api.get_ticker_market_analysis(
                t, target_yield_pct=target_yield
            )
            metadata = self.get_asset_metadata(t)

            if details:
                current_year = datetime.date.today().year
                last_5_years = [current_year - i for i in range(1, 6)]

                row_data = {
                    DISPLAY_TICKER: t,
                    DISPLAY_COMPANY: details.get(MARKET_NAME, metadata.get(NAME, t)),
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
        from services.planning_service import SimulationService

        if df_positions.empty:
            return df_positions, {}

        tickers = df_positions[TICKER].tolist()
        quote_map = self._market_data_api.get_batch_quotes(tickers)

        df_positions[CURRENT_PRICE] = df_positions[TICKER].map(quote_map)
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

        total_invested_init = df_positions[INVESTED_AMOUNT].sum()
        total_equity = df_positions[CURRENT_VALUE].sum()

        total_dividends = df_positions[TOTAL_DIVIDENDS].sum()
        l12m_dividends = df_positions[L12M_DIVIDENDS].sum()
        ytd_dividends = df_positions[YTD_DIVIDENDS].sum()

        total_profit = total_equity - total_invested_init
        overall_return = (
            (total_profit / total_invested_init * 100) if total_invested_init > 0 else 0.0
        )

        overall_yoc = (
            (total_dividends / total_invested_init * 100) if total_invested_init > 0 else 0.0
        )
        overall_l12m_yoc = (
            (l12m_dividends / total_invested_init * 100) if total_invested_init > 0 else 0.0
        )

        # Pull the invested capital parameter used in PMT calculations from the planning service
        sim = SimulationService.get_current_simulation()
        total_invested_sim = sim["total_invested"] if sim else 0.0

        return df_positions, {
            "total_equity": total_equity,
            "total_invested": total_invested_sim,
            "total_dividends": total_dividends,
            "l12m_dividends": l12m_dividends,
            "ytd_dividends": ytd_dividends,
            "overall_return": overall_return,
            "overall_yoc": overall_yoc,
            "overall_l12m_yoc": overall_l12m_yoc,
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

        total_equity = df_positions[CURRENT_VALUE].sum()

        df_positions[ADJUSTED_PRICE] = (
            df_positions[INVESTED_AMOUNT] - df_positions[TOTAL_DIVIDENDS]
        ) / df_positions[QUANTITY]
        df_positions[RETURN_PCT_CUSTOM] = (
            df_positions[PROFIT_LOSS] / df_positions[INVESTED_AMOUNT] * 100
        )
        df_positions[YOC_CUSTOM] = (
            df_positions[TOTAL_DIVIDENDS] / df_positions[INVESTED_AMOUNT] * 100
        )
        df_positions[YOC_12_CUSTOM] = (
            df_positions[L12M_DIVIDENDS] / df_positions[INVESTED_AMOUNT] * 100
        )
        df_positions[WEIGHT_PCT] = (
            (df_positions[CURRENT_VALUE] / total_equity * 100) if total_equity > 0 else 0.0
        )

        ceilings = {}
        for t in df_positions[TICKER]:
            details = self._market_data_api.get_ticker_market_analysis(
                t, target_yield_pct=target_yield
            )
            ceilings[t] = details.get("ceiling_price", 0.0) if details else 0.0

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

        return df_display, ceilings
