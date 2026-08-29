import contextlib
import datetime
import pandas as pd
import pytest
import sqlite3

from core.daos.planning_dao import PlanningDAO
from core.database import DatabaseManager
from services.goals_service import GoalService
from services.share_quantity_goal_service import ShareQuantityGoalService
from services.planning_service import SimulationService
from views.components.accumulation_goals import AccumulationGoalProgressWidget
from views.components.goal_progress import GoalProgressBar


class StubPortfolioProvider:
    def __init__(
        self, positions, ytd_contributions=0.0, year_start_quantities=None, transactions=None
    ):
        self.positions = positions
        self.ytd_contributions = ytd_contributions
        self.quantity_queries = []
        self.transactions = transactions or {}
        self.year_start_quantities = year_start_quantities or {
            position["ticker"]: position["quantity"] for position in positions
        }

    def calculate_positions(self, today_date=None, start_date=None):
        return pd.DataFrame(self.positions)

    def get_ytd_contributions(self, current_year):
        return self.ytd_contributions

    def get_quantity_on_date(self, ticker, date_str, conn=None):
        self.quantity_queries.append((ticker, date_str))
        return self.year_start_quantities.get(ticker, 0)

    def get_raw_transactions_for_chart(self, ticker):
        return pd.DataFrame(
            self.transactions.get(
                ticker,
                [],
            ),
            columns=["date", "transaction_type", "quantity", "unit_price", "fees"],
        )


class StubMarketData:
    @staticmethod
    def get_ticker_market_analysis(ticker, target_yield_pct=6.0):
        return {"avg_dividend_5y": 2.0}


class StubPlanningProvider:
    @staticmethod
    def get_current_simulation():
        return {"target_monthly_income": 1000.0}

    @staticmethod
    def get_planned_annual_dividends():
        return 12_000.0

    @staticmethod
    def get_updated_required_contribution():
        return 1_000.0


class AnnualExamplePlanningProvider:
    @staticmethod
    def get_current_simulation():
        return {"target_monthly_income": 1000.0}

    @staticmethod
    def get_planned_annual_dividends():
        return 4_816.63


class GrowthExamplePlanningProvider:
    @staticmethod
    def get_planned_annual_dividends():
        return 300.0


class EmptyMarketData:
    @staticmethod
    def get_ticker_market_analysis(ticker, target_yield_pct=6.0):
        return {}


class PartialHistoryMarketData:
    @staticmethod
    def get_ticker_market_analysis(ticker, target_yield_pct=6.0):
        return {
            "avg_dividend_5y": 3.0,
            "dividend_average_years": 2,
            "dividend_history_status": "partial",
        }


class BbasMarketData:
    @staticmethod
    def get_ticker_market_analysis(ticker, target_yield_pct=6.0):
        return {"avg_dividend_5y": 1.86}


class PortfolioMarketData:
    @staticmethod
    def get_ticker_market_analysis(ticker, target_yield_pct=6.0):
        averages = {"BBAS3": 1.86, "TAEE11": 3.81}
        return {"avg_dividend_5y": averages.get(ticker, 2.0)}


class EmptyPlanningProvider:
    @staticmethod
    def get_current_simulation():
        return None

    @staticmethod
    def get_planned_annual_dividends():
        return 0.0


def build_service(positions):
    return ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=StubPortfolioProvider(positions),
        market_data_api=StubMarketData,
        planning_provider=StubPlanningProvider(),
    )


def test_dividend_income_target_uses_annual_income_weight_and_five_year_average():
    target = ShareQuantityGoalService.calculate_dividend_income_target(
        planned_annual_dividends=12_000,
        allocation_weight=50,
        average_dividend_5y=2.0,
    )

    assert target == 3_000
    assert (
        ShareQuantityGoalService.calculate_dividend_income_target(
            planned_annual_dividends=4_816.63,
            allocation_weight=100 / 7,
            average_dividend_5y=3.81,
        )
        == 181
    )


def test_percentage_target_rounds_up_to_a_whole_share():
    assert ShareQuantityGoalService.calculate_percentage_target(101, 10) == 112


@pytest.mark.parametrize(
    ("current_quantity", "expected_progress"),
    [(80, 0.0), (100, 0.0), (125, 25.0), (200, 100.0), (250, 150.0)],
)
def test_incremental_progress_is_clamped_at_zero_but_can_exceed_one_hundred(
    current_quantity, expected_progress
):
    progress = ShareQuantityGoalService.calculate_progress(100, current_quantity, 200)

    assert progress == expected_progress


def test_share_goal_uses_january_first_baseline_for_progress_and_growth_marker(mock_db):
    repository = PlanningDAO()
    portfolio = StubPortfolioProvider(
        [{"ticker": "BBAS3", "quantity": 125}],
        year_start_quantities={"BBAS3": 100},
    )
    service = ShareQuantityGoalService(
        goal_repo=repository,
        settings_repo=repository,
        portfolio_provider=portfolio,
        market_data_api=StubMarketData,
        planning_provider=GrowthExamplePlanningProvider(),
    )

    reference_date = datetime.date(2026, 8, 28)
    service.save_portfolio_goal_plan({"BBAS3": 100}, today_date=reference_date)
    stored_goal = repository.list_accumulation_goals()[0]
    portfolio.quantity_queries.clear()
    progress = service.list_goals_with_progress(reference_date)[0]
    plan_row = service.get_portfolio_goal_plan(today_date=reference_date)["rows"].iloc[0]

    assert stored_goal["start_quantity"] == 100
    assert progress["start_quantity"] == 100
    assert progress["progress_percentage"] == 50
    assert plan_row[ShareQuantityGoalService.PLAN_GROWTH_PERCENTAGE] == 50
    assert portfolio.quantity_queries == [
        ("BBAS3", "2026-01-01"),
        ("BBAS3", "2026-01-01"),
    ]


def test_dashboard_refreshes_a_previously_stored_baseline_for_the_current_year(mock_db):
    repository = PlanningDAO()
    repository.upsert_accumulation_goal(
        ticker="BBAS3",
        start_quantity=125,
        target_quantity=150,
        target_mode=ShareQuantityGoalService.MODE_QUANTITY,
        target_percentage=None,
        allocation_weight=100,
        average_dividend_5y=2.0,
    )
    service = ShareQuantityGoalService(
        goal_repo=repository,
        settings_repo=repository,
        portfolio_provider=StubPortfolioProvider(
            [{"ticker": "BBAS3", "quantity": 125}],
            year_start_quantities={"BBAS3": 100},
        ),
        market_data_api=StubMarketData,
        planning_provider=GrowthExamplePlanningProvider(),
    )

    progress = service.list_goals_with_progress(datetime.date(2026, 8, 28))[0]

    assert progress["start_quantity"] == 100
    assert progress["progress_percentage"] == 50


def test_dashboard_progress_bar_uses_green_overlay_for_excess(monkeypatch):
    rendered = {}

    def capture_markup(markup, unsafe_allow_html=False):
        rendered["markup"] = markup
        rendered["unsafe_allow_html"] = unsafe_allow_html

    monkeypatch.setattr("views.components.goal_progress.st.markdown", capture_markup)

    GoalProgressBar.render(150, "BBAS3: 150% & acima")

    assert "width:100.00%" in rendered["markup"]
    assert "width:50.00%" in rendered["markup"]
    assert "background:#2ca02c" in rendered["markup"]
    assert 'title="BBAS3: 150% &amp; acima"' in rendered["markup"]
    assert rendered["unsafe_allow_html"] is True


def test_portfolio_progress_is_weighted_by_active_asset_allocation():
    goals = [
        {"allocation_weight": 20, "progress_percentage": 50},
        {"allocation_weight": 80, "progress_percentage": 100},
        {"allocation_weight": 0, "progress_percentage": 500},
    ]

    progress = ShareQuantityGoalService.calculate_weighted_progress(goals)

    assert progress == 90


def test_corporate_actions_do_not_count_as_accumulation_progress(mock_db):
    repository = PlanningDAO()
    repository.upsert_accumulation_goal(
        ticker="BBAS3",
        start_quantity=100,
        target_quantity=150,
        target_mode=ShareQuantityGoalService.MODE_QUANTITY,
        target_percentage=None,
        allocation_weight=100,
        average_dividend_5y=2.0,
    )
    portfolio = StubPortfolioProvider(
        [{"ticker": "BBAS3", "quantity": 200}],
        year_start_quantities={"BBAS3": 100},
        transactions={
            "BBAS3": [
                {
                    "date": "2026-01-02",
                    "transaction_type": "BUY",
                    "quantity": 100,
                    "unit_price": 0.0,
                    "fees": 0.0,
                },
            ]
        },
    )
    service = ShareQuantityGoalService(
        goal_repo=repository,
        portfolio_provider=portfolio,
        market_data_api=StubMarketData,
        planning_provider=GrowthExamplePlanningProvider(),
    )

    progress = service.list_goals_with_progress(datetime.date(2026, 8, 28))[0]

    assert progress["current_quantity"] == 200
    assert progress["progress_percentage"] == 0


def test_paid_acquisitions_are_added_to_the_annual_baseline_for_progress(mock_db):
    repository = PlanningDAO()
    repository.upsert_accumulation_goal(
        ticker="BBAS3",
        start_quantity=100,
        target_quantity=150,
        target_mode=ShareQuantityGoalService.MODE_QUANTITY,
        target_percentage=None,
        allocation_weight=100,
        average_dividend_5y=2.0,
    )
    portfolio = StubPortfolioProvider(
        [{"ticker": "BBAS3", "quantity": 125}],
        year_start_quantities={"BBAS3": 100},
        transactions={
            "BBAS3": [
                {
                    "date": "2026-01-02",
                    "transaction_type": "BUY",
                    "quantity": 25,
                    "unit_price": 10.0,
                    "fees": 0.0,
                },
            ]
        },
    )
    service = ShareQuantityGoalService(
        goal_repo=repository,
        portfolio_provider=portfolio,
        market_data_api=StubMarketData,
        planning_provider=GrowthExamplePlanningProvider(),
    )

    progress = service.list_goals_with_progress(datetime.date(2026, 8, 28))[0]

    assert progress["progress_percentage"] == 50


def test_unavailable_dividend_plan_is_not_activated_on_save(mock_db):
    repository = PlanningDAO()
    service = ShareQuantityGoalService(
        goal_repo=repository,
        portfolio_provider=StubPortfolioProvider([{"ticker": "BBAS3", "quantity": 100}]),
        market_data_api=StubMarketData,
        planning_provider=EmptyPlanningProvider(),
    )

    goals = service.save_portfolio_goal_plan({"BBAS3": 100})

    stored_goal = repository.list_accumulation_goals()[0]
    assert goals == []
    assert stored_goal["is_active"] == 0


def test_dashboard_renders_one_weighted_bar_with_asset_details(monkeypatch):
    goals = [
        {
            "ticker": "BBAS3",
            "start_quantity": 100,
            "current_quantity": 125,
            "target_quantity": 150,
            "allocation_weight": 20,
            "progress_percentage": 50,
        },
        {
            "ticker": "TAEE11",
            "start_quantity": 50,
            "current_quantity": 75,
            "target_quantity": 75,
            "allocation_weight": 80,
            "progress_percentage": 100,
        },
    ]
    rendered_bars = []

    monkeypatch.setattr(ShareQuantityGoalService, "get_goal_enabled", lambda: True)
    monkeypatch.setattr(ShareQuantityGoalService, "list_goals_with_progress", lambda: goals)
    monkeypatch.setattr(
        "views.components.accumulation_goals.GoalProgressBar.render",
        lambda progress, tooltip=None: rendered_bars.append((progress, tooltip)),
    )
    monkeypatch.setattr("views.components.accumulation_goals.st.subheader", lambda *_: None)
    monkeypatch.setattr("views.components.accumulation_goals.st.write", lambda *_: None)
    monkeypatch.setattr("views.components.accumulation_goals.st.caption", lambda *_: None)
    monkeypatch.setattr(
        "views.components.accumulation_goals.st.expander",
        lambda *_: contextlib.nullcontext(),
    )

    AccumulationGoalProgressWidget().render()

    assert len(rendered_bars) == 1
    assert rendered_bars[0][0] == 90
    assert (
        "BBAS3 — 01/01: 100 | atual: 125 | meta: 150 cotas | 50,0% concluído" in rendered_bars[0][1]
    )
    assert (
        "TAEE11 — 01/01: 50 | atual: 75 | meta: 75 cotas | 100,0% concluído" in rendered_bars[0][1]
    )


def test_dashboard_hides_goal_progress_when_portfolio_setting_is_disabled(monkeypatch):
    monkeypatch.setattr(ShareQuantityGoalService, "get_goal_enabled", lambda: False)

    def fail_if_goals_are_loaded():
        raise AssertionError("disabled goals must not be loaded for the Dashboard")

    monkeypatch.setattr(
        ShareQuantityGoalService, "list_goals_with_progress", fail_if_goals_are_loaded
    )

    AccumulationGoalProgressWidget().render()


def test_annual_investment_and_reinvestment_goal_is_owned_by_goal_service(mock_db):
    service = GoalService(
        settings_repo=PlanningDAO(),
        portfolio_provider=StubPortfolioProvider([], ytd_contributions=15_000),
        planning_provider=StubPlanningProvider(),
    )

    goal = service.get_annual_investment_goal(2026, ytd_dividends=1_000)

    assert goal["annual_salary_goal"] == 12_000
    assert goal["reinvestment_goal"] == 1_000
    assert goal["total_goal"] == 13_000
    assert goal["progress_percentage"] == pytest.approx(115.38, abs=0.01)
    assert goal["remaining_to_invest"] == 0

    service.set_reinvestment_goal_enabled(False)
    contribution_only_goal = service.get_annual_investment_goal(2026, ytd_dividends=1_000)

    assert contribution_only_goal["reinvestment_enabled"] is False
    assert contribution_only_goal["reinvestment_goal"] == 0
    assert contribution_only_goal["total_goal"] == 12_000


def test_dividend_income_goal_freezes_baseline_and_uses_equal_initial_allocation(mock_db):
    portfolio = StubPortfolioProvider(
        [
            {"ticker": "BBAS3", "quantity": 100},
            {"ticker": "TAEE11", "quantity": 50},
        ]
    )
    service = ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=portfolio,
        market_data_api=StubMarketData,
        planning_provider=StubPlanningProvider(),
    )

    created = service.create_goal("bbas3", ShareQuantityGoalService.MODE_DIVIDEND_INCOME)

    assert created["ticker"] == "BBAS3"
    assert created["start_quantity"] == 100
    assert created["target_quantity"] == 3_000
    assert created["allocation_weight"] == 50.0
    assert created["average_dividend_5y"] == 2.0

    portfolio.positions[0]["quantity"] = 1_550
    updated = service.list_goals_with_progress()[0]

    assert updated["start_quantity"] == 100
    assert updated["current_quantity"] == 1_550
    assert updated["progress_percentage"] == 50.0

    portfolio.positions = []
    sold_position = service.list_goals_with_progress()[0]

    assert sold_position["current_quantity"] == 0
    assert sold_position["progress_percentage"] == 0.0


def test_suggested_goal_uses_planned_dividends_for_the_year_instead_of_retirement_income(
    mock_db,
):
    positions = [
        {"ticker": ticker, "quantity": 100}
        for ticker in ["BBAS3", "TAEE11", "PETR4", "VALE3", "ITSA4", "CXSE3", "BBSE3"]
    ]
    service = ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=StubPortfolioProvider(positions),
        market_data_api=BbasMarketData,
        planning_provider=AnnualExamplePlanningProvider(),
    )

    suggestion = service.get_goal_suggestion("BBAS3")

    assert suggestion["planned_annual_dividends"] == pytest.approx(4_816.63)
    assert suggestion["allocation_weight"] == pytest.approx(100 / 7)
    assert suggestion["allocated_annual_dividends"] == pytest.approx(688.09, abs=0.01)
    assert suggestion["suggested_target_quantity"] == 370


def test_user_weight_recalculates_and_is_persisted_with_the_goal(mock_db):
    service = ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=StubPortfolioProvider([{"ticker": "BBAS3", "quantity": 100}]),
        market_data_api=BbasMarketData,
        planning_provider=AnnualExamplePlanningProvider(),
    )

    suggestion = service.get_goal_suggestion("BBAS3", allocation_weight=20)
    goal = service.create_goal(
        "BBAS3",
        ShareQuantityGoalService.MODE_DIVIDEND_INCOME,
        allocation_weight=20,
    )

    assert suggestion["allocated_annual_dividends"] == pytest.approx(963.326)
    assert suggestion["suggested_target_quantity"] == 518
    assert goal["allocation_weight"] == 20
    assert goal["target_quantity"] == 518


def test_existing_dividend_goal_is_recalculated_with_the_current_annual_plan(mock_db):
    repository = PlanningDAO()
    repository.upsert_accumulation_goal(
        ticker="BBAS3",
        start_quantity=100,
        target_quantity=1_000,
        target_mode=ShareQuantityGoalService.MODE_DIVIDEND_INCOME,
        target_percentage=None,
        allocation_weight=100 / 7,
        average_dividend_5y=1.86,
    )
    positions = [
        {"ticker": ticker, "quantity": 100}
        for ticker in ["BBAS3", "TAEE11", "PETR4", "VALE3", "ITSA4", "CXSE3", "BBSE3"]
    ]
    service = ShareQuantityGoalService(
        goal_repo=repository,
        portfolio_provider=StubPortfolioProvider(positions),
        market_data_api=BbasMarketData,
        planning_provider=AnnualExamplePlanningProvider(),
    )

    goal = service.list_goals_with_progress()[0]

    assert goal["target_quantity"] == 370


def test_planned_annual_dividends_are_extracted_from_the_cumulative_projection():
    projection = pd.DataFrame(
        {
            "month_str": ["2025-12", "2026-01", "2026-12", "2027-01"],
            "planned_dividends": [1_000.0, 1_300.0, 5_816.63, 6_200.0],
        }
    )

    annual_dividends = SimulationService.calculate_planned_dividends_for_year(projection, 2026)

    assert annual_dividends == pytest.approx(4_816.63)


def test_portfolio_plan_lists_every_asset_in_one_equal_weight_table(mock_db):
    tickers = ["BBAS3", "TAEE11", "PETR4", "VALE3", "ITSA4", "CXSE3", "BBSE3"]
    service = ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=StubPortfolioProvider(
            [{"ticker": ticker, "quantity": 100} for ticker in tickers]
        ),
        market_data_api=PortfolioMarketData,
        planning_provider=AnnualExamplePlanningProvider(),
    )

    plan = service.get_portfolio_goal_plan()
    rows = plan["rows"].set_index("ticker")

    assert len(rows) == 7
    assert plan["planned_annual_dividends"] == pytest.approx(4_816.63)
    assert rows.loc["BBAS3", "allocation_weight"] == pytest.approx(100 / 7)
    assert rows.loc["BBAS3", "allocated_annual_dividends"] == pytest.approx(688.09)
    assert rows.loc["BBAS3", "target_quantity"] == 370
    assert rows.loc["TAEE11", "target_quantity"] == 181


def test_partial_dividend_history_is_used_and_explained_in_the_plan(mock_db):
    service = ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=StubPortfolioProvider([{"ticker": "NEW3", "quantity": 100}]),
        market_data_api=PartialHistoryMarketData,
        planning_provider=AnnualExamplePlanningProvider(),
    )

    row = service.get_portfolio_goal_plan()["rows"].iloc[0]

    assert row[ShareQuantityGoalService.PLAN_AVERAGE_DIVIDEND] == 3.0
    assert row[ShareQuantityGoalService.PLAN_TARGET_QUANTITY] == 1_606
    assert "média calculada com 2 ano(s)" in row[ShareQuantityGoalService.PLAN_HISTORY_NOTE]
    assert "anos sem pagamento contam como zero" in row[ShareQuantityGoalService.PLAN_HISTORY_NOTE]


def test_missing_dividend_history_does_not_block_saving_other_goals(mock_db):
    service = ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=StubPortfolioProvider([{"ticker": "NEW3", "quantity": 100}]),
        market_data_api=EmptyMarketData,
        planning_provider=AnnualExamplePlanningProvider(),
    )

    plan = service.get_portfolio_goal_plan()
    saved_goals = service.save_portfolio_goal_plan({"NEW3": 100})
    stored_goal = PlanningDAO().list_accumulation_goals()[0]

    assert pd.isna(plan["rows"].iloc[0][ShareQuantityGoalService.PLAN_TARGET_QUANTITY])
    assert (
        "Sem histórico de proventos"
        in plan["rows"].iloc[0][ShareQuantityGoalService.PLAN_HISTORY_NOTE]
    )
    assert stored_goal["average_dividend_5y"] == 0
    assert saved_goals == []


def test_custom_portfolio_weights_recalculate_rows_and_must_total_one_hundred(mock_db):
    tickers = ["BBAS3", "TAEE11", "PETR4", "VALE3", "ITSA4", "CXSE3", "BBSE3"]
    positions = [{"ticker": ticker, "quantity": 100} for ticker in tickers]
    service = ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=StubPortfolioProvider(positions),
        market_data_api=PortfolioMarketData,
        planning_provider=AnnualExamplePlanningProvider(),
    )
    weights = {ticker: 80 / 6 for ticker in tickers}
    weights["BBAS3"] = 20

    plan = service.get_portfolio_goal_plan(weights)
    rows = plan["rows"].set_index("ticker")
    goals = service.save_portfolio_goal_plan(weights)

    assert rows.loc["BBAS3", "allocated_annual_dividends"] == pytest.approx(963.326)
    assert rows.loc["BBAS3", "target_quantity"] == 518
    assert len(goals) == 7
    assert sum(goal["allocation_weight"] for goal in goals) == pytest.approx(100)

    invalid_weights = dict(weights)
    invalid_weights["BBAS3"] = 25
    with pytest.raises(ValueError, match="soma dos pesos"):
        service.save_portfolio_goal_plan(invalid_weights)


def test_zero_weight_deactivates_asset_and_removes_it_from_dashboard_progress(mock_db):
    tickers = ["BBAS3", "TAEE11", "PETR4", "VALE3", "ITSA4", "CXSE3", "BBSE3"]
    positions = [{"ticker": ticker, "quantity": 100} for ticker in tickers]
    service = ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=StubPortfolioProvider(positions),
        market_data_api=PortfolioMarketData,
        planning_provider=AnnualExamplePlanningProvider(),
    )
    weights = {ticker: 100 / 6 for ticker in tickers if ticker != "BBAS3"}
    weights["BBAS3"] = 0

    plan = service.get_portfolio_goal_plan(weights)
    goals = service.save_portfolio_goal_plan(weights)
    stored_bbas = next(
        goal for goal in PlanningDAO().list_accumulation_goals() if goal["ticker"] == "BBAS3"
    )
    bbas_row = plan["rows"].set_index("ticker").loc["BBAS3"]

    assert bool(bbas_row["is_active"]) is False
    assert bbas_row["allocated_annual_dividends"] == 0
    assert bbas_row["target_quantity"] == bbas_row["current_quantity"]
    assert stored_bbas["allocation_weight"] == 0
    assert stored_bbas["is_active"] == 0
    assert "BBAS3" not in {goal["ticker"] for goal in goals}


def test_all_accumulation_goals_can_be_inactive(mock_db):
    service = ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=StubPortfolioProvider([{"ticker": "BBAS3", "quantity": 100}]),
        market_data_api=BbasMarketData,
        planning_provider=AnnualExamplePlanningProvider(),
    )

    goals = service.save_portfolio_goal_plan({"BBAS3": 0})

    assert goals == []
    assert PlanningDAO().list_accumulation_goals()[0]["is_active"] == 0


def test_legacy_accumulation_table_migrates_active_state_and_zero_weight_support(tmp_path):
    database_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(database_path)
    connection.execute("""
        CREATE TABLE asset_accumulation_goals (
            ticker TEXT PRIMARY KEY,
            start_quantity REAL NOT NULL CHECK (start_quantity >= 0),
            target_quantity REAL NOT NULL CHECK (target_quantity > start_quantity),
            target_mode TEXT NOT NULL,
            target_percentage REAL,
            allocation_weight REAL NOT NULL CHECK (
                allocation_weight > 0 AND allocation_weight <= 100
            ),
            average_dividend_5y REAL NOT NULL CHECK (average_dividend_5y >= 0),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    connection.execute(
        """
        INSERT INTO asset_accumulation_goals (
            ticker, start_quantity, target_quantity, target_mode,
            allocation_weight, average_dividend_5y
        ) VALUES ('BBAS3', 100, 370, 'DIVIDEND_INCOME', 100, 1.86)
        """
    )
    connection.commit()

    PlanningDAO(DatabaseManager(str(database_path))).initialize_tables(connection)
    connection.commit()
    columns = {row[1] for row in connection.execute("PRAGMA table_info(asset_accumulation_goals)")}
    migrated_goal = connection.execute(
        "SELECT ticker, allocation_weight, is_active FROM asset_accumulation_goals"
    ).fetchone()
    goal_settings = connection.execute(
        """
        SELECT reinvest_dividends_enabled, share_quantity_enabled
        FROM goal_settings WHERE id = 1
        """
    ).fetchone()
    connection.execute(
        "UPDATE asset_accumulation_goals SET allocation_weight = 0 WHERE ticker = 'BBAS3'"
    )
    connection.close()

    assert "is_active" in columns
    assert migrated_goal == ("BBAS3", 100.0, 1)
    assert goal_settings == (1, 1)


def test_accumulation_goals_are_opt_in_and_setting_is_persisted(mock_db):
    assert ShareQuantityGoalService.get_goal_enabled() is False

    ShareQuantityGoalService.set_goal_enabled(True)

    assert ShareQuantityGoalService.get_goal_enabled() is True
    assert PlanningDAO().get_goal_settings()["share_quantity"] is True


def test_legacy_goal_visibility_setting_is_migrated(tmp_path):
    database_path = tmp_path / "legacy-settings.db"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE accumulation_goal_settings (
            id INTEGER PRIMARY KEY,
            enabled INTEGER NOT NULL
        )
        """
    )
    connection.execute("INSERT INTO accumulation_goal_settings (id, enabled) VALUES (1, 0)")

    PlanningDAO(DatabaseManager(str(database_path))).initialize_tables(connection)
    connection.commit()
    settings = connection.execute(
        """
        SELECT reinvest_dividends_enabled, share_quantity_enabled
        FROM goal_settings WHERE id = 1
        """
    ).fetchone()
    connection.close()

    assert settings == (1, 0)


def test_user_can_create_percentage_or_explicit_quantity_goals(mock_db):
    service = build_service([{"ticker": "BBAS3", "quantity": 100}])

    percentage_goal = service.create_goal("BBAS3", ShareQuantityGoalService.MODE_PERCENTAGE, 10)
    assert percentage_goal["target_quantity"] == 110
    assert percentage_goal["target_percentage"] == 10

    quantity_goal = service.create_goal("BBAS3", ShareQuantityGoalService.MODE_QUANTITY, 175)
    assert quantity_goal["start_quantity"] == 100
    assert quantity_goal["target_quantity"] == 175
    assert quantity_goal["target_percentage"] is None


def test_custom_goal_does_not_require_dividend_history_or_retirement_configuration(mock_db):
    service = ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=StubPortfolioProvider([{"ticker": "BBAS3", "quantity": 100}]),
        market_data_api=EmptyMarketData,
        planning_provider=EmptyPlanningProvider(),
    )

    goal = service.create_goal("BBAS3", ShareQuantityGoalService.MODE_QUANTITY, 150)

    assert goal["target_quantity"] == 150
    assert goal["average_dividend_5y"] == 0


def test_dividend_income_goal_without_history_is_saved_as_unavailable_instead_of_raising(
    mock_db,
):
    service = ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=StubPortfolioProvider([{"ticker": "NEW3", "quantity": 100}]),
        market_data_api=EmptyMarketData,
        planning_provider=AnnualExamplePlanningProvider(),
    )

    goal = service.create_goal("NEW3", ShareQuantityGoalService.MODE_DIVIDEND_INCOME)

    assert goal["target_available"] is False
    assert "Sem histórico de proventos" in goal[ShareQuantityGoalService.PLAN_HISTORY_NOTE]
    assert service.list_goals_with_progress() == []


def test_target_must_be_greater_than_frozen_baseline(mock_db):
    service = build_service([{"ticker": "BBAS3", "quantity": 100}])

    with pytest.raises(ValueError, match="maior que a quantidade atual"):
        service.create_goal("BBAS3", ShareQuantityGoalService.MODE_QUANTITY, 100)


def test_accumulation_goal_can_be_deleted(mock_db):
    service = build_service([{"ticker": "BBAS3", "quantity": 100}])
    service.create_goal("BBAS3", ShareQuantityGoalService.MODE_QUANTITY, 150)

    assert service.delete_goal("bbas3") is True
    assert service.list_goals_with_progress() == []
