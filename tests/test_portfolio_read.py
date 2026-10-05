import datetime

import pandas as pd
import pytest

from core.daos.portfolio_dao import PortfolioDAO
from core.utils.market_data import MarketData
from services.assets_service import AssetService
from services.portfolio_read_service import PortfolioReadService


class FakeQuotes:
    def get_batch_quotes(self, tickers):
        return {ticker: 30.0 for ticker in tickers}


class FakeAnalysis:
    def prefetch_tickers(self, tickers):
        pass

    def get_ticker_market_analysis(self, ticker, target_yield_pct=6.0):
        return {"current_price": 30.0, "ceiling_price": 40.0}


def reader():
    return PortfolioReadService(PortfolioDAO(), FakeQuotes(), FakeAnalysis(), MarketData)


def test_portfolio_replays_fees_sales_split_and_group_into_one_read():
    AssetService.add_transaction("BBAS3", "2024-01-01", "BUY", 10, 20, 10)
    AssetService.add_transaction("BBAS3", "2024-02-01", "SELL", 2, 25, 1)
    AssetService.add_transaction("BBAS3", "2024-03-01", "BUY", 8, 0)
    AssetService.add_transaction("BBAS3", "2024-04-01", "GROUP", 4, 0)
    result = reader().read_portfolio(today_date=datetime.date(2024, 6, 1))
    position = result.positions.iloc[0]
    assert position["quantity"] == 4
    assert position["average_price"] == pytest.approx(42)
    assert position["invested_amount"] == pytest.approx(168)
    assert position["current_value"] == 120
    assert result.summary["total_equity"] == 120
    assert not result.holdings.empty


def test_asset_receipts_and_planning_share_historical_ledger_rules():
    AssetService.add_transaction("BBAS3", "2024-01-01", "BUY", 10, 20, 10)
    AssetService.add_transaction("BBAS3", "2024-02-01", "BUY", 10, 0)
    AssetService.add_dividend("BBAS3", "2024-03-01", "DIVIDEND", 40)
    AssetService.add_dividend("BBAS3", "2024-04-01", "JCP", 15, quantity=5, unit_price=3)
    reads = reader()
    asset = reads.read_asset("BBAS3")
    assert asset.dividend_details["Unitário"].tolist() == [3, 2]
    assert asset.annual_dividends["2024"]["total_paid_per_share"] == 5
    assert asset.position["adjusted_price"] == pytest.approx(7.75)
    planning = reads.read_planning(start_date="2024-02-01", year=2024, quantity_date="2024-03-01")
    assert planning.prior_invested == 210
    assert planning.quantities["BBAS3"] == 20
    assert planning.ytd_contributions == 210
    history = reads.read_history("2024-01-01")
    assert history.evolution.iloc[-1]["cumulative_dividends"] == 55
    assert history.evolution.iloc[-1]["cumulative_invested"] == 210


def test_cached_ledger_reopens_and_invalidates_after_writes(monkeypatch, tmp_path):
    import views.cached_market_data as cache

    monkeypatch.setitem(cache._cache_configuration, "path", tmp_path / "screens.db")
    repository = cache.StreamlitCachedPortfolioRepository()
    cache.StreamlitCachedPortfolioRepository._load_ledger.clear()
    reads = PortfolioReadService(repository, FakeQuotes(), FakeAnalysis(), MarketData)
    AssetService.add_transaction("BBAS3", "2024-01-01", "BUY", 10, 20)
    first = reads.read_portfolio()
    # Recover from disk after the in-memory Streamlit cache is lost.
    cache.StreamlitCachedPortfolioRepository._load_ledger.clear()
    original_load = repository._repository.load_ledger
    monkeypatch.setattr(repository._repository, "load_ledger", lambda: pytest.fail("disk snapshot should be reused"))
    reopened = reads.read_portfolio()
    assert reopened.summary == first.summary
    assert reopened.positions.iloc[0]["quantity"] == 10
    monkeypatch.setattr(repository._repository, "load_ledger", original_load)
    AssetService.add_transaction("BBAS3", "2024-02-01", "BUY", 5, 10)
    updated = reads.read_portfolio()
    assert updated.positions.iloc[0]["quantity"] == 15
    assert updated.summary["total_equity"] == 450
    assert first.positions.iloc[0]["quantity"] == 10


def test_quote_updates_do_not_require_local_cache_invalidation():
    from views.cached_market_data import StreamlitCachedPortfolioRepository

    class ChangingQuotes:
        price = 25

        def get_batch_quotes(self, tickers):
            return {ticker: self.price for ticker in tickers}

    quotes = ChangingQuotes()
    reads = PortfolioReadService(StreamlitCachedPortfolioRepository(), quotes, FakeAnalysis(), MarketData)
    AssetService.add_transaction("BBAS3", "2024-01-01", "BUY", 10, 20)
    assert reads.read_portfolio().summary["total_equity"] == 250
    quotes.price = 35
    assert reads.read_asset("BBAS3").market["current_price"] == 35
    assert reads.read_portfolio().summary["total_equity"] == 350


def test_cached_reads_do_not_cross_portfolios_or_restored_generations(monkeypatch, tmp_path):
    import views.cached_market_data as cache
    from core.application_paths import ApplicationPaths
    from core.database import DatabaseManager

    monkeypatch.setitem(cache._cache_configuration, "path", tmp_path / "screens.db")
    generation = ["first"]
    monkeypatch.setattr(ApplicationPaths, "database_generation", lambda _: generation[0])
    db_a = DatabaseManager(tmp_path / "a.db")
    db_b = DatabaseManager(tmp_path / "b.db")
    db_a.init_personal_db()
    db_b.init_personal_db()
    repo_a, repo_b = PortfolioDAO(db_a), PortfolioDAO(db_b)
    repo_a.insert_transaction("2024-01-01", "BBAS3", "BUY", 10, 20, 0)
    repo_b.insert_transaction("2024-01-01", "CXSE3", "BUY", 5, 10, 0)
    reads_a = PortfolioReadService(cache.StreamlitCachedPortfolioRepository(repo_a), FakeQuotes(), FakeAnalysis(), MarketData)
    reads_b = PortfolioReadService(cache.StreamlitCachedPortfolioRepository(repo_b), FakeQuotes(), FakeAnalysis(), MarketData)
    assert reads_a.read_portfolio().positions.iloc[0]["ticker"] == "BBAS3"
    assert reads_b.read_portfolio().positions.iloc[0]["ticker"] == "CXSE3"
    # A restored file can have the same revision as the previous file.
    replacement = repo_a.load_ledger()
    replacement.transactions.loc[:, "ticker"] = "NEW4"
    monkeypatch.setattr(repo_a, "load_ledger", lambda: replacement)
    generation[0] = "restored"
    assert reads_a.read_portfolio().positions.iloc[0]["ticker"] == "NEW4"


def test_empty_portfolio_returns_usable_named_results():
    reads = reader()
    assert reads.read_portfolio().positions.empty
    assert reads.read_portfolio().summary == {}
    assert reads.read_asset("BBAS3").transactions.empty
    assert reads.read_asset("BBAS3").annual_dividends == {}
    assert reads.read_history().evolution.empty
    assert reads.read_planning().total_invested == 0


def test_portfolio_read_is_coherent_when_a_write_commits_between_queries(monkeypatch):
    repository = PortfolioDAO()
    with repository.get_personal_connection() as connection:
        connection.execute("PRAGMA journal_mode=WAL")
    connection.close()
    AssetService.add_transaction("BBAS3", "2024-01-01", "BUY", 10, 20)
    original_query = pd.read_sql_query
    inserted = []

    def interleave_write(sql, connection, *args, **kwargs):
        if "FROM dividends ORDER BY" in sql and not inserted:
            inserted.append(True)
            AssetService.add_dividend("BBAS3", "2024-01-02", "DIVIDEND", 20)
        return original_query(sql, connection, *args, **kwargs)

    monkeypatch.setattr(pd, "read_sql_query", interleave_write)
    reads = reader()
    first = reads.read_portfolio()
    assert inserted == [True]
    assert first.summary["total_dividends"] == 0
    assert first.positions.iloc[0]["total_dividends"] == 0
    assert reads.read_portfolio().summary["total_dividends"] == 20


def test_annual_dividend_totals_include_legacy_receipt_types():
    AssetService.add_dividend("BBAS3", "2024-01-02", "OTHER", 20)
    AssetService.add_dividend("BBAS3", "2024-02-02", "YIELD", 30)
    annual = reader().read_asset("BBAS3").annual_dividends["2024"]
    assert annual["yields"] == 50
    assert annual["total"] == 50
    assert annual["pivot"].iloc[2]["Valor (R$)"] == 50
    assert annual["pivot"].iloc[3]["Valor (R$)"] == 50


def test_holdings_consume_public_market_analysis_with_current_portfolio_corrections():
    from services.market_analysis_service import MarketAnalysisService
    from views.cached_market_data import StreamlitCachedPortfolioRepository

    class RemoteSnapshot:
        def get_ticker_market_snapshot(self, ticker, reference_year):
            dividends = {reference_year - offset: 2 for offset in range(1, 6)}
            return {"current_price": 30, "dividends_5y": dividends, "dividends_history": dividends,
                    "annual_closing_prices": dict.fromkeys(dividends, 30)}

    repository = PortfolioDAO()
    analysis = MarketAnalysisService(RemoteSnapshot(), repository)
    reads = PortfolioReadService(StreamlitCachedPortfolioRepository(repository), FakeQuotes(), analysis, MarketData)
    AssetService.add_transaction("CXSE3", "2024-01-01", "BUY", 10, 20)
    assert reads.read_portfolio().ceilings["CXSE3"] == pytest.approx(33.333333333)
    AssetService.save_dividend_correction("CXSE3", datetime.date.today().year - 1, 10)
    updated = reads.read_portfolio()
    assert updated.ceilings["CXSE3"] == pytest.approx(60)
    assert updated.positions.iloc[0]["invested_amount"] == 200
