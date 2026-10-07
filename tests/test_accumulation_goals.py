from services.portfolio_read_service import PortfolioReadService
import contextlib
import datetime
import sqlite3

import pandas as pd
import pytest

from core.daos.planning_dao import PlanningDAO
from core.database import DatabaseManager
from core.portfolio_read import PortfolioPlanning
from services.goals_service import GoalService
from services.planning_service import SimulationService
from services.share_quantity_goal_service import ShareQuantityGoalService
from views.components.accumulation_goals import (
    AccumulationGoalPlanningWidget,
    AccumulationGoalProgressWidget,
)
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

    def read_planning(self, *, start_date=None, year=None, quantity_date=None):
        positions = pd.DataFrame(self.positions)
        if quantity_date:
            self.quantity_queries.extend((ticker, quantity_date) for ticker in self.year_start_quantities)
        transactions = {ticker: self._transactions_for_ticker(ticker) for ticker in self.transactions}
        return PortfolioPlanning(positions, 0.0, 0.0, self.ytd_contributions, self.year_start_quantities, transactions)

    def _transactions_for_ticker(self, ticker):
        records = [
            {**transaction, "event_kind": transaction.get("event_kind", "CORPORATE")}
            for transaction in self.transactions.get(ticker, [])
        ]
        return pd.DataFrame(
            records,
            columns=[
                "date",
                "transaction_type",
                "quantity",
                "unit_price",
                "fees",
                "cost_status",
                "event_kind",
            ],
        )


class StubMarketData:
    @staticmethod
    def get_ticker_market_analysis(ticker, target_yield_pct=6.0):
        return {"avg_dividend_5y": 2.0}


class StubPlanningProvider:
    @staticmethod
    def get_current_simulation():
        return {"target_monthly_income": 1000.0, "updated_monthly_contribution": 1000.0}

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
        return {
            "avg_dividend_5y": 0.0,
            "dividend_average_years": 0,
            "dividend_history_status": "unavailable",
        }


class FailedMarketData:
    @staticmethod
    def get_ticker_market_analysis(ticker, target_yield_pct=6.0):
        return {}


class PartialFailedMarketData:
    @staticmethod
    def get_ticker_market_analysis(ticker, target_yield_pct=6.0):
        return {"avg_dividend_5y": 2.0} if ticker == "BBAS3" else {}


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
        market_analysis_api=StubMarketData,
        planning_provider=StubPlanningProvider(),
    )


def set_goal_created_at(repository, created_at):
    conn = repository.get_personal_connection()
    conn.execute("UPDATE asset_accumulation_goals SET created_at = ?", (created_at,))
    conn.commit()
    conn.close()


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


def test_percentage_edit_uses_january_baseline_even_after_partial_purchase(mock_db):
    portfolio = StubPortfolioProvider(
        [{"ticker": "BBAS3", "quantity": 125}], year_start_quantities={"BBAS3": 100}
    )
    service = ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=portfolio,
        market_analysis_api=StubMarketData,
        planning_provider=GrowthExamplePlanningProvider(),
    )
    target = service.calculate_percentage_target(100, 100)
    service.save_portfolio_goal_plan({"BBAS3": target})
    portfolio.positions[0]["quantity"] = 150

    row = service.get_portfolio_goal_plan()["rows"].iloc[0]
    assert target == 200
    assert row[ShareQuantityGoalService.PLAN_TARGET_QUANTITY] == 200
    assert row[ShareQuantityGoalService.PLAN_GROWTH_PERCENTAGE] == 100


def test_editor_keeps_quantity_and_growth_synchronized_from_january_baseline():
    original = pd.DataFrame(
        [
            {
                "ticker": "BBAS3",
                "year_start_quantity": 100,
                "target_quantity": 150,
                "target_growth_percentage": 50.0,
            },
            {
                "ticker": "TAEE11",
                "year_start_quantity": 0,
                "target_quantity": 25,
                "target_growth_percentage": float("nan"),
            },
        ]
    )
    growth_edit = original.copy()
    growth_edit["target_growth_percentage"] = ["100,00", "N/D"]
    targets = ShareQuantityGoalService.targets_from_edited_rows(original, growth_edit)
    assert targets == {"BBAS3": 200, "TAEE11": 25}

    quantity_edit = original.copy()
    quantity_edit.loc[0, "target_quantity"] = 175
    assert (
        ShareQuantityGoalService.targets_from_edited_rows(original, quantity_edit)["BBAS3"] == 175
    )

    zero_base_growth_edit = original.copy()
    zero_base_growth_edit.loc[1, "target_growth_percentage"] = 100
    with pytest.raises(ValueError, match="N/D"):
        ShareQuantityGoalService.targets_from_edited_rows(original, zero_base_growth_edit)


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
        [{"ticker": "BBAS3", "quantity": 125}], year_start_quantities={"BBAS3": 100}
    )
    service = ShareQuantityGoalService(
        goal_repo=repository,
        portfolio_provider=portfolio,
        market_analysis_api=StubMarketData,
        planning_provider=GrowthExamplePlanningProvider(),
    )
    reference_date = datetime.date(2026, 8, 28)
    service.save_portfolio_goal_plan({"BBAS3": 150}, today_date=reference_date)
    portfolio.positions[0]["quantity"] = 140
    progress = service.list_goals_with_progress(reference_date)[0]
    row = service.get_portfolio_goal_plan(today_date=reference_date)["rows"].iloc[0]

    assert repository.list_accumulation_goals()[0]["start_quantity"] == 100
    assert progress["start_quantity"] == 100
    assert progress["target_quantity"] == 150
    assert progress["progress_percentage"] == 80
    assert row[ShareQuantityGoalService.PLAN_TARGET_QUANTITY] == 150
    assert row[ShareQuantityGoalService.PLAN_GROWTH_PERCENTAGE] == 50


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
        market_analysis_api=StubMarketData,
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
    set_goal_created_at(repository, "2025-12-31")
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
        market_analysis_api=StubMarketData,
        planning_provider=GrowthExamplePlanningProvider(),
    )

    progress = service.list_goals_with_progress(datetime.date(2026, 8, 28))[0]

    assert progress["current_quantity"] == 200
    assert progress["progress_percentage"] == 0
    plan_row = service.get_portfolio_goal_plan(today_date=datetime.date(2026, 8, 28))["rows"].iloc[
        0
    ]
    assert plan_row[ShareQuantityGoalService.PLAN_YEAR_START_QUANTITY] == 200
    assert plan_row[ShareQuantityGoalService.PLAN_TARGET_QUANTITY] == 300


def test_zero_cost_deposit_does_not_rebase_accumulation_goal(mock_db):
    goal = {
        "ticker": "BBAS3",
        "start_quantity": 100,
        "target_quantity": 150,
    }
    portfolio = StubPortfolioProvider(
        [{"ticker": "BBAS3", "quantity": 125}],
        transactions={
            "BBAS3": [
                {
                    "date": "2026-01-02",
                    "transaction_type": "BUY",
                    "quantity": 25,
                    "unit_price": 0.0,
                    "fees": 0.0,
                    "cost_status": "KNOWN",
                    "event_kind": "TRADE",
                }
            ]
        },
    )
    service = ShareQuantityGoalService(portfolio_provider=portfolio)

    result = service._get_corporate_action_adjusted_progress(goal, "2026-01-01")

    assert result == (100.0, 150.0, 50.0)


def test_manual_zero_cost_buy_is_rebased_as_corporate_action(mock_db):
    goal = {
        "ticker": "BBAS3",
        "start_quantity": 100,
        "target_quantity": 150,
    }
    portfolio = StubPortfolioProvider(
        [{"ticker": "BBAS3", "quantity": 200}],
        transactions={
            "BBAS3": [
                {
                    "date": "2026-01-02",
                    "transaction_type": "BUY",
                    "quantity": 100,
                    "unit_price": 0.0,
                    "fees": 0.0,
                    "cost_status": "KNOWN",
                    "event_kind": None,
                }
            ]
        },
    )
    service = ShareQuantityGoalService(portfolio_provider=portfolio)

    result = service._get_corporate_action_adjusted_progress(goal, "2026-01-01")

    assert result == (200.0, 300.0, 0.0)


def test_pending_cost_acquisitions_count_as_accumulation_progress(mock_db):
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
    set_goal_created_at(repository, "2025-12-31")
    portfolio = StubPortfolioProvider(
        [{"ticker": "BBAS3", "quantity": 125}],
        year_start_quantities={"BBAS3": 100},
        transactions={
            "BBAS3": [
                {
                    "date": "2026-01-02",
                    "transaction_type": "BUY",
                    "quantity": 25,
                    "unit_price": 0.0,
                    "fees": 0.0,
                    "cost_status": "PENDING",
                },
            ]
        },
    )
    service = ShareQuantityGoalService(
        goal_repo=repository,
        portfolio_provider=portfolio,
        market_analysis_api=StubMarketData,
        planning_provider=GrowthExamplePlanningProvider(),
    )

    progress = service.list_goals_with_progress(datetime.date(2026, 8, 28))[0]

    assert progress["progress_percentage"] == 50


def test_paid_acquisitions_are_rebased_after_corporate_actions(mock_db):
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
    set_goal_created_at(repository, "2025-12-31")
    portfolio = StubPortfolioProvider(
        [{"ticker": "BBAS3", "quantity": 225}],
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
                {
                    "date": "2026-01-03",
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
        market_analysis_api=StubMarketData,
        planning_provider=GrowthExamplePlanningProvider(),
    )

    progress = service.list_goals_with_progress(datetime.date(2026, 8, 28))[0]

    assert progress["current_quantity"] == 225
    assert progress["start_quantity"] == 200
    assert progress["target_quantity"] == 300
    assert progress["progress_percentage"] == 25


def test_zero_planned_dividends_does_not_block_share_target(mock_db):
    repository = PlanningDAO()
    service = ShareQuantityGoalService(
        goal_repo=repository,
        portfolio_provider=StubPortfolioProvider([{"ticker": "BBAS3", "quantity": 100}]),
        market_analysis_api=StubMarketData,
        planning_provider=EmptyPlanningProvider(),
    )

    goals = service.save_portfolio_goal_plan({"BBAS3": 200})

    assert goals[0]["target_quantity"] == 200
    assert repository.list_accumulation_goals()[0]["is_active"] == 1


def test_market_data_failure_does_not_block_an_existing_share_goal(mock_db):
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
    service = ShareQuantityGoalService(
        goal_repo=repository,
        portfolio_provider=StubPortfolioProvider([{"ticker": "BBAS3", "quantity": 100}]),
        market_analysis_api=FailedMarketData,
        planning_provider=GrowthExamplePlanningProvider(),
    )

    plan = service.get_portfolio_goal_plan()
    assert plan["rows"].iloc[0][ShareQuantityGoalService.PLAN_TARGET_QUANTITY] == 150
    assert plan["total_estimated_cost"] is None
    service.save_portfolio_goal_plan({"BBAS3": 175})
    assert repository.list_accumulation_goals()[0]["target_quantity"] == 175


def test_dashboard_hides_dividend_goal_when_current_projection_is_unavailable(mock_db):
    repository = PlanningDAO()
    repository.upsert_accumulation_goal(
        ticker="BBAS3",
        start_quantity=100,
        target_quantity=150,
        target_mode=ShareQuantityGoalService.MODE_DIVIDEND_INCOME,
        target_percentage=None,
        allocation_weight=100,
        average_dividend_5y=2.0,
    )
    service = ShareQuantityGoalService(
        goal_repo=repository,
        portfolio_provider=StubPortfolioProvider([{"ticker": "BBAS3", "quantity": 100}]),
        market_analysis_api=StubMarketData,
        planning_provider=EmptyPlanningProvider(),
    )

    assert service.list_goals_with_progress(datetime.date(2026, 8, 28)) == []


def test_percentage_goal_recomputes_target_from_new_year_baseline(mock_db):
    repository = PlanningDAO()
    repository.upsert_accumulation_goal(
        ticker="BBAS3",
        start_quantity=100,
        target_quantity=110,
        target_mode=ShareQuantityGoalService.MODE_PERCENTAGE,
        target_percentage=10,
        allocation_weight=100,
        average_dividend_5y=2.0,
    )
    service = ShareQuantityGoalService(
        goal_repo=repository,
        portfolio_provider=StubPortfolioProvider(
            [{"ticker": "BBAS3", "quantity": 110}],
            year_start_quantities={"BBAS3": 105},
        ),
        market_analysis_api=StubMarketData,
        planning_provider=GrowthExamplePlanningProvider(),
    )

    progress = service.list_goals_with_progress(datetime.date(2026, 8, 28))[0]

    assert progress["start_quantity"] == 105
    assert progress["target_quantity"] == 116
    assert progress["progress_percentage"] == pytest.approx(45.45454545)


def test_same_day_corporate_action_is_processed_before_paid_purchase(mock_db):
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
    set_goal_created_at(repository, "2025-12-31")
    portfolio = StubPortfolioProvider(
        [{"ticker": "BBAS3", "quantity": 225}],
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
        market_analysis_api=StubMarketData,
        planning_provider=GrowthExamplePlanningProvider(),
    )

    progress = service.list_goals_with_progress(datetime.date(2026, 8, 28))[0]

    assert progress["progress_percentage"] == 25
    assert progress["start_quantity"] == 200
    assert progress["target_quantity"] == 300


def test_dashboard_excludes_goals_for_assets_no_longer_held(mock_db):
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
    service = ShareQuantityGoalService(
        goal_repo=repository,
        portfolio_provider=StubPortfolioProvider([]),
        market_analysis_api=StubMarketData,
        planning_provider=GrowthExamplePlanningProvider(),
    )

    assert service.list_goals_with_progress(datetime.date(2026, 8, 28)) == []


def test_goal_below_year_start_shows_position_excess_over_target(mock_db):
    repository = PlanningDAO()
    repository.upsert_accumulation_goal(
        ticker="CSMG3",
        start_quantity=4283,
        target_quantity=5000,
        target_mode=ShareQuantityGoalService.MODE_DIVIDEND_INCOME,
        target_percentage=None,
        allocation_weight=5,
        average_dividend_5y=2.0,
    )
    service = ShareQuantityGoalService(
        goal_repo=repository,
        portfolio_provider=StubPortfolioProvider([{"ticker": "CSMG3", "quantity": 4541}]),
        market_analysis_api=StubMarketData,
        planning_provider=GrowthExamplePlanningProvider(),
    )

    progress = service.list_goals_with_progress(datetime.date(2026, 8, 28))[0]

    assert progress["target_quantity"] == 8
    assert progress["progress_percentage"] == pytest.approx(4541 / 8 * 100)


def test_saved_target_is_not_rebased_again_for_prior_corporate_action(mock_db):
    portfolio = StubPortfolioProvider(
        [{"ticker": "BBAS3", "quantity": 200}],
        transactions={
            "BBAS3": [
                {
                    "date": "2026-01-02",
                    "transaction_type": "BUY",
                    "quantity": 100,
                    "unit_price": 0.0,
                    "fees": 0.0,
                }
            ]
        },
    )
    service = ShareQuantityGoalService(portfolio_provider=portfolio)

    result = service._get_corporate_action_adjusted_progress(
        {
            "ticker": "BBAS3",
            "start_quantity": 100,
            "target_quantity": 250,
            "created_at": "2026-01-03 10:00:00",
        },
        "2026-01-01",
        "2026-01-03",
    )

    assert result[0:2] == (200.0, 250.0)


def test_same_day_pre_save_corporate_action_does_not_rebase_saved_target(mock_db):
    portfolio = StubPortfolioProvider(
        [{"ticker": "BBAS3", "quantity": 200}],
        transactions={
            "BBAS3": [
                {
                    "date": "2026-01-03",
                    "transaction_type": "BUY",
                    "quantity": 100,
                    "unit_price": 0.0,
                    "fees": 0.0,
                }
            ]
        },
    )
    service = ShareQuantityGoalService(portfolio_provider=portfolio)

    result = service._get_corporate_action_adjusted_progress(
        {"ticker": "BBAS3", "start_quantity": 100, "target_quantity": 250},
        "2026-01-01",
        "2026-01-03",
    )

    assert result[0:2] == (200.0, 250.0)


def test_partial_market_failure_keeps_targets_editable(mock_db):
    service = ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=StubPortfolioProvider(
            [{"ticker": "BBAS3", "quantity": 100}, {"ticker": "TAEE11", "quantity": 100}]
        ),
        market_analysis_api=PartialFailedMarketData,
        planning_provider=StubPlanningProvider(),
    )

    plan = service.get_portfolio_goal_plan({"BBAS3": 150, "TAEE11": 200})
    assert plan["total_estimated_cost"] is None
    assert set(
        service_goal["ticker"]
        for service_goal in service.save_portfolio_goal_plan({"BBAS3": 150, "TAEE11": 200})
    ) == {"BBAS3", "TAEE11"}


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


def test_annual_goal_is_unavailable_when_trade_cost_is_pending(mock_db):
    service = GoalService(
        settings_repo=PlanningDAO(),
        portfolio_provider=StubPortfolioProvider([], ytd_contributions=None),
        planning_provider=StubPlanningProvider(),
    )

    goal = service.get_annual_investment_goal(2026, ytd_dividends=1_000)

    assert goal["ytd_contributions"] is None
    assert goal["contributions_pending"] is True
    assert goal["progress_percentage"] is None
    assert goal["remaining_to_invest"] is None


def test_annual_goal_is_unavailable_when_planning_simulation_is_pending(mock_db):
    class UnavailablePlanningProvider:
        @staticmethod
        def get_current_simulation():
            return None

        @staticmethod
        def get_updated_required_contribution():
            return 0.0

    service = GoalService(
        settings_repo=PlanningDAO(),
        portfolio_provider=StubPortfolioProvider([], ytd_contributions=15_000),
        planning_provider=UnavailablePlanningProvider(),
    )

    goal = service.get_annual_investment_goal(2026, ytd_dividends=1_000)

    assert goal["planning_pending"] is True
    assert goal["contributions_pending"] is True
    assert goal["progress_percentage"] is None
    assert goal["remaining_to_invest"] is None


def test_net_withdrawal_increases_remaining_annual_contribution(mock_db):
    from services.assets_service import AssetService

    assert AssetService.add_transaction("BBAS3", "2025-12-01", "BUY", 100, 100)
    assert AssetService.add_transaction("BBAS3", "2026-01-01", "SELL", 100, 100, 20)
    service = GoalService(
        settings_repo=PlanningDAO(),
        portfolio_provider=PortfolioReadService.get_default(),
        planning_provider=StubPlanningProvider(),
    )

    goal = service.get_annual_investment_goal(2026, ytd_dividends=0)

    assert goal["ytd_contributions"] == -9_980
    assert goal["remaining_to_invest"] == 21_980
    assert goal["progress_percentage"] == pytest.approx(-83.16666667)
    assert not goal["contributions_pending"]


def test_annual_goal_is_available_without_planning_configuration(mock_db):
    service = GoalService(
        settings_repo=PlanningDAO(),
        portfolio_provider=StubPortfolioProvider([], ytd_contributions=15_000),
        planning_provider=StubPlanningProvider(),
    )

    goal = service.get_annual_investment_goal(2026, ytd_dividends=1_000)

    assert goal["planning_pending"] is False
    assert goal["contributions_pending"] is False
    assert goal["annual_salary_goal"] == 12_000


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
        market_analysis_api=StubMarketData,
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
    assert service.list_goals_with_progress() == []


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
        market_analysis_api=BbasMarketData,
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
        market_analysis_api=BbasMarketData,
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
        market_analysis_api=BbasMarketData,
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


def test_portfolio_plan_lists_every_asset_without_allocating_income(mock_db):
    tickers = ["BBAS3", "TAEE11", "PETR4", "VALE3", "ITSA4", "CXSE3", "BBSE3"]
    service = ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=StubPortfolioProvider(
            [{"ticker": ticker, "quantity": 100} for ticker in tickers]
        ),
        market_analysis_api=PortfolioMarketData,
        planning_provider=AnnualExamplePlanningProvider(),
    )

    plan = service.get_portfolio_goal_plan()
    rows = plan["rows"].set_index("ticker")
    assert len(rows) == 7
    assert plan["planned_annual_dividends"] == pytest.approx(4_816.63)
    assert all(rows["target_quantity"] == 101)
    assert all(rows["target_growth_percentage"] == 1)


def test_partial_dividend_history_does_not_determine_share_target(mock_db):
    service = ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=StubPortfolioProvider([{"ticker": "NEW3", "quantity": 100}]),
        market_analysis_api=PartialHistoryMarketData,
        planning_provider=AnnualExamplePlanningProvider(),
    )

    row = service.get_portfolio_goal_plan()["rows"].iloc[0]
    assert row[ShareQuantityGoalService.PLAN_AVERAGE_DIVIDEND] == 3.0
    assert row[ShareQuantityGoalService.PLAN_TARGET_QUANTITY] == 101
    assert "média calculada com 2 ano(s)" in row[ShareQuantityGoalService.PLAN_HISTORY_NOTE]


def test_missing_dividend_history_does_not_block_saving_share_goal(mock_db):
    service = ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=StubPortfolioProvider([{"ticker": "NEW3", "quantity": 100}]),
        market_analysis_api=EmptyMarketData,
        planning_provider=AnnualExamplePlanningProvider(),
    )

    service.save_portfolio_goal_plan({"NEW3": 150})
    row = service.get_portfolio_goal_plan()["rows"].iloc[0]
    assert row[ShareQuantityGoalService.PLAN_TARGET_QUANTITY] == 150
    assert "Sem histórico de proventos" in row[ShareQuantityGoalService.PLAN_HISTORY_NOTE]


def test_targets_are_not_constrained_by_planned_income_or_total_weights(mock_db):
    class PricedMarketData:
        @staticmethod
        def get_ticker_market_analysis(ticker, target_yield_pct=6.0):
            return {"current_price": 10.0, "avg_dividend_5y": 2.0}

    service = ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=StubPortfolioProvider(
            [{"ticker": "BBAS3", "quantity": 100}, {"ticker": "TAEE11", "quantity": 100}]
        ),
        market_analysis_api=PricedMarketData,
        planning_provider=StubPlanningProvider(),
    )
    targets = {"BBAS3": 10000, "TAEE11": 200}
    plan = service.get_portfolio_goal_plan(targets)
    rows = plan["rows"].set_index("ticker")
    assert plan["total_estimated_cost"] == 100_000
    assert plan["projected_annual_dividends"] == 20_400
    assert plan["estimated_external_contribution"] == 79_600
    assert plan["exceeds_planned_resources"] is True
    assert rows.loc["BBAS3", "allocation_weight"] == pytest.approx(99)
    assert rows.loc["TAEE11", "allocation_weight"] == pytest.approx(1)
    assert len(service.save_portfolio_goal_plan(targets)) == 2


def test_invalid_target_does_not_partially_save_plan(mock_db):
    service = ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=StubPortfolioProvider(
            [{"ticker": "BBAS3", "quantity": 100}, {"ticker": "TAEE11", "quantity": 100}]
        ),
        market_analysis_api=StubMarketData,
        planning_provider=StubPlanningProvider(),
    )

    with pytest.raises(ValueError, match="inteira e não negativa"):
        service.save_portfolio_goal_plan({"BBAS3": 150, "TAEE11": -1})
    assert PlanningDAO().list_accumulation_goals() == []


def test_zero_january_baseline_accepts_a_share_target_and_has_no_growth_percentage(mock_db):
    service = ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=StubPortfolioProvider(
            [{"ticker": "BBAS3", "quantity": 25}], year_start_quantities={"BBAS3": 0}
        ),
        market_analysis_api=BbasMarketData,
        planning_provider=AnnualExamplePlanningProvider(),
    )

    service.save_portfolio_goal_plan({"BBAS3": 50})
    row = service.get_portfolio_goal_plan()["rows"].iloc[0]
    assert row[ShareQuantityGoalService.PLAN_TARGET_QUANTITY] == 50
    assert pd.isna(row[ShareQuantityGoalService.PLAN_GROWTH_PERCENTAGE])
    assert "N/D" in row[ShareQuantityGoalService.PLAN_HISTORY_NOTE]


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
        market_analysis_api=EmptyMarketData,
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
        market_analysis_api=EmptyMarketData,
        planning_provider=AnnualExamplePlanningProvider(),
    )

    goal = service.create_goal("NEW3", ShareQuantityGoalService.MODE_DIVIDEND_INCOME)

    assert goal["target_available"] is False
    assert "Sem histórico de proventos" in goal[ShareQuantityGoalService.PLAN_HISTORY_NOTE]
    assert service.list_goals_with_progress() == []


def test_negative_target_cannot_be_created(mock_db):
    service = build_service([{"ticker": "BBAS3", "quantity": 100}])

    with pytest.raises(ValueError, match="não negativa"):
        service.create_goal("BBAS3", ShareQuantityGoalService.MODE_QUANTITY, -1)


def test_accumulation_goal_can_be_deleted(mock_db):
    service = build_service([{"ticker": "BBAS3", "quantity": 100}])
    service.create_goal("BBAS3", ShareQuantityGoalService.MODE_QUANTITY, 150)

    assert service.delete_goal("bbas3") is True
    assert service.list_goals_with_progress() == []


def test_planning_editor_shows_zero_baseline_growth_as_nd_and_keeps_saving_available(monkeypatch):
    rows = pd.DataFrame(
        [
            {
                "ticker": "BBAS3",
                "year_start_quantity": 0,
                "current_quantity": 25,
                "target_quantity": 50,
                "target_growth_percentage": float("nan"),
                "current_price": 10.0,
                "average_dividend_5y": 2.0,
                "estimated_cost": 500.0,
                "remaining_estimated_cost": 250.0,
                "allocation_weight": 100.0,
                "projected_annual_dividends": 100.0,
                "dividend_history_note": "Crescimento N/D: sem posição em 01/01.",
            }
        ]
    )
    plan = {
        "rows": rows,
        "total_estimated_cost": 500.0,
        "total_remaining_cost": 250.0,
        "projected_annual_dividends": 100.0,
        "estimated_external_contribution": 400.0,
        "planned_annual_dividends": 50.0,
        "planned_external_contribution": 100.0,
        "exceeds_planned_resources": True,
    }
    captured = {}

    def editor(data, **kwargs):
        captured["rows"] = data
        captured["disabled"] = kwargs["disabled"]
        return data

    def button(*args, **kwargs):
        captured["save_disabled"] = kwargs.get("disabled", False)
        return False

    class Column:
        def metric(self, label, value, **kwargs):
            captured.setdefault("metrics", {})[label] = (value, kwargs.get("help"))

    monkeypatch.setattr(ShareQuantityGoalService, "get_portfolio_goal_plan", lambda *_: plan)
    monkeypatch.setattr("views.components.accumulation_goals.st.session_state", {})
    monkeypatch.setattr("views.components.accumulation_goals.st.data_editor", editor)
    monkeypatch.setattr("views.components.accumulation_goals.st.button", button)
    monkeypatch.setattr("views.components.accumulation_goals.st.columns", lambda *_: [Column()] * 4)
    monkeypatch.setattr(
        "views.components.accumulation_goals.st.caption",
        lambda message: captured.setdefault("captions", []).append(message),
    )
    for name in ("markdown", "subheader", "write", "warning", "info"):
        monkeypatch.setattr(f"views.components.accumulation_goals.st.{name}", lambda *_: None)

    widget = AccumulationGoalPlanningWidget()
    monkeypatch.setattr(
        widget,
        "_render_editor",
        lambda *args: AccumulationGoalPlanningWidget._render_editor.__wrapped__(widget, *args),
    )
    widget.render()

    assert captured["rows"].iloc[0]["target_growth_percentage"] == "N/D"
    assert "target_quantity" not in captured["disabled"]
    assert "target_growth_percentage" not in captured["disabled"]
    assert "allocation_weight" in captured["disabled"]
    assert "remaining_estimated_cost" in captured["disabled"]
    assert captured["rows"].iloc[0]["estimated_cost"] == "R$ 500,00"
    assert captured["rows"].iloc[0]["remaining_estimated_cost"] == "R$ 250,00"
    assert "save_disabled" not in captured
    assert all(help_text for _, help_text in captured["metrics"].values())
    assert captured["metrics"]["Aporte externo anual estimado"][0] == "R$ 400,00"
    assert (
        "proventos anuais projetados"
        in captured["metrics"]["Aporte externo anual estimado"][1].lower()
    )
    assert not any("Recursos planejados:" in caption for caption in captured.get("captions", []))


def test_reverse_split_plan_can_be_saved_in_current_trading_units(mock_db):
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
    set_goal_created_at(repository, "2025-12-31")
    service = ShareQuantityGoalService(
        goal_repo=repository,
        portfolio_provider=StubPortfolioProvider(
            [{"ticker": "BBAS3", "quantity": 50}],
            year_start_quantities={"BBAS3": 100},
            transactions={
                "BBAS3": [
                    {
                        "date": "2026-01-02",
                        "transaction_type": "GROUP",
                        "quantity": 50,
                        "unit_price": 0,
                        "fees": 0,
                    }
                ]
            },
        ),
        market_analysis_api=StubMarketData,
        planning_provider=StubPlanningProvider(),
    )
    date = datetime.date(2026, 8, 28)
    row = service.get_portfolio_goal_plan(today_date=date)["rows"].iloc[0]
    assert row[ShareQuantityGoalService.PLAN_YEAR_START_QUANTITY] == 50
    assert row[ShareQuantityGoalService.PLAN_TARGET_QUANTITY] == 75
    service.save_portfolio_goal_plan({"BBAS3": 75}, today_date=date)
    assert service.list_goals_with_progress(date)[0]["target_quantity"] == 75


def _render_accumulation_editor():
    from views.components.accumulation_goals import AccumulationGoalPlanningWidget

    AccumulationGoalPlanningWidget().render()


@pytest.mark.parametrize(
    ("column", "value", "expected_target", "expected_growth"),
    [
        ("target_quantity", 200, 200, "100,00"),
        ("target_growth_percentage", "100,00", 200, "100,00"),
        ("target_growth_percentage", "0", 100, "0,00"),
        ("target_growth_percentage", "-25", 75, "-25,00"),
        ("target_growth_percentage", "-100", 0, "-100,00"),
        ("target_quantity", 75, 75, "-25,00"),
        ("target_quantity", 0, 0, "-100,00"),
    ],
)
@pytest.mark.parametrize("refresh_quote", [False, True])
def test_streamlit_editor_synchronizes_fields_after_a_real_edit(
    monkeypatch, column, value, expected_target, expected_growth, refresh_quote
):
    import json
    from streamlit.testing.v1 import AppTest
    from streamlit.proto.WidgetStates_pb2 import WidgetStates

    class RefreshingMarketData:
        price = 10.0
        calls = 0

        def get_ticker_market_analysis(self, ticker):
            self.calls += 1
            if refresh_quote:
                self.price += 0.01
            return {"current_price": self.price, "avg_dividend_5y": 2.0}

    service = build_service([{"ticker": "BBAS3", "quantity": 100}])
    service._market_analysis_api = RefreshingMarketData()
    service.save_portfolio_goal_plan({"BBAS3": 150})
    monkeypatch.setattr(ShareQuantityGoalService, "_default_instance", service)
    app = AppTest.from_function(_render_accumulation_editor, default_timeout=60).run()
    assert not app.exception

    def submit_edit(edited_column, edited_value):
        states = WidgetStates()
        state = states.widgets.add()
        state.id = app.dataframe[0].proto.id
        state.string_value = json.dumps(
            {
                "edited_rows": {"0": {edited_column: edited_value}},
                "added_rows": [],
                "deleted_rows": [],
            }
        )
        app._run(states)
        assert not app.exception

    initial_market_calls = service._market_analysis_api.calls
    submit_edit(column, value)
    assert service._goal_repo.list_accumulation_goals()[0]["target_quantity"] == expected_target
    assert service._market_analysis_api.calls == initial_market_calls
    row = app.dataframe[0].value.iloc[0]
    assert row["target_quantity"] == expected_target
    assert row["target_growth_percentage"] == expected_growth

    previous_editor_id = app.dataframe[0].proto.id
    submit_edit("target_quantity", -1)
    assert "inteira e não negativa" in app.error[0].value
    assert app.dataframe[0].proto.id != previous_editor_id
    assert not app.button
    assert service._goal_repo.list_accumulation_goals()[0]["target_quantity"] == expected_target

    submit_edit("target_growth_percentage", "125,00")
    row = app.dataframe[0].value.iloc[0]
    assert row["target_quantity"] == 225
    assert row["target_growth_percentage"] == "125,00"
    assert not app.error
    assert not app.button
    assert service._goal_repo.list_accumulation_goals()[0]["target_quantity"] == 225


@pytest.mark.parametrize(("percentage", "expected"), [(0, 100), (-25, 75), (-100, 0)])
def test_percentage_target_accepts_maintenance_and_reductions(percentage, expected):
    assert ShareQuantityGoalService.calculate_percentage_target(100, percentage) == expected


def test_percentage_target_rejects_reduction_below_minus_one_hundred():
    with pytest.raises(ValueError):
        ShareQuantityGoalService.calculate_percentage_target(100, -100.01)


@pytest.mark.parametrize(
    ("current", "target", "expected"),
    [
        (100, 100, 100),
        (125, 100, 0),
        (75, 100, 0),
        (100, 50, 0),
        (75, 50, 50),
        (50, 50, 100),
        (25, 50, 150),
        (100, 0, 0),
        (50, 0, 50),
        (0, 0, 100),
    ],
)
def test_progress_tracks_maintenance_and_sales(current, target, expected):
    assert ShareQuantityGoalService.calculate_progress(100, current, target) == expected


@pytest.mark.parametrize("market_data", [StubMarketData, EmptyMarketData])
def test_liquidation_target_remains_visible_and_complete_after_full_sale(mock_db, market_data):
    portfolio = StubPortfolioProvider(
        [{"ticker": "SANB3", "quantity": 100}], year_start_quantities={"SANB3": 100}
    )
    service = ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=portfolio,
        market_analysis_api=market_data,
        planning_provider=StubPlanningProvider(),
    )
    service.save_portfolio_goal_plan({"SANB3": 0})
    portfolio.positions = []
    portfolio.transactions = {
        "SANB3": [
            {
                "date": "2026-06-01",
                "transaction_type": "SELL",
                "quantity": 100,
                "unit_price": 10,
                "fees": 0,
            }
        ]
    }
    goal = service.list_goals_with_progress()[0]
    assert goal["ticker"] == "SANB3"
    assert goal["target_quantity"] == 0
    assert goal["current_quantity"] == 0
    assert goal["progress_percentage"] == 100
    plan = service.get_portfolio_goal_plan()
    row = plan["rows"].iloc[0]
    assert row["target_quantity"] == 0
    assert row["target_growth_percentage"] == -100
    assert plan["total_estimated_cost"] == 0
    assert plan["projected_annual_dividends"] == 0


def test_reduction_plan_preserves_target_and_does_not_create_purchase_cost(mock_db):
    class PricedMarketData:
        @staticmethod
        def get_ticker_market_analysis(ticker):
            return {"current_price": 10.0, "avg_dividend_5y": 2.0}

    portfolio = StubPortfolioProvider(
        [{"ticker": "SANB3", "quantity": 100}], year_start_quantities={"SANB3": 100}
    )
    service = ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=portfolio,
        market_analysis_api=PricedMarketData,
        planning_provider=StubPlanningProvider(),
    )
    service.save_portfolio_goal_plan({"SANB3": 50})
    portfolio.positions[0]["quantity"] = 75
    portfolio.transactions = {
        "SANB3": [
            {
                "date": "2026-06-01",
                "transaction_type": "SELL",
                "quantity": 25,
                "unit_price": 10,
                "fees": 0,
            }
        ]
    }
    plan = service.get_portfolio_goal_plan()
    row = plan["rows"].iloc[0]
    assert row["target_quantity"] == 50
    assert row["target_growth_percentage"] == -50
    assert plan["total_estimated_cost"] == 0
    assert plan["projected_annual_dividends"] == 100
    assert service.list_goals_with_progress()[0]["progress_percentage"] == 50


def test_goal_schema_migration_preserves_saved_goals_and_accepts_zero_targets(tmp_path):
    from core.database import CURRENT_SCHEMA_VERSION

    path = tmp_path / "growth-only.db"
    connection = sqlite3.connect(path)
    connection.execute("""
        CREATE TABLE asset_accumulation_goals (
            ticker TEXT PRIMARY KEY,
            start_quantity REAL NOT NULL CHECK (start_quantity >= 0),
            target_quantity REAL NOT NULL CHECK (target_quantity > start_quantity),
            target_mode TEXT NOT NULL,
            target_percentage REAL,
            allocation_weight REAL NOT NULL CHECK (allocation_weight >= 0 AND allocation_weight <= 100),
            average_dividend_5y REAL NOT NULL CHECK (average_dividend_5y >= 0),
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    connection.execute("""
        INSERT INTO asset_accumulation_goals VALUES
        ('SANB3', 100, 150, 'QUANTITY', NULL, 100, 2, 1, '2026-01-02 10:00:00')
    """)
    connection.execute("PRAGMA user_version = 1")
    connection.commit()
    original = connection.execute("SELECT * FROM asset_accumulation_goals").fetchone()
    connection.close()
    manager = DatabaseManager(path)
    manager.init_personal_db()
    connection = manager.get_personal_connection()
    assert connection.execute("SELECT * FROM asset_accumulation_goals").fetchone() == original
    connection.execute("UPDATE asset_accumulation_goals SET target_quantity = 0")
    connection.commit()
    assert connection.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("UPDATE asset_accumulation_goals SET target_quantity = -1")
    connection.close()
    manager.init_personal_db()
    assert PlanningDAO(manager).list_accumulation_goals()[0]["target_quantity"] == 0


def test_maintenance_requires_current_position_to_match_target_after_custody_entry(mock_db):
    portfolio = StubPortfolioProvider(
        [{"ticker": "SANB3", "quantity": 100}], year_start_quantities={"SANB3": 100}
    )
    service = ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=portfolio,
        market_analysis_api=StubMarketData,
        planning_provider=StubPlanningProvider(),
    )
    service.save_portfolio_goal_plan({"SANB3": 100})
    assert service.list_goals_with_progress()[0]["progress_percentage"] == 100
    portfolio.positions[0]["quantity"] = 125
    portfolio.transactions = {
        "SANB3": [
            {
                "date": "2026-06-01",
                "transaction_type": "TRANSFER_IN",
                "quantity": 25,
                "unit_price": 10,
                "fees": 0,
                "event_kind": "TRANSFER_IN",
            }
        ]
    }
    assert service.list_goals_with_progress()[0]["progress_percentage"] == 0


@pytest.mark.parametrize("current_quantity", [40, 100, 120])
def test_annual_effort_uses_january_baseline_and_stays_stable_after_purchases(
    mock_db, current_quantity
):
    class PricedMarketData:
        @staticmethod
        def get_ticker_market_analysis(ticker):
            return {"current_price": 10.0, "avg_dividend_5y": 2.0}

    class AnnualPlanningProvider:
        @staticmethod
        def get_planned_annual_dividends():
            return 200.0

        @staticmethod
        def get_current_simulation():
            return {"updated_monthly_contribution": 100.0}

    service = ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=StubPortfolioProvider(
            [
                {"ticker": "BBAS3", "quantity": 125},
                {"ticker": "SANB3", "quantity": current_quantity},
            ],
            year_start_quantities={"BBAS3": 100, "SANB3": 0},
        ),
        market_analysis_api=PricedMarketData,
        planning_provider=AnnualPlanningProvider(),
    )
    targets = {"BBAS3": 150, "SANB3": 100}
    plan = service.get_portfolio_goal_plan(targets)
    rows = plan["rows"].set_index("ticker")
    assert rows.loc["BBAS3", "estimated_cost"] == 500
    assert rows.loc["SANB3", "estimated_cost"] == 1000
    assert rows.loc["BBAS3", "remaining_estimated_cost"] == 250
    assert rows.loc["SANB3", "remaining_estimated_cost"] == max(100 - current_quantity, 0) * 10
    assert rows.loc["BBAS3", "allocation_weight"] == pytest.approx(100 / 3)
    assert rows.loc["SANB3", "allocation_weight"] == pytest.approx(200 / 3)
    assert plan["total_estimated_cost"] == 1500
    assert plan["total_remaining_cost"] == 250 + max(100 - current_quantity, 0) * 10
    assert plan["estimated_external_contribution"] == 1000
    assert plan["exceeds_planned_resources"] is False
    service.save_portfolio_goal_plan(targets)
    stored = {goal["ticker"]: goal for goal in service._goal_repo.list_accumulation_goals()}
    assert stored["SANB3"]["allocation_weight"] == pytest.approx(200 / 3)


def test_completed_goal_without_quote_has_unknown_annual_effort_but_zero_remaining_cost(mock_db):
    service = ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=StubPortfolioProvider(
            [{"ticker": "SANB3", "quantity": 100}], year_start_quantities={"SANB3": 0}
        ),
        market_analysis_api=StubMarketData,
        planning_provider=StubPlanningProvider(),
    )
    plan = service.get_portfolio_goal_plan({"SANB3": 100})
    assert plan["total_estimated_cost"] is None
    assert plan["estimated_external_contribution"] is None
    assert plan["total_remaining_cost"] == 0
    assert pd.isna(plan["rows"].iloc[0]["allocation_weight"])


def test_maintenance_plan_separates_zero_annual_effort_from_replacement_purchases(mock_db):
    class PricedMarketData:
        @staticmethod
        def get_ticker_market_analysis(ticker):
            return {"current_price": 10.0, "avg_dividend_5y": 2.0}

    service = ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=StubPortfolioProvider(
            [{"ticker": "SANB3", "quantity": 75}], year_start_quantities={"SANB3": 100}
        ),
        market_analysis_api=PricedMarketData,
        planning_provider=StubPlanningProvider(),
    )
    plan = service.get_portfolio_goal_plan({"SANB3": 100})
    assert plan["total_estimated_cost"] == 0
    assert plan["total_remaining_cost"] == 250
    assert plan["estimated_external_contribution"] == 0
    assert plan["rows"].iloc[0]["allocation_weight"] == 0


@pytest.mark.parametrize(
    ("average_dividend", "history_years", "expected_external", "expected_warning"),
    [(2.0, 5, 200.0, True), (5.0, 5, 0.0, False), (0.0, 5, 500.0, True), (0.0, 0, None, False)],
)
def test_external_contribution_uses_goal_dividends_and_handles_missing_history(
    mock_db, average_dividend, history_years, expected_external, expected_warning
):
    class MarketData:
        @staticmethod
        def get_ticker_market_analysis(ticker):
            return {
                "current_price": 10.0,
                "avg_dividend_5y": average_dividend,
                "dividend_average_years": history_years,
            }

    class PlanningProvider:
        @staticmethod
        def get_planned_annual_dividends():
            return 900.0

        @staticmethod
        def get_current_simulation():
            return {"updated_monthly_contribution": 10.0}

    service = ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=StubPortfolioProvider([{"ticker": "SANB3", "quantity": 100}]),
        market_analysis_api=MarketData,
        planning_provider=PlanningProvider(),
    )
    plan = service.get_portfolio_goal_plan({"SANB3": 150})
    assert plan["total_estimated_cost"] == 500
    assert plan["estimated_external_contribution"] == expected_external
    assert plan["exceeds_planned_resources"] is expected_warning
    assert len(service.save_portfolio_goal_plan({"SANB3": 150})) == 1


@pytest.mark.parametrize(
    ("price", "expected_progress"), [(10, 50), (20, 100 * 2 / 3), (None, 50), ("unavailable", 50)]
)
def test_dashboard_recalculates_annual_weights_instead_of_discarding_completed_goals(
    mock_db, price, expected_progress
):
    repository = PlanningDAO()
    for ticker, weight in [("BBAS3", 0), ("SANB3", 100)]:
        repository.upsert_accumulation_goal(
            ticker=ticker,
            start_quantity=100,
            target_quantity=200,
            target_mode=ShareQuantityGoalService.MODE_QUANTITY,
            target_percentage=None,
            allocation_weight=weight,
            average_dividend_5y=2,
        )

    class MarketData:
        @staticmethod
        def get_ticker_market_analysis(ticker):
            if price == "unavailable":
                raise RuntimeError("Market data unavailable")
            return {"current_price": price if ticker == "BBAS3" else 10, "avg_dividend_5y": 2}

    service = ShareQuantityGoalService(
        goal_repo=repository,
        portfolio_provider=StubPortfolioProvider(
            [{"ticker": "BBAS3", "quantity": 200}, {"ticker": "SANB3", "quantity": 100}],
            year_start_quantities={"BBAS3": 100, "SANB3": 100},
        ),
        market_analysis_api=MarketData,
        planning_provider=StubPlanningProvider(),
    )
    goals = service.list_goals_with_progress()
    assert [goal["progress_percentage"] for goal in goals] == [100, 0]
    assert service.calculate_weighted_progress(goals) == pytest.approx(expected_progress)
    assert [goal["allocation_weight"] for goal in goals] == pytest.approx(
        [expected_progress, 100 - expected_progress]
    )
    assert [goal["allocation_weight"] for goal in repository.list_accumulation_goals()] == [0, 100]


@pytest.mark.parametrize("target", [0, 100, 200])
def test_saved_snapshot_edits_recalculate_without_market_or_portfolio_queries(
    mock_db, monkeypatch, target
):
    class MarketData:
        @staticmethod
        def get_ticker_market_analysis(ticker):
            return {"current_price": 10, "avg_dividend_5y": 2}

    portfolio = StubPortfolioProvider(
        [{"ticker": "BBAS3", "quantity": 125}, {"ticker": "SANB3", "quantity": 100}],
        year_start_quantities={"BBAS3": 100, "SANB3": 100},
    )
    service = ShareQuantityGoalService(
        goal_repo=PlanningDAO(),
        portfolio_provider=portfolio,
        market_analysis_api=MarketData,
        planning_provider=StubPlanningProvider(),
    )
    service.save_portfolio_goal_plan({"BBAS3": 150, "SANB3": 150})
    snapshot = service.get_portfolio_goal_plan()
    unchanged_goal = service._goal_repo.list_accumulation_goals()[1].copy()

    def unexpected_query(*args, **kwargs):
        raise AssertionError("editing must use the displayed snapshot")

    monkeypatch.setattr(MarketData, "get_ticker_market_analysis", unexpected_query)
    monkeypatch.setattr(portfolio, "read_planning", unexpected_query)
    monkeypatch.setattr(StubPlanningProvider, "get_current_simulation", unexpected_query)
    updated = service.save_edited_goal_plan(snapshot, {"BBAS3": target, "SANB3": 150})
    assert snapshot["rows"].iloc[0]["target_quantity"] == 150
    assert updated["total_estimated_cost"] == max(target - 100, 0) * 10 + 500
    assert updated["total_remaining_cost"] == max(target - 125, 0) * 10 + 500
    assert updated["projected_annual_dividends"] == target * 2 + 300
    assert service._goal_repo.list_accumulation_goals()[0]["target_quantity"] == target
    assert service._goal_repo.list_accumulation_goals()[1] == unchanged_goal


def test_automatic_save_failure_keeps_displayed_and_persisted_target(mock_db, monkeypatch):
    service = build_service([{"ticker": "BBAS3", "quantity": 100}])
    service.save_portfolio_goal_plan({"BBAS3": 150})
    plan = service.get_portfolio_goal_plan()
    state = {"editor": {"edited_rows": {"0": {"target_quantity": 200}}}}
    monkeypatch.setattr(ShareQuantityGoalService, "_default_instance", service)
    monkeypatch.setattr("views.components.accumulation_goals.st.session_state", state)

    def failed_write(goals):
        raise sqlite3.OperationalError("database is locked")

    with monkeypatch.context() as patch:
        patch.setattr(service._goal_repo, "upsert_accumulation_goals", failed_write)
        AccumulationGoalPlanningWidget._on_editor_change(
            plan, "editor", "snapshot"
        )
    assert state["snapshot"]["rows"].iloc[0]["target_quantity"] == 150
    assert service._goal_repo.list_accumulation_goals()[0]["target_quantity"] == 150
    assert "Não foi possível salvar" in state["snapshot_error"]
    AccumulationGoalPlanningWidget._on_editor_change(
        plan, "editor", "snapshot"
    )
    assert "snapshot_error" not in state
    assert service._goal_repo.list_accumulation_goals()[0]["target_quantity"] == 200


@pytest.mark.parametrize("save_error", [
    ValueError("Meta inválida."),
    RuntimeError("private storage details"),
    sqlite3.OperationalError("private database details"),
])
def test_table_save_failure_restores_snapshot_and_retry_invalidates_detail(
    monkeypatch, save_error
):
    import json
    from streamlit.testing.v1 import AppTest
    from streamlit.proto.WidgetStates_pb2 import WidgetStates
    from core.constants import WIDGET_ASSET_ANNUAL_GOAL_PREFIX

    service = build_service([{"ticker": "BBAS3", "quantity": 100}])
    service.save_portfolio_goal_plan({"BBAS3": 150})
    monkeypatch.setattr(ShareQuantityGoalService, "_default_instance", service)
    app = AppTest.from_function(_render_accumulation_editor, default_timeout=30).run()
    assert not app.exception
    detail_error_key = f"{WIDGET_ASSET_ANNUAL_GOAL_PREFIX}test_error"
    app.session_state[detail_error_key] = "previous detail error"

    def unexpected_query(*args, **kwargs):
        raise AssertionError("Cell edits must retain the displayed snapshot")

    monkeypatch.setattr(service, "get_portfolio_goal_plan", unexpected_query)
    monkeypatch.setattr(service._market_analysis_api, "get_ticker_market_analysis", unexpected_query)
    monkeypatch.setattr(service._portfolio_provider, "read_planning", unexpected_query)
    monkeypatch.setattr(service._planning_provider, "get_current_simulation", unexpected_query)

    def submit_target():
        states = WidgetStates()
        state = states.widgets.add()
        state.id = app.dataframe[0].proto.id
        state.string_value = json.dumps({
            "edited_rows": {"0": {"target_quantity": 200}},
            "added_rows": [],
            "deleted_rows": [],
        })
        app._run(states)
        assert not app.exception

    def fail(goals):
        raise save_error

    initial_editor = app.dataframe[0].proto.id
    with monkeypatch.context() as patch:
        patch.setattr(service._goal_repo, "upsert_accumulation_goals", fail)
        submit_target()
    assert service._goal_repo.list_accumulation_goals()[0]["target_quantity"] == 150
    assert app.dataframe[0].value.iloc[0]["target_quantity"] == 150
    assert app.dataframe[0].proto.id != initial_editor
    assert app.error[0].value == (
        str(save_error) if isinstance(save_error, ValueError)
        else "Não foi possível salvar a meta. Tente novamente."
    )
    assert app.session_state[detail_error_key] == "previous detail error"

    submit_target()
    assert not app.error
    assert service._goal_repo.list_accumulation_goals()[0]["target_quantity"] == 200
    assert app.dataframe[0].value.iloc[0]["target_quantity"] == 200
    assert detail_error_key not in app.session_state


def test_automatic_multi_row_save_is_atomic_on_database_failure(mock_db):
    service = build_service(
        [{"ticker": "BBAS3", "quantity": 100}, {"ticker": "SANB3", "quantity": 100}]
    )
    service.save_portfolio_goal_plan({"BBAS3": 150, "SANB3": 150})
    snapshot = service.get_portfolio_goal_plan()
    connection = service._goal_repo.get_personal_connection()
    connection.execute("""
        CREATE TRIGGER reject_second_goal BEFORE UPDATE ON asset_accumulation_goals
        WHEN NEW.ticker = 'SANB3'
        BEGIN SELECT RAISE(ABORT, 'test write failure'); END
    """)
    connection.commit()
    connection.close()
    with pytest.raises(sqlite3.IntegrityError, match="test write failure"):
        service.save_edited_goal_plan(snapshot, {"BBAS3": 200, "SANB3": 200})
    assert [goal["target_quantity"] for goal in service._goal_repo.list_accumulation_goals()] == [
        150,
        150,
    ]


@pytest.mark.parametrize(
    ("transaction_type", "event_quantity", "saved_target", "expected_target", "expected_baseline"),
    [("GROUP", 50, 151, 76, 50), ("BUY", 10, 151, 167, 110), ("BUY", 10, 100, 110, 110)],
)
def test_corporate_action_targets_remain_whole_and_allow_editing_other_assets(
    mock_db, transaction_type, event_quantity, saved_target, expected_target, expected_baseline
):
    repository = PlanningDAO()
    for ticker, target in [("BBAS3", saved_target), ("SANB3", 150)]:
        repository.upsert_accumulation_goal(
            ticker=ticker,
            start_quantity=100,
            target_quantity=target,
            target_mode=ShareQuantityGoalService.MODE_QUANTITY,
            target_percentage=None,
            allocation_weight=50,
            average_dividend_5y=2,
        )
    set_goal_created_at(repository, "2025-12-31")
    bought_quantity = 0 if saved_target == 100 else 25
    transactions = [
        {
            "date": "2026-02-01",
            "transaction_type": transaction_type,
            "quantity": event_quantity,
            "unit_price": 0,
            "fees": 0,
        }
    ]
    if bought_quantity:
        transactions.append(
            {
                "date": "2026-03-01",
                "transaction_type": "BUY",
                "quantity": bought_quantity,
                "unit_price": 10,
                "fees": 0,
            }
        )
    service = ShareQuantityGoalService(
        goal_repo=repository,
        portfolio_provider=StubPortfolioProvider(
            [
                {"ticker": "BBAS3", "quantity": expected_baseline + bought_quantity},
                {"ticker": "SANB3", "quantity": 100},
            ],
            year_start_quantities={"BBAS3": 100, "SANB3": 100},
            transactions={"BBAS3": transactions},
        ),
        market_analysis_api=StubMarketData,
        planning_provider=StubPlanningProvider(),
    )
    date = datetime.date(2026, 8, 28)
    plan = service.get_portfolio_goal_plan(today_date=date)
    assert plan["rows"].iloc[0]["target_quantity"] == expected_target
    targets = service.targets_from_editor_changes(
        plan["rows"], {"edited_rows": {"1": {"target_quantity": 160}}}
    )
    service.save_edited_goal_plan(plan, targets)
    assert repository.list_accumulation_goals()[1]["target_quantity"] == 160
    goal = service.list_goals_with_progress(date)[0]
    assert goal["target_quantity"] == expected_target
    expected_progress = (
        bought_quantity / (expected_target - expected_baseline) * 100
        if expected_target > expected_baseline
        else 100
    )
    assert goal["progress_percentage"] == pytest.approx(expected_progress)


@pytest.mark.parametrize("schema_version", [0, 1, 2])
@pytest.mark.parametrize("planning_provider", [EmptyPlanningProvider(), StubPlanningProvider()])
def test_legacy_modes_migrate_to_fixed_targets_consistent_across_views(
    tmp_path, schema_version, planning_provider
):
    manager = DatabaseManager(tmp_path / "legacy-modes.db")
    manager.init_personal_db()
    repository = PlanningDAO(manager)
    for ticker, mode, target, percentage, active in [
        ("BBAS3", "DIVIDEND_INCOME", 120, None, True),
        ("SANB3", "PERCENTAGE", 140, 20, True),
        ("TAEE11", "QUANTITY", 160, None, True),
        ("ITUB3", "DIVIDEND_INCOME", 180, None, False),
    ]:
        repository.upsert_accumulation_goal(ticker, 50, target, mode, percentage, 25, 2, active)
    connection = manager.get_personal_connection()
    connection.execute("UPDATE asset_accumulation_goals SET created_at = '2025-12-31 10:00:00'")
    connection.execute(f"PRAGMA user_version = {schema_version}")
    connection.commit()
    connection.close()
    before = repository.list_accumulation_goals()

    manager.init_personal_db()

    expected = [{**goal, "target_mode": "QUANTITY", "target_percentage": None} for goal in before]
    assert repository.list_accumulation_goals() == expected
    service = ShareQuantityGoalService(
        goal_repo=repository,
        portfolio_provider=StubPortfolioProvider(
            [{"ticker": ticker, "quantity": 110} for ticker in ["BBAS3", "SANB3", "TAEE11"]],
            year_start_quantities=dict.fromkeys(["BBAS3", "SANB3", "TAEE11"], 100),
        ),
        market_analysis_api=StubMarketData,
        planning_provider=planning_provider,
    )
    date = datetime.date(2026, 9, 28)
    plan = service.get_portfolio_goal_plan(today_date=date)
    planning_targets = dict(
        zip(plan["rows"][service.PLAN_TICKER], plan["rows"][service.PLAN_TARGET_QUANTITY])
    )
    dashboard = service.list_goals_with_progress(today_date=date)
    assert {goal["ticker"]: goal["target_quantity"] for goal in dashboard} == planning_targets
    assert planning_targets == {"BBAS3": 120, "SANB3": 140, "TAEE11": 160}
    assert [goal["progress_percentage"] for goal in dashboard] == pytest.approx([50, 25, 100 / 6])

    manager.init_personal_db()
    assert repository.list_accumulation_goals() == expected


@pytest.mark.parametrize("annual_baseline, expected_visible", [(200, True), (100, False)])
def test_closed_goal_visibility_uses_effective_annual_baseline(
    mock_db, annual_baseline, expected_visible
):
    repository = PlanningDAO()
    repository.upsert_accumulation_goal("SANB3", 100, 150, "QUANTITY", None, 100, 2)
    connection = repository.get_personal_connection()
    connection.execute("UPDATE asset_accumulation_goals SET created_at = '2025-07-01 10:00:00'")
    connection.commit()
    connection.close()
    portfolio = StubPortfolioProvider([], year_start_quantities={"SANB3": annual_baseline})
    service = ShareQuantityGoalService(
        goal_repo=repository,
        portfolio_provider=portfolio,
        market_analysis_api=StubMarketData,
        planning_provider=EmptyPlanningProvider(),
    )
    date = datetime.date(2027, 9, 28)
    plan = service.get_portfolio_goal_plan(today_date=date)
    dashboard = service.list_goals_with_progress(today_date=date)
    assert (not plan["rows"].empty) == expected_visible
    assert bool(dashboard) == expected_visible
    if expected_visible:
        row = plan["rows"].iloc[0]
        assert row[service.PLAN_YEAR_START_QUANTITY] == annual_baseline
        assert row[service.PLAN_CURRENT_QUANTITY] == 0
        assert row[service.PLAN_TARGET_QUANTITY] == 150
        assert dashboard[0]["progress_percentage"] == 400
    assert set(portfolio.quantity_queries) == {("SANB3", "2027-01-01")}


def test_closed_maintenance_goal_remains_visible_after_fractional_bonus(mock_db):
    repository = PlanningDAO()
    repository.upsert_accumulation_goal("SANB3", 100, 100, "QUANTITY", None, 0, 2)
    connection = repository.get_personal_connection()
    connection.execute("UPDATE asset_accumulation_goals SET created_at = '2025-12-31 10:00:00'")
    connection.commit()
    connection.close()
    portfolio = StubPortfolioProvider(
        [],
        year_start_quantities={"SANB3": 100},
        transactions={
            "SANB3": [
                {
                    "date": "2027-03-01",
                    "transaction_type": "BUY",
                    "quantity": 13,
                    "unit_price": 0,
                    "fees": 0,
                },
                {
                    "date": "2027-04-01",
                    "transaction_type": "SELL",
                    "quantity": 113,
                    "unit_price": 10,
                    "fees": 0,
                },
            ]
        },
    )
    service = ShareQuantityGoalService(
        goal_repo=repository,
        portfolio_provider=portfolio,
        market_analysis_api=StubMarketData,
        planning_provider=EmptyPlanningProvider(),
    )
    date = datetime.date(2027, 9, 28)
    plan = service.get_portfolio_goal_plan(today_date=date)
    assert plan["rows"].iloc[0][service.PLAN_TARGET_QUANTITY] == 113
    dashboard = service.list_goals_with_progress(today_date=date)
    assert dashboard[0]["target_quantity"] == 113
    assert dashboard[0]["progress_percentage"] == 0
