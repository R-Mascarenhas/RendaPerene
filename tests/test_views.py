from services.portfolio_read_service import PortfolioReadService
from core.database import db
from core.portfolio_read import PortfolioPlanning, AssetRead
from types import SimpleNamespace
import pytest
import os
import re
import datetime
import pandas as pd
import streamlit as st
from services.assets_service import AssetService
from services.planning_service import SimulationService
from views.planning_view import PlanningView
from views.components.charts import DashboardCharts


class _FakeAssetTab:
    def __init__(self, open):
        self.open = open

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _fake_tabs(labels, **_kwargs):
    return [_FakeAssetTab(index == 0) for index, _ in enumerate(labels)]


@pytest.mark.parametrize("transaction_date", [None, "2024-01-10"])
def test_planning_time_metric_uses_effective_start_date(monkeypatch, transaction_date):
    from views.components.time_metrics import TimeMetricsWidget

    SimulationService.save_configuration(
        birth_date="1992-12-15",
        retirement_age=60,
        desired_income_mw=5.0,
        annual_interest_rate=6.0,
        mw_value=1412.0,
        initial_equity_input=0.0,
    )
    if transaction_date:
        AssetService.add_transaction("BBAS3", transaction_date, "BUY", 10, 20.0)
    sim = SimulationService.get_current_simulation()
    metrics = []
    column = SimpleNamespace(metric=lambda *args: metrics.append(args))
    monkeypatch.setattr(st, "subheader", lambda *args: None)
    monkeypatch.setattr(st, "columns", lambda *args: [column, column])
    TimeMetricsWidget().render(sim)
    expected_description = (
        "Planejamento iniciado aos 31 anos"
        if transaction_date
        else "Planejamento iniciado Hoje"
    )
    assert metrics[0][2] == expected_description


def test_views_and_services_sanity():
    """Automated SCM Sanity and View Import/Attribute Verification Test."""
    for name in ("read_portfolio", "read_asset", "read_history", "read_planning"):
        assert hasattr(PortfolioReadService, name)
    from services.assets_service import AssetService


    from services.planning_service import SimulationService

    assert hasattr(SimulationService, "get_configuration")
    assert hasattr(SimulationService, "save_configuration")
    assert hasattr(SimulationService, "get_initial_investment_age")
    assert hasattr(SimulationService, "get_current_simulation")
    assert hasattr(SimulationService, "build_projection_dataframe")
    assert hasattr(SimulationService, "get_updated_required_contribution")
    assert hasattr(SimulationService, "get_required_contribution")

    from services.assets_service import AssetService

    assert hasattr(AssetService, "add_transaction")
    assert hasattr(AssetService, "add_dividend")
    assert hasattr(AssetService, "process_b3_import")
    assert hasattr(AssetService, "get_asset_metadata")
    assert hasattr(AssetService, "get_tracked_market_assets")
    assert hasattr(AssetService, "add_tracked_market_asset")
    assert hasattr(AssetService, "remove_tracked_market_asset")

    from views.dashboard_view import DashboardView

    assert hasattr(DashboardView, "render")

    from views.planning_view import PlanningView

    assert hasattr(PlanningView, "render")

    from views.assets_view import AssetsView

    assert hasattr(AssetsView, "render")

    from views.operations_view import OperationsView

    assert hasattr(OperationsView, "render")

    from views.portfolio_view import PortfolioView

    assert hasattr(PortfolioView, "render")

    from views.market_view import MarketView
    from views.goals_view import GoalsView

    assert hasattr(MarketView, "render")


def test_market_view_renders_only_the_selected_secondary_navigation(monkeypatch):
    """The inactive market screen must not run its network-backed renderer."""
    from core.strings import TAB_ASSET_DEEP_DIVE
    from views.market_view import MarketView
    from views.asset_deep_dive_view import AssetDeepDiveView
    from views.market_monitoring_view import MarketMonitoringView

    rendered = []
    monkeypatch.setattr(st, "segmented_control", lambda *args, **kwargs: TAB_ASSET_DEEP_DIVE)
    monkeypatch.setattr(MarketMonitoringView, "render", lambda self: rendered.append("monitoring"))
    monkeypatch.setattr(AssetDeepDiveView, "render", lambda self: rendered.append("deep_dive"))

    MarketView().render()

    assert rendered == ["deep_dive"]


def test_asset_information_renders_without_opening_editors(monkeypatch):
    from views.portfolio_view import PortfolioView
    from views.components.manual_entry import ManualEntryWidget
    from views.components.asset_annual_goal import AssetAnnualGoalWidget

    calls = []
    monkeypatch.setattr(st, "tabs", _fake_tabs)
    monkeypatch.setattr(
        PortfolioReadService,
        "read_planning",
        lambda *args, **kwargs: PortfolioPlanning(pd.DataFrame([{"ticker": "ABCD3"}]), 0, 0, 0),
    )
    monkeypatch.setattr(AssetService, "get_pending_tickers", lambda: [])
    monkeypatch.setattr(ManualEntryWidget, "render", lambda *args: calls.append("entry"))
    monkeypatch.setattr(AssetAnnualGoalWidget, "render", lambda *args: calls.append("goal"))
    monkeypatch.setattr(AssetService, "get_asset_metadata", lambda *args: {})
    monkeypatch.setattr(AssetService, "get_asset_market_analysis", lambda *args: {})
    monkeypatch.setattr(PortfolioReadService, "read_asset", lambda ticker: (calls.append("detail") or AssetRead(ticker, {}, {"quantity": 1}, {}, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), {})))
    for name in (
        "_render_header_metadata_block", "_render_behavior_chart", "_render_proventos_pivot_table",
        "_render_indicators_block", "_render_transactions_and_dividends_tables",
    ):
        monkeypatch.setattr(PortfolioView, name, lambda *args, name=name: calls.append(name))

    PortfolioView().render()

    assert "entry" not in calls
    assert "goal" not in calls
    assert "_render_behavior_chart" in calls
    assert "detail" in calls
    assert "_render_proventos_pivot_table" in calls
    assert "_render_transactions_and_dividends_tables" in calls


def test_asset_tabs_render_only_the_selected_ticker(monkeypatch):
    from views.portfolio_view import PortfolioView

    rendered = []
    options = []
    monkeypatch.setattr(
        PortfolioReadService,
        "read_planning",
        lambda: PortfolioPlanning(pd.DataFrame({"ticker": ["CXSE3", "BBAS3"]}), 0, 0, 0),
    )
    monkeypatch.setattr(AssetService, "get_pending_tickers", lambda: [])

    def tabs(labels, **kwargs):
        options.extend(labels)
        assert kwargs["on_change"] == "rerun"
        return [_FakeAssetTab(False), _FakeAssetTab(True)]

    monkeypatch.setattr(st, "tabs", tabs)
    monkeypatch.setattr(
        PortfolioView,
        "_render_single_asset_subtab",
        lambda self, ticker, positions: rendered.append(ticker),
    )

    PortfolioView().render()

    assert options == ["BBAS3", "CXSE3"]
    assert rendered == ["CXSE3"]


def test_native_asset_tabs_switch_without_rendering_hidden_tickers(monkeypatch):
    import hashlib
    import streamlit.env_util
    from streamlit.testing.v1 import AppTest
    from views.portfolio_view import PortfolioView

    monkeypatch.setattr(streamlit.env_util, "is_repl", lambda: False)
    monkeypatch.setattr(
        PortfolioReadService,
        "read_planning",
        lambda: PortfolioPlanning(pd.DataFrame({"ticker": ["BBAS3", "CXSE3"]}), 0, 0, 0),
    )
    monkeypatch.setattr("views.portfolio_view.portfolio_context", lambda: ("portfolio", "gen", 1))
    monkeypatch.setattr(AssetService, "get_pending_tickers", lambda: [])
    rendered = []
    monkeypatch.setattr(
        PortfolioView,
        "_render_single_asset_subtab",
        lambda self, ticker, positions: rendered.append(ticker),
    )

    app = AppTest.from_string('''
from views.portfolio_view import PortfolioView
PortfolioView().render()
''').run(timeout=15)
    assert not app.exception
    assert len(app.tabs) == 2
    assert rendered == ["BBAS3"]

    digest = hashlib.sha256(repr(["BBAS3", "CXSE3"]).encode("utf-8")).hexdigest()[:12]
    app.session_state[f"asset_tabs_portfolio_gen_{digest}"] = "CXSE3"
    app.run(timeout=15)
    assert not app.exception
    assert rendered == ["BBAS3", "CXSE3"]


def test_chart_theme_adapter_uses_dark_empty_cells_for_heatmaps(monkeypatch):
    """Heatmaps must not introduce a light background in the dark application theme."""
    from views.components.chart_theme import ChartThemeAdapter

    monkeypatch.setattr(ChartThemeAdapter, "is_dark_theme", lambda: True)

    assert ChartThemeAdapter.heatmap_empty_color() == "#2a2f36"


def test_asset_deep_dive_renders_cached_price_history(monkeypatch):
    """The Raio-X price chart must request the same cached history adapter as My Assets."""
    from views.asset_deep_dive_view import AssetDeepDiveView
    from views.cached_market_data import StreamlitCachedMarketData
    from views.components.chart_theme import ChartThemeAdapter

    class Spinner:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    calls = []
    history = pd.DataFrame(
        {"Close": [10.0, 11.0]}, index=pd.to_datetime(["2025-01-01", "2025-01-02"])
    )
    monkeypatch.setattr(st, "subheader", lambda *args, **kwargs: None)
    monkeypatch.setattr(st, "radio", lambda *args, **kwargs: "1 Ano")
    monkeypatch.setattr(st, "spinner", lambda *args, **kwargs: Spinner())
    monkeypatch.setattr(st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(st, "metric", lambda *args, **kwargs: None)
    monkeypatch.setattr(st, "plotly_chart", lambda figure, **kwargs: calls.append(figure))
    monkeypatch.setattr(ChartThemeAdapter, "apply_theme", lambda figure: figure)
    monkeypatch.setattr(
        StreamlitCachedMarketData,
        "get_ticker_history",
        lambda ticker, period, interval: history,
    )

    AssetDeepDiveView._render_asset_price_history("BBAS3")

    assert len(calls) == 1
    assert calls[0].data[0].name == "Preço de Fechamento"


def test_raio_x_information_renders_when_ticker_is_selected(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import streamlit.env_util
    from views.asset_deep_dive_view import AssetDeepDiveView

    monkeypatch.setattr(streamlit.env_util, "is_repl", lambda: False)
    monkeypatch.setattr(AssetService, "get_asset_catalog_entries", lambda: [("BBAS3", "Banco")])
    monkeypatch.setattr(AssetService, "get_asset_market_analysis", lambda *args: {
        "current_price": 25.0,
        "metadata": {"name": "Banco", "sector": "Financeiro"},
    })
    monkeypatch.setattr(AssetDeepDiveView, "_get_current_target_yield", lambda self: 6.0)
    rendered = []
    for name in (
        "_render_favorite_button", "_render_quote_snapshot", "_render_asset_price_history",
        "_render_dividend_event_map", "_render_dividend_history", "_render_market_indicators",
    ):
        monkeypatch.setattr(AssetDeepDiveView, name, lambda *args, name=name: rendered.append(name))

    app = AppTest.from_string('''
from views.asset_deep_dive_view import AssetDeepDiveView
AssetDeepDiveView().render()
''').run(timeout=15)
    app.selectbox[0].set_value("BBAS3 - Banco").run(timeout=15)

    assert not app.exception
    assert "_render_asset_price_history" in rendered
    assert "_render_dividend_event_map" in rendered
    assert "_render_dividend_history" in rendered
    assert "_render_market_indicators" in rendered


def test_dividend_event_hover_shows_monthly_total_per_share():
    from views.asset_deep_dive_view import AssetDeepDiveView

    hover_text = AssetDeepDiveView._format_dividend_event_hover(1.0)

    assert hover_text == "Total de proventos no mês: R$ 1,00 por ação"


def test_asset_deep_dive_uses_last_valid_close_when_latest_history_row_is_empty(monkeypatch):
    """Weekend or holiday rows without a close must not make the displayed quote NaN."""
    from views.asset_deep_dive_view import AssetDeepDiveView
    from views.cached_market_data import StreamlitCachedMarketData
    from views.components.chart_theme import ChartThemeAdapter

    class Spinner:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    metrics = []
    history = pd.DataFrame(
        {"Close": [10.0, 11.0, float("nan")]},
        index=pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-04"]),
    )
    monkeypatch.setattr(st, "subheader", lambda *args, **kwargs: None)
    monkeypatch.setattr(st, "radio", lambda *args, **kwargs: "1 Ano")
    monkeypatch.setattr(st, "spinner", lambda *args, **kwargs: Spinner())
    monkeypatch.setattr(st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(st, "metric", lambda *args, **kwargs: metrics.append(args))
    monkeypatch.setattr(st, "plotly_chart", lambda *args, **kwargs: None)
    monkeypatch.setattr(ChartThemeAdapter, "apply_theme", lambda figure: figure)
    monkeypatch.setattr(
        StreamlitCachedMarketData,
        "get_ticker_history",
        lambda ticker, period, interval: history,
    )

    AssetDeepDiveView._render_asset_price_history("BBAS3")

    assert metrics[0][1] == "R$ 11,00"


def test_portfolio_chart_uses_last_valid_close_when_latest_history_row_is_empty(monkeypatch):
    """My Assets uses the same prior-business-day close fallback as the Raio-X."""
    from views.portfolio_view import PortfolioView
    from views.cached_market_data import StreamlitCachedMarketData

    class Spinner:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    markdown_calls = []
    history = pd.DataFrame(
        {"Close": [10.0, 11.0, float("nan")]},
        index=pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-04"]),
    )
    monkeypatch.setattr(st, "markdown", lambda text, **kwargs: markdown_calls.append(text))
    monkeypatch.setattr(st, "radio", lambda *args, **kwargs: "1 Ano")
    monkeypatch.setattr(st, "spinner", lambda *args, **kwargs: Spinner())
    monkeypatch.setattr(st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(st, "plotly_chart", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        StreamlitCachedMarketData,
        "get_ticker_history",
        lambda ticker, period, interval: history,
    )

    PortfolioView()._render_behavior_chart("BBAS3", {"transaction_history": pd.DataFrame()})

    assert any("R$ 11,00" in text for text in markdown_calls)


def test_portfolio_view_renders_missing_market_multiples_as_unavailable(monkeypatch):
    """Owned-asset details stay available when Yahoo omits P/L and P/VP."""
    from core.strings import LABEL_PE_RATIO, LABEL_P_VP
    from views.cached_market_data import StreamlitCachedMarketData
    from views.portfolio_view import PortfolioView
    from views.components.manual_entry import ManualEntryWidget
    from views.components.asset_annual_goal import AssetAnnualGoalWidget

    monkeypatch.setattr(ManualEntryWidget, "render", lambda self, ticker: None)
    monkeypatch.setattr(AssetAnnualGoalWidget, "render", lambda self, ticker: None)

    class Container:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def metric(self, label, value, **kwargs):
            metrics[label] = value

    metrics = {}
    positions = pd.DataFrame(
        [
            {
                "ticker": "BBAS3",
                "quantity": 10,
                "total_dividends": 5.0,
                "invested_amount": 200.0,
                "average_price": 20.0,
                "l12m_dividends": 2.0,
            }
        ]
    )

    monkeypatch.setattr(st, "subheader", lambda *args, **kwargs: None)
    monkeypatch.setattr(st, "tabs", _fake_tabs)
    monkeypatch.setattr(st, "spinner", lambda *args, **kwargs: Container())
    monkeypatch.setattr(
        st,
        "columns",
        lambda specification: [
            Container()
            for _ in range(specification if isinstance(specification, int) else len(specification))
        ],
    )
    monkeypatch.setattr(st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(st, "write", lambda *args, **kwargs: None)
    monkeypatch.setattr(st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(st, "radio", lambda *args, **kwargs: "1 Ano")
    monkeypatch.setattr(st, "plotly_chart", lambda *args, **kwargs: None)
    positions["adjusted_price"] = 19.5
    positions["monthly_l12m_yoc"] = 2 / 200 * 100 / 12
    monkeypatch.setattr(PortfolioReadService, "read_planning", lambda: PortfolioPlanning(positions, 200, 0, 0))
    monkeypatch.setattr(PortfolioReadService, "read_asset", lambda ticker: AssetRead(
        ticker, {"name": "Banco do Brasil"}, positions.iloc[0].to_dict(),
        {"current_price": 20.0, "dy": 0.0, "pe": None, "pb": None, "high_52w": 0.0, "low_52w": 0.0},
        pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), {},
    ))
    monkeypatch.setattr(
        StreamlitCachedMarketData,
        "get_ticker_history",
        lambda ticker, period, interval: pd.DataFrame(),
    )

    PortfolioView().render()

    assert metrics[LABEL_PE_RATIO] == "N/D"
    assert metrics[LABEL_P_VP] == "N/D"


def test_asset_deep_dive_favorite_adds_ticker_to_market_watchlist(monkeypatch):
    """Favoriting a Raio-X asset persists it in the existing market monitor list."""
    from views.asset_deep_dive_view import AssetDeepDiveView

    added_tickers = []
    monkeypatch.setattr(AssetService, "get_tracked_market_assets", lambda include_owned=True: [])
    monkeypatch.setattr(st, "button", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        AssetService,
        "add_tracked_market_asset",
        lambda ticker: added_tickers.append(ticker) or True,
    )
    monkeypatch.setattr(st, "success", lambda *args, **kwargs: None)
    monkeypatch.setattr(st, "rerun", lambda: None)

    AssetDeepDiveView._render_favorite_button("BBAS3")

    assert added_tickers == ["BBAS3"]


def test_asset_deep_dive_marks_owned_asset_as_favorited_without_allowing_removal(monkeypatch):
    """Assets monitored through the portfolio show a filled, non-removable favorite state."""
    from views.asset_deep_dive_view import AssetDeepDiveView

    button_calls = []
    monkeypatch.setattr(
        AssetService,
        "get_tracked_market_assets",
        lambda include_owned=True: ["BBAS3"] if include_owned else [],
    )
    monkeypatch.setattr(
        st,
        "button",
        lambda label, **kwargs: button_calls.append((label, kwargs)) or False,
    )

    AssetDeepDiveView._render_favorite_button("BBAS3")

    assert button_calls[0][0] == "★ Favorito"
    assert button_calls[0][1]["disabled"] is True


def test_asset_deep_dive_unfavorites_manual_asset(monkeypatch):
    """Manual favorites can be removed without affecting assets held in the portfolio."""
    from views.asset_deep_dive_view import AssetDeepDiveView

    removed_tickers = []
    monkeypatch.setattr(
        AssetService,
        "get_tracked_market_assets",
        lambda include_owned=True: ["BBAS3"],
    )
    monkeypatch.setattr(st, "button", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        AssetService,
        "remove_tracked_market_asset",
        lambda ticker: removed_tickers.append(ticker) or True,
    )
    monkeypatch.setattr(st, "success", lambda *args, **kwargs: None)
    monkeypatch.setattr(st, "rerun", lambda: None)

    AssetDeepDiveView._render_favorite_button("BBAS3")

    assert removed_tickers == ["BBAS3"]


def test_app_py_static_syntax_sanity():
    """
    Statically analyzes app.py as plaintext to ensure no obsolete calls
    or deleted assets database initialization functions are referenced,
    fully protecting the startup flow before Streamlit boot.
    """
    assert os.path.exists("app.py")
    with open("app.py", "r", encoding="utf-8") as f:
        content = f.read()

    assert "init_assets_db" not in content, (
        "FALHA: O arquivo app.py ainda referencia o método obsoleto 'init_assets_db'!"
    )
    assert "get_assets_connection" not in content, (
        "FALHA: O arquivo app.py ainda referencia a conexão obsoleta 'get_assets_connection'!"
    )


def test_views_static_db_imports_sanity():
    """
    Statically analyzes all visual view files inside views/ directory.
    Ensures that if 'db' is referenced in a file, 'from core.database import db'
    must also be imported in that file, preventing dynamic NameErrors.
    """
    views_dir = "views"
    assert os.path.exists(views_dir)

    # Loop through view files
    for file_name in os.listdir(views_dir):
        file_path = os.path.join(views_dir, file_name)
        if os.path.isfile(file_path) and file_name.endswith(".py"):
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # If 'db' is used (e.g. calling db.get_personal_connection() or db.X),
            # verify that the database connection object was imported
            if " db." in content or "=db." in content:
                assert "from core.database import db" in content, (
                    f"FALHA: O arquivo {file_path} referencia o objeto de banco 'db', "
                    f"mas não importa 'from core.database import db'!"
                )


def test_views_no_duplicate_widget_keys_sanity():
    """
    Statically analyzes all visual view files inside views/ directory and sub-directories.
    Extracts all occurrences of key="..." or key='...' and asserts that within
    any single file, there are absolutely zero duplicate Streamlit widget keys,
    completely preventing StreamlitDuplicateElementKey exceptions.
    """
    views_dir = "views"
    assert os.path.exists(views_dir)

    # Simple regex to extract widget keys like key="my_key" or key='my_key'
    key_pattern = re.compile(r"key\s*=\s*['\"]([^'\"]+)['\"]")

    # Recursively traverse views/ directory
    for root, dirs, files in os.walk(views_dir):
        for file_name in files:
            if file_name.endswith(".py"):
                file_path = os.path.join(root, file_name)
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                found_keys = key_pattern.findall(content)

                # Check for duplicates inside this file
                seen_keys = set()
                duplicates = []
                for k in found_keys:
                    if k in seen_keys:
                        duplicates.append(k)
                    seen_keys.add(k)

                assert len(duplicates) == 0, (
                    f"FALHA: O arquivo {file_path} possui chaves de widgets duplicadas: {duplicates}! "
                    f"Cada widget Streamlit em um mesmo arquivo deve possuir uma chave 'key' única."
                )


def test_views_session_state_persistent_keys_sanity():
    """
    Statically analyzes views/planning_view.py to ensure that unmountable, toggled
    widgets (like desired_income_mw and desired_income_fixed) do not bind directly
    as widget keys in st.session_state (which Streamlit deletes upon unmounting).
    Verifies that they utilize protected '_val' keys as their source of truth.
    """
    assert os.path.exists("views/planning_view.py")
    with open("views/planning_view.py", "r", encoding="utf-8") as f:
        content = f.read()

    assert 'key="desired_income_mw"' not in content, (
        "FALHA: O arquivo views/planning_view.py ainda vincula diretamente a chave 'desired_income_mw' como chave de widget! "
        "Use 'desired_income_mw_input' e salve o valor dinamicamente para evitar exclusões do Streamlit no unmount."
    )
    assert 'key="desired_income_fixed"' not in content, (
        "FALHA: O arquivo views/planning_view.py ainda vincula diretamente a chave 'desired_income_fixed' como chave de widget! "
        "Use 'desired_income_fixed_input' e salve o valor dinamicamente para evitar exclusões do Streamlit no unmount."
    )


def test_views_static_market_data_methods_sanity():
    """
    Statically analyzes all files inside views/ (including sub-folders) to ensure
    any referenced market method corresponds to the presentation adapter actually
    imported by the views, including its background-refresh status interface.
    """
    from views.cached_market_data import StreamlitCachedMarketData

    # 1. Dynamically retrieve all public/callable method names from MarketData
    valid_methods = {name for name in dir(StreamlitCachedMarketData) if not name.startswith("_")}

    # 2. Setup regex to capture 'MarketData.some_method' calls
    call_pattern = re.compile(r"\b(?:MarketData|StreamlitCachedMarketData)\.([a-zA-Z0-9_]+)")

    views_dir = "views"
    assert os.path.exists(views_dir)

    # Traverse views directory
    for root, dirs, files in os.walk(views_dir):
        for file_name in files:
            if file_name.endswith(".py") and file_name != "cached_market_data.py":
                file_path = os.path.join(root, file_name)
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                matches = call_pattern.findall(content)
                for called_method in matches:
                    assert called_method in valid_methods, (
                        f"FALHA: O arquivo {file_path} tenta chamar 'MarketData.{called_method}()', "
                        f"mas esse método não existe na classe MarketData! Métodos válidos: {valid_methods}"
                    )


def test_views_and_widgets_import_integrity():
    """
    Quality gate test to verify that all major Streamlit view and widget classes
    can be imported and parsed by the Python interpreter cleanly, avoiding NameError
    or syntax regressions on constants/imports.
    """
    from views.components.projection_chart import ProjectionChartWidget
    from views.components.charts import DashboardCharts
    from views.components.annual_planning import AnnualPlanningWidget
    from views.components.detailed_holdings import DetailedHoldingsWidget
    from views.components.patrimony_summary import PatrimonySummaryWidget
    from views.components.simulation_results import SimulationResultsWidget
    from views.components.time_metrics import TimeMetricsWidget

    from views.planning_view import PlanningView
    from views.dashboard_view import DashboardView
    from views.portfolio_view import PortfolioView
    from views.operations_view import OperationsView
    from views.assets_view import AssetsView
    from views.market_view import MarketView
    from views.goals_view import GoalsView

    # Verify instantiations don't raise syntax/import-time failures
    assert ProjectionChartWidget is not None
    assert DashboardCharts is not None
    assert PlanningView is not None
    assert DashboardView is not None
    assert GoalsView is not None


def test_operations_view_only_offers_owned_assets_for_sales(mock_db, monkeypatch):
    """The manual sale selector must contain only assets with a current position."""
    from views.operations_view import OperationsView

    monkeypatch.setattr(
        AssetService,
        "get_owned_tickers",
        lambda: ["BBAS3"],
    )
    catalog = pd.DataFrame(
        {"NOME": ["Banco do Brasil", "Caixa Seguridade"]}, index=["BBAS3", "CXSE3"]
    )

    available = OperationsView()._get_available_tickers("Venda (Resgate)", catalog)

    assert available == ["BBAS3"]


def test_operations_view_offers_uncatalogued_owned_asset_for_sales(mock_db, monkeypatch):
    from views.operations_view import OperationsView

    monkeypatch.setattr(AssetService, "get_owned_tickers", lambda: ["MOCK4"])
    catalog = pd.DataFrame({"NOME": ["Banco do Brasil"]}, index=["BBAS3"])

    available = OperationsView()._get_available_tickers("Venda (Resgate)", catalog)

    assert available == ["MOCK4"]


def test_operations_view_accepts_a_new_ticker_for_manual_purchase(mock_db, monkeypatch):
    from contextlib import nullcontext

    from views.operations_view import OperationsView

    ticker_selectbox = {}

    def selectbox(label, options, **kwargs):
        if label == "Tipo de Lançamento":
            return "Compra (Aporte)"
        ticker_selectbox.update(options=options, kwargs=kwargs)
        return "--- Selecione ---"

    monkeypatch.setattr(st, "subheader", lambda *args, **kwargs: None)
    monkeypatch.setattr(st, "selectbox", selectbox)
    monkeypatch.setattr(st, "form", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(st, "date_input", lambda *args, **kwargs: datetime.date.today())
    monkeypatch.setattr(st, "number_input", lambda *args, **kwargs: kwargs["value"])
    monkeypatch.setattr(st, "form_submit_button", lambda *args, **kwargs: False)

    OperationsView()._render_unified_manual_form()

    assert ticker_selectbox["kwargs"]["accept_new_options"] is True


def test_operations_view_reports_invalid_free_form_ticker_without_saving(mock_db, monkeypatch):
    from contextlib import nullcontext

    from views.operations_view import OperationsView

    errors = []

    def selectbox(label, options, **kwargs):
        if label == "Tipo de Lançamento":
            return "Compra (Aporte)"
        return "Petrobras"

    monkeypatch.setattr(st, "subheader", lambda *args, **kwargs: None)
    monkeypatch.setattr(st, "selectbox", selectbox)
    monkeypatch.setattr(st, "form", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(st, "date_input", lambda *args, **kwargs: datetime.date.today())
    monkeypatch.setattr(st, "number_input", lambda *args, **kwargs: kwargs["value"])
    monkeypatch.setattr(st, "form_submit_button", lambda *args, **kwargs: True)
    monkeypatch.setattr(st, "error", errors.append)
    monkeypatch.setattr(st.cache_data, "clear", lambda: None)
    monkeypatch.setattr(st, "rerun", lambda: None)

    OperationsView()._render_unified_manual_form()

    assert errors == ["Informe um ticker válido da B3, como PETR4, BOVA11, NUBR33 ou PETR4F."]
    assert PortfolioReadService.read_planning().positions.empty


def test_operations_view_labels_uncatalogued_owned_ticker_neutrally(mock_db, monkeypatch):
    from contextlib import nullcontext

    from views.operations_view import OperationsView

    ticker_options = []

    def selectbox(label, options, **kwargs):
        if label == "Tipo de Lançamento":
            return "Venda (Resgate)"
        ticker_options.extend(options)
        return "--- Selecione ---"

    monkeypatch.setattr(AssetService, "get_owned_tickers", lambda: ["MOCK4"])
    monkeypatch.setattr(st, "subheader", lambda *args, **kwargs: None)
    monkeypatch.setattr(st, "selectbox", selectbox)
    monkeypatch.setattr(st, "form", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(st, "date_input", lambda *args, **kwargs: datetime.date.today())
    monkeypatch.setattr(st, "number_input", lambda *args, **kwargs: kwargs["value"])
    monkeypatch.setattr(st, "form_submit_button", lambda *args, **kwargs: False)

    OperationsView()._render_unified_manual_form()

    assert "MOCK4 - Ativo não catalogado" in ticker_options


def test_market_monitoring_preserves_initial_equity_flags(mock_db, monkeypatch):
    from core.constants import (
        ANNUAL_INTEREST_RATE,
        BIRTH_DATE,
        DESIRED_INCOME_FIXED,
        DESIRED_INCOME_MW,
        DESIRED_INCOME_TYPE,
        INITIAL_EQUITY_AUTO,
        INITIAL_EQUITY_INPUT,
        INITIAL_EQUITY_MANUAL_OVERRIDE,
        MW_VALUE,
        RETIREMENT_AGE,
        SESSION_BAZIN_TARGET_SPREAD,
        SESSION_BAZIN_TARGET_YIELD,
        SESSION_CEILING_MODEL_SELECTION,
    )
    from views.market_monitoring_view import MarketMonitoringView

    config = {
        BIRTH_DATE: "1990-01-01",
        RETIREMENT_AGE: 65,
        DESIRED_INCOME_MW: 10.0,
        ANNUAL_INTEREST_RATE: 6.0,
        MW_VALUE: 1518.0,
        DESIRED_INCOME_TYPE: "MULTIPLIER",
        DESIRED_INCOME_FIXED: 10000.0,
        INITIAL_EQUITY_INPUT: 10000.0,
        INITIAL_EQUITY_AUTO: True,
        INITIAL_EQUITY_MANUAL_OVERRIDE: False,
    }
    saved = {}
    monkeypatch.setattr(SimulationService, "get_configuration", lambda: config)
    monkeypatch.setattr(
        SimulationService,
        "save_configuration",
        lambda *args, **kwargs: saved.update(args=args, kwargs=kwargs),
    )
    st.session_state[SESSION_CEILING_MODEL_SELECTION] = "Bazin Clássico"
    st.session_state[SESSION_BAZIN_TARGET_YIELD] = 6.0
    st.session_state[SESSION_BAZIN_TARGET_SPREAD] = 3.0

    MarketMonitoringView()._save_market_params()

    assert saved["kwargs"]["initial_equity_auto"] is True
    assert saved["kwargs"]["initial_equity_manual_override"] is False
    assert saved["args"][5] == 10000.0


def test_planning_view_start_date_change_callback(mock_db, monkeypatch):
    """
    Verifies that PlanningView._on_planning_start_date_change correctly syncs state,
    calculates prior invested amount, and runs without a NameError.
    """
    from core.constants import (
        INITIAL_EQUITY_AUTO,
        SESSION_BIRTH_DATE,
        SESSION_RETIREMENT_AGE,
        SESSION_DESIRED_INCOME_MW,
        SESSION_ANNUAL_INTEREST_RATE,
        SESSION_MW_VALUE,
        SESSION_DESIRED_INCOME_TYPE,
        SESSION_DESIRED_INCOME_FIXED,
        SESSION_INITIAL_EQUITY,
        SESSION_PLANNING_START_DATE,
        WIDGET_PLANNING_START_DATE,
        SESSION_PLANNING_START_DATE_ENABLED,
    )

    # Mock st.session_state as a standard dict with all required initial keys
    mock_session = {
        SESSION_BIRTH_DATE: datetime.date(1990, 1, 1),
        SESSION_RETIREMENT_AGE: 65,
        SESSION_DESIRED_INCOME_MW: 10.0,
        SESSION_ANNUAL_INTEREST_RATE: 6.0,
        SESSION_MW_VALUE: 1412.00,
        SESSION_DESIRED_INCOME_TYPE: "MULTIPLIER",
        SESSION_DESIRED_INCOME_FIXED: 10000.0,
        SESSION_INITIAL_EQUITY: 0.0,
        SESSION_PLANNING_START_DATE: datetime.date(2024, 1, 1),
        SESSION_PLANNING_START_DATE_ENABLED: True,
        WIDGET_PLANNING_START_DATE: datetime.date(2024, 1, 1),
        INITIAL_EQUITY_AUTO: True,
    }

    monkeypatch.setattr(st, "session_state", mock_session)

    # Mock st.rerun to be a no-op
    monkeypatch.setattr(st, "rerun", lambda: None)

    # Add transaction in database prior to custom start date to verify computed_initial calculation
    AssetService.add_transaction("BBAS3", "2021-01-01", "BUY", 100, 30.00)

    # Instantiate view and trigger callback
    view = PlanningView()
    view._on_planning_start_date_change()

    # Assertions
    assert st.session_state[SESSION_PLANNING_START_DATE] == datetime.date(2024, 1, 1)
    assert st.session_state[SESSION_INITIAL_EQUITY] == 3000.0


def test_planning_view_first_start_date_enable_initializes_automatic_equity(mock_db, monkeypatch):
    from core.constants import (
        INITIAL_EQUITY_AUTO,
        INITIAL_EQUITY_MANUAL_OVERRIDE,
        SESSION_ANNUAL_INTEREST_RATE,
        SESSION_BIRTH_DATE,
        SESSION_DESIRED_INCOME_FIXED,
        SESSION_DESIRED_INCOME_MW,
        SESSION_DESIRED_INCOME_TYPE,
        SESSION_INITIAL_EQUITY,
        SESSION_MW_VALUE,
        SESSION_PLANNING_START_DATE,
        SESSION_PLANNING_START_DATE_ENABLED,
        SESSION_RETIREMENT_AGE,
        WIDGET_PLANNING_START_DATE_ENABLED,
    )

    monkeypatch.setattr(
        st,
        "session_state",
        {
            SESSION_BIRTH_DATE: datetime.date(1990, 1, 1),
            SESSION_RETIREMENT_AGE: 65,
            SESSION_DESIRED_INCOME_MW: 10.0,
            SESSION_ANNUAL_INTEREST_RATE: 6.0,
            SESSION_MW_VALUE: 1412.00,
            SESSION_DESIRED_INCOME_FIXED: 10000.0,
            SESSION_DESIRED_INCOME_TYPE: "MULTIPLIER",
            SESSION_INITIAL_EQUITY: 0.0,
            INITIAL_EQUITY_AUTO: False,
            INITIAL_EQUITY_MANUAL_OVERRIDE: False,
            SESSION_PLANNING_START_DATE: datetime.date(2024, 1, 1),
            SESSION_PLANNING_START_DATE_ENABLED: False,
            WIDGET_PLANNING_START_DATE_ENABLED: True,
        },
    )
    monkeypatch.setattr(st, "rerun", lambda: None)
    AssetService.add_transaction("BBAS3", "2021-01-01", "BUY", 100, 30.00)

    PlanningView()._on_planning_start_date_enabled_change()

    assert st.session_state[SESSION_INITIAL_EQUITY] == 3000.0
    assert st.session_state[INITIAL_EQUITY_AUTO] is True


def test_planning_view_start_date_change_preserves_explicit_zero_initial_equity(
    mock_db, monkeypatch
):
    from core.constants import (
        INITIAL_EQUITY_AUTO,
        SESSION_BIRTH_DATE,
        SESSION_DESIRED_INCOME_FIXED,
        SESSION_DESIRED_INCOME_MW,
        SESSION_INITIAL_EQUITY,
        SESSION_MW_VALUE,
        SESSION_PLANNING_START_DATE,
        SESSION_PLANNING_START_DATE_ENABLED,
        SESSION_RETIREMENT_AGE,
        SESSION_ANNUAL_INTEREST_RATE,
        SESSION_DESIRED_INCOME_TYPE,
        WIDGET_PLANNING_START_DATE,
    )

    mock_session = {
        SESSION_BIRTH_DATE: datetime.date(1990, 1, 1),
        SESSION_RETIREMENT_AGE: 65,
        SESSION_DESIRED_INCOME_MW: 10.0,
        SESSION_ANNUAL_INTEREST_RATE: 6.0,
        SESSION_MW_VALUE: 1412.00,
        SESSION_DESIRED_INCOME_TYPE: "MULTIPLIER",
        SESSION_DESIRED_INCOME_FIXED: 10000.0,
        SESSION_INITIAL_EQUITY: 0.0,
        INITIAL_EQUITY_AUTO: False,
        SESSION_PLANNING_START_DATE: datetime.date(2024, 1, 1),
        SESSION_PLANNING_START_DATE_ENABLED: True,
        WIDGET_PLANNING_START_DATE: datetime.date(2024, 1, 1),
    }
    monkeypatch.setattr(st, "session_state", mock_session)
    monkeypatch.setattr(st, "rerun", lambda: None)
    AssetService.add_transaction("BBAS3", "2021-01-01", "BUY", 100, 30.00)

    PlanningView()._on_planning_start_date_change()

    assert st.session_state[SESSION_INITIAL_EQUITY] == 0.0
    assert st.session_state[INITIAL_EQUITY_AUTO] is False


def test_planning_view_synchronizes_refreshed_automatic_initial_equity(monkeypatch):
    from core.constants import INITIAL_EQUITY_AUTO, SESSION_INITIAL_EQUITY

    monkeypatch.setattr(
        st,
        "session_state",
        {SESSION_INITIAL_EQUITY: 0.0, INITIAL_EQUITY_AUTO: True},
    )
    saved = []
    view = PlanningView()
    monkeypatch.setattr(view, "_save_params", lambda: saved.append(True))

    view._sync_automatic_initial_equity(2000.0)

    assert st.session_state[SESSION_INITIAL_EQUITY] == 2000.0
    assert saved == [True]


def test_chart_theme_adapter_applies_light_defaults(monkeypatch):
    from plotly.graph_objects import Figure

    from views.components.chart_theme import ChartThemeAdapter

    monkeypatch.setattr(ChartThemeAdapter, "current_theme_type", lambda: "light")

    figure = ChartThemeAdapter.apply_theme(Figure())

    assert figure.layout.paper_bgcolor == ChartThemeAdapter.TRANSPARENT
    assert figure.layout.plot_bgcolor == ChartThemeAdapter.TRANSPARENT
    assert figure.layout.font.color == ChartThemeAdapter.LIGHT_FONT_COLOR
    assert figure.layout.hovermode == "x unified"
    assert figure.layout.legend.orientation == "h"
    assert figure.layout.legend.y == -0.22
    assert figure.layout.margin.b == 90
    assert figure.layout.xaxis.gridcolor == ChartThemeAdapter.LIGHT_GRID_COLOR
    assert figure.layout.yaxis.gridcolor == ChartThemeAdapter.LIGHT_GRID_COLOR
    assert (
        ChartThemeAdapter.annotation_background() == ChartThemeAdapter.LIGHT_ANNOTATION_BACKGROUND
    )
    assert ChartThemeAdapter.annotation_font_color() == ChartThemeAdapter.LIGHT_FONT_COLOR


def test_chart_theme_adapter_applies_dark_defaults(monkeypatch):
    from plotly.graph_objects import Figure

    from views.components.chart_theme import ChartThemeAdapter

    monkeypatch.setattr(ChartThemeAdapter, "current_theme_type", lambda: "dark")

    figure = ChartThemeAdapter.apply_theme(Figure())

    assert figure.layout.template.layout.paper_bgcolor == "rgb(17,17,17)"
    assert figure.layout.font.color == ChartThemeAdapter.DARK_FONT_COLOR
    assert figure.layout.xaxis.gridcolor == ChartThemeAdapter.DARK_GRID_COLOR
    assert ChartThemeAdapter.annotation_background() == ChartThemeAdapter.DARK_ANNOTATION_BACKGROUND
    assert ChartThemeAdapter.annotation_font_color() == ChartThemeAdapter.DARK_FONT_COLOR


def test_sector_chart_hover_customdata(monkeypatch):
    """
    Ensures that DashboardCharts._render_top_charts prepares custom hover data
    containing ticker codes, values, and percentages for the Sector Allocation pie chart.
    """
    # Define columns needed for _render_top_charts
    df_mock = pd.DataFrame(
        [
            {
                "ticker": "BBAS3",
                "sector": "Financeiro",
                "current_value": 1000.00,
                "invested_amount": 800.00,
                "total_dividends": 50.00,
                "total_yoc": 6.25,
            },
            {
                "ticker": "SANB11",
                "sector": "Financeiro",
                "current_value": 2000.00,
                "invested_amount": 1600.00,
                "total_dividends": 100.00,
                "total_yoc": 6.25,
            },
            {
                "ticker": "CXSE3",
                "sector": "Seguridade",
                "current_value": 3000.00,
                "invested_amount": 2500.00,
                "total_dividends": 150.00,
                "total_yoc": 6.00,
            },
        ]
    )

    captured_charts = []

    def mock_plotly_chart(fig, width=None):
        captured_charts.append(fig)

    class MockColumns:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    def mock_columns(spec):
        return [MockColumns(), MockColumns(), MockColumns()]

    monkeypatch.setattr("streamlit.columns", mock_columns)
    monkeypatch.setattr("streamlit.plotly_chart", mock_plotly_chart)

    charts = DashboardCharts()
    sectors = pd.DataFrame([
        {"sector": "Financeiro", "current_value": 3000, "Detalhes": "BBAS3: R$ 1.000,00 (33.33% / 16.67%)<br>SANB11: R$ 2.000,00 (66.67% / 33.33%)"},
        {"sector": "Seguridade", "current_value": 3000, "Detalhes": "CXSE3: R$ 3.000,00 (100.00% / 50.00%)"},
    ])
    charts._render_top_charts(SimpleNamespace(positions=df_mock, sectors=sectors))

    assert len(captured_charts) >= 1
    fig_sectors = captured_charts[0]

    # Verify that custom_data is passed
    assert fig_sectors.data[0].customdata is not None

    customdata_list = fig_sectors.data[0].customdata

    # Find custom hover details for "Financeiro" and "Seguridade"
    # Sector totals: Financeiro = 3000, Seguridade = 3000. Total = 6000.
    # Financeiro should list BBAS3 (1000.00, 16.67% total, 33.33% sector) and SANB11 (2000.00, 33.33% total, 66.67% sector)
    # Seguridade should list CXSE3 (3000.00, 50.00% total, 100.00% sector)

    # Let's check that customdata has the formatted content
    # Note that Plotly names could be mapped to indices, let's verify both hover templates exist
    found_financeiro = False
    found_seguridade = False

    for details in customdata_list:
        detail_str = details[0]
        if "BBAS3" in detail_str and "SANB11" in detail_str:
            found_financeiro = True
            assert "R$\xa01.000,00" in detail_str or "R$ 1.000,00" in detail_str
            assert "16.67%" in detail_str
            assert "33.33%" in detail_str
            assert "R$\xa02.000,00" in detail_str or "R$ 2.000,00" in detail_str
            assert "33.33%" in detail_str
            assert "66.67%" in detail_str
        elif "CXSE3" in detail_str:
            found_seguridade = True
            assert "R$\xa03.000,00" in detail_str or "R$ 3.000,00" in detail_str
            assert "50.00%" in detail_str
            assert "100.00%" in detail_str

    assert found_financeiro, "Hover data for Financeiro not found or incorrect"
    assert found_seguridade, "Hover data for Seguridade not found or incorrect"








@pytest.mark.parametrize("initial_equity", [0.0, 100_000.0])
def test_quick_simulation_charts_start_with_entered_equity(monkeypatch, initial_equity):
    from contextlib import nullcontext
    from views import planning_view
    from views.components.chart_theme import ChartThemeAdapter

    inputs = {
        "sandbox_tempo_anos": 30,
        "sandbox_salario_desejado": 10_000.0,
        "sandbox_taxa_juros": 6.0,
        "sandbox_patrimonio_inicial": initial_equity,
    }
    figures = []
    saved_configuration = SimulationService.get_configuration()
    monkeypatch.setattr(planning_view.st, "expander", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(planning_view.st, "columns", lambda count: [nullcontext() for _ in range(count)])
    monkeypatch.setattr(planning_view.st, "number_input", lambda *args, **kwargs: inputs[kwargs["key"]])
    for method in ("write", "markdown", "subheader"):
        monkeypatch.setattr(planning_view.st, method, lambda *args, **kwargs: None)
    monkeypatch.setattr(planning_view.st, "plotly_chart", lambda fig, **kwargs: figures.append(fig))
    monkeypatch.setattr(planning_view.SimulationResultsWidget, "render", lambda *args, **kwargs: None)
    monkeypatch.setattr(ChartThemeAdapter, "current_theme_type", lambda: "light")

    PlanningView()._render_sandbox_simulation()

    assert len(figures) == 2
    cumulative, cashflow = figures
    assert cumulative.data[0].x[0] == 0.0
    assert cumulative.data[0].y[0] == initial_equity
    assert cumulative.data[1].y[0] == initial_equity
    assert cumulative.data[2].y[0] == 0.0
    crossover = [item for item in cumulative.layout.annotations if "Juros >= Aportes" in item.text]
    assert crossover and crossover[0].x > 0.0
    monthly_rate = 1.06 ** (1 / 12) - 1
    target = 10_000.0 / monthly_rate
    assert cumulative.data[0].x[-1] == 30.0
    assert cumulative.data[0].y[-1] == pytest.approx(target)
    assert cashflow.data[1].y[0] == pytest.approx(initial_equity * monthly_rate)
    assert SimulationService.get_configuration() == saved_configuration
