import datetime

import pandas as pd
import pytest

from core.planning import PlanningConfiguration, PlanningScenario, SimulationResult
from core.portfolio_read import PortfolioPlanning
from services.planning_service import SimulationService


@pytest.mark.parametrize("initial_equity", [0, 25000, 10000000])
@pytest.mark.parametrize("income_type", ["FIXED", "MULTIPLIER"])
def test_saved_and_sandbox_have_equivalent_financial_results(initial_equity, income_type):
    today = datetime.date.today()
    service = SimulationService.get_default()
    service.save_planning_configuration(
        PlanningConfiguration(
            birth_date=today,
            retirement_age=30,
            desired_income_mw=10,
            annual_interest_rate=6,
            mw_value=1000,
            initial_equity_input=initial_equity,
            desired_income_type=income_type,
            desired_income_fixed=10000,
            planning_start_date=today,
        )
    )
    saved = service.get_current_simulation()
    sandbox = service.simulate_scenario(PlanningScenario(30, 10000, 6, initial_equity))
    assert isinstance(saved, SimulationResult)
    assert isinstance(sandbox, SimulationResult)
    assert set(saved) == set(sandbox)
    for field in (
        "total_time_months",
        "remaining_time_months",
        "monthly_interest_rate",
        "target_equity",
        "required_monthly_contribution",
        "updated_monthly_contribution",
        "total_invested",
        "initial_equity_input",
    ):
        assert saved[field] == pytest.approx(sandbox[field])
    saved_charts = service.get_scenario_projection(saved)
    sandbox_charts = service.get_scenario_projection(sandbox)
    pd.testing.assert_frame_equal(saved_charts.cumulative, sandbox_charts.cumulative)
    pd.testing.assert_frame_equal(saved_charts.monthly, sandbox_charts.monthly)


def test_zero_interest_scenario_projections_keep_initial_capital():
    service = SimulationService()
    result = service.simulate_scenario(PlanningScenario(1, 10000, 0, 25000))
    assert result.required_monthly_contribution == 0
    assert result.target_equity == 0
    charts = service.get_scenario_projection(result)
    assert charts.cumulative["Patrimônio Projetado"].tolist() == [25000] * 13
    assert charts.monthly["Juros Mensal"].tolist() == [0] * 12


@pytest.mark.parametrize("duration", [0, -1])
def test_expired_scenario_has_zero_contribution_and_empty_projections(duration):
    service = SimulationService()
    result = service.simulate_scenario(PlanningScenario(duration, 10000, 6, 25000))
    assert result.required_monthly_contribution == 0
    assert result.updated_monthly_contribution == 0
    projection = service.get_scenario_projection(result)
    assert projection.cumulative.empty
    assert projection.monthly.empty


def test_sandbox_needs_no_repository_or_portfolio_and_preserves_due_payments():
    class Unavailable:
        def __getattr__(self, name):
            pytest.fail(f"Sandbox must not access {name}")

    service = SimulationService(Unavailable(), Unavailable())
    # A 1% monthly rate, FV=10000, PV=0, 12 advance payments:
    # Worked independently as FV / sum(1.01**month for month in 1..12).
    annual_rate = 12.682503013196978
    result = service.simulate_scenario(PlanningScenario(1, 100, annual_rate))
    assert result.target_equity == pytest.approx(10000)
    assert result.required_monthly_contribution == pytest.approx(780.6810760231852)
    projection = service.get_scenario_projection(result)
    assert projection.cumulative.iloc[-1]["Patrimônio Projetado"] == pytest.approx(10000)


@pytest.mark.parametrize("prior", [3500, None])
def test_prior_capital_uses_injected_provider_and_normalizes_dates(prior):
    requested = []

    class Provider:
        def read_planning(self, *, start_date):
            requested.append(start_date)
            return PortfolioPlanning(pd.DataFrame(), 0, prior, 0)

    service = SimulationService(portfolio_provider=Provider())
    assert service.get_prior_invested_capital(datetime.date(2024, 1, 1)) == prior
    assert requested == ["2024-01-01"]


def test_configuration_command_preserves_valuation_and_explicit_manual_zero():
    service = SimulationService.get_default()
    service.save_configuration(
        "1990-01-01",
        65,
        5,
        6,
        1500,
        25000,
        ceiling_model_selection="Bazin Ajustado",
        bazin_target_yield=8,
        bazin_target_spread=4,
    )
    service.save_planning_configuration(
        PlanningConfiguration(
            birth_date=datetime.date(1990, 1, 1),
            retirement_age=60,
            desired_income_mw=10,
            annual_interest_rate=7,
            mw_value=1500,
            initial_equity_input=0,
            planning_start_date=datetime.date(2024, 1, 1),
            initial_equity_manual_override=True,
        )
    )
    config = service.get_configuration()
    assert config["birth_date"] == "1990-01-01"
    assert config["planning_start_date"] == "2024-01-01"
    assert config["initial_equity_input"] == 0
    assert config["initial_equity_manual_override"] is True
    assert config["initial_equity_auto"] is False
    assert config["ceiling_model_selection"] == "Bazin Ajustado"
    assert config["bazin_target_yield"] == 8
    assert config["bazin_target_spread"] == 4


def test_saved_planning_reuses_cached_ledger_until_portfolio_mutation(monkeypatch):
    from core.daos.planning_dao import PlanningDAO
    from core.utils.market_data import MarketData
    from services.assets_service import AssetService
    from services.portfolio_read_service import PortfolioReadService
    from views.cached_market_data import StreamlitCachedPortfolioRepository

    cached = StreamlitCachedPortfolioRepository()
    StreamlitCachedPortfolioRepository._load_ledger.clear()
    loads = []
    original_load = cached._repository.load_ledger

    def load():
        loads.append(True)
        return original_load()

    monkeypatch.setattr(cached._repository, "load_ledger", load)
    portfolio = PortfolioReadService(cached, catalog=MarketData)
    service = SimulationService(PlanningDAO(), portfolio)
    service.save_planning_configuration(
        PlanningConfiguration(
            "1990-01-01",
            65,
            10,
            6,
            1500,
            planning_start_date="2024-01-01",
            initial_equity_auto=True,
        )
    )
    AssetService.add_transaction("BBAS3", "2023-01-01", "BUY", 10, 20)
    first = service.get_current_simulation()
    assert first.initial_equity_input == 200
    assert len(loads) == 1
    assert service.get_prior_invested_capital("2024-01-01") == 200
    assert service.get_current_simulation() == first
    assert len(loads) == 1
    AssetService.add_transaction("BBAS3", "2023-02-01", "BUY", 5, 20)
    updated = service.get_current_simulation()
    assert updated.initial_equity_input == 300
    assert len(loads) == 2
