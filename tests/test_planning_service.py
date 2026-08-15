import pytest
import datetime
from services.assets_service import AssetService
from services.planning_service import SimulationService

def test_get_current_simulation_math():
    """Verifies that the core retirement simulation correctly loads DB config and runs the correct PMT math."""
    SimulationService.save_configuration(
        birth_date="1992-12-15",
        retirement_age=60,
        desired_income_mw=5.0,
        annual_interest_rate=6.0,
        mw_value=1412.0,
        initial_equity_input=0.0
    )
    AssetService.add_transaction("BBAS3", "2021-12-15", "BUY", 10, 10.00)
    sim = SimulationService.get_current_simulation()

    assert sim is not None
    assert sim["retirement_age"] == 60
    assert sim["desired_income_mw"] == 5.0
    assert sim["mw_value"] == 1412.0
    assert sim["target_monthly_income"] == 7060.0
    assert sim["required_monthly_contribution"] > 0.0
    assert sim["total_time_months"] > 0

def test_planning_custom_start_date(mock_db):
    """
    TDD Test to verify that when a planning_start_date is defined in the configuration,
    the simulation disregards transactions before that date for total_invested and start_age_years.
    """
    # 1. Seed two transactions: one before and one after the custom start date
    # BBAS3 buy before: 100 @ 30.00 on 2021-01-01 -> Invested: 3000
    AssetService.add_transaction("BBAS3", "2021-01-01", "BUY", 100, 30.00)
    # BBAS3 buy after: 50 @ 40.00 on 2024-05-15 -> Invested: 2000
    AssetService.add_transaction("BBAS3", "2024-05-15", "BUY", 50, 40.00)

    birth_date = datetime.date(1990, 1, 1)

    # 2. Case A: Default simulation (no custom planning_start_date, planning_start_date is None)
    # Should consider the earliest transaction: 2021-01-01.
    # Total invested should be 3000 + 2000 = 5000.
    SimulationService.save_configuration(
        birth_date=birth_date.strftime("%Y-%m-%d"),
        retirement_age=65,
        desired_income_mw=10.0,
        annual_interest_rate=6.0,
        mw_value=1412.00,
        initial_equity_input=0.0,
        desired_income_type="MULTIPLIER",
        desired_income_fixed=10000.0,
        planning_start_date=None
    )

    sim_default = SimulationService.get_current_simulation()
    assert sim_default is not None
    assert sim_default["total_invested"] == 5000.0
    # First investment age: from Jan 1990 to Jan 2021 is exactly 31 years (372 months)
    assert sim_default["start_age_years"] == 31.0

    # Assert historical evolution start month for default case (should be Jan 2021)
    df_ev_default = AssetService.calculate_historical_evolution()
    assert not df_ev_default.empty
    assert df_ev_default.sort_values("month_str").iloc[0]["month_str"] == "2021-01"

    # Assert get_monthly_contributions_by_year includes both years in default
    df_contribs_default = AssetService.get_monthly_contributions_by_year()
    assert "2021" in df_contribs_default["year"].values
    assert "2024" in df_contribs_default["year"].values

    # 3. Case B: Custom start date simulation (planning_start_date = "2024-01-01")
    # Should disregard the 2021 transaction.
    # Total invested should be only the 2024 transaction: 2000.0.
    SimulationService.save_configuration(
        birth_date=birth_date.strftime("%Y-%m-%d"),
        retirement_age=65,
        desired_income_mw=10.0,
        annual_interest_rate=6.0,
        mw_value=1412.00,
        initial_equity_input=0.0,
        desired_income_type="MULTIPLIER",
        desired_income_fixed=10000.0,
        planning_start_date="2024-01-01"
    )

    sim_custom = SimulationService.get_current_simulation()
    assert sim_custom is not None
    # total_invested represents transactions after start date (2000.0) + initial_equity_input (0.0) = 2000.0
    assert sim_custom["total_invested"] == 2000.0
    # First investment age with custom start date: Jan 1990 to Jan 2024 is exactly 34 years
    assert sim_custom["start_age_years"] == 34.0

    # Assert historical evolution start month for custom start date case (should be Jan 2024)
    df_ev_custom = AssetService.calculate_historical_evolution(start_date="2024-01-01")
    assert not df_ev_custom.empty
    assert df_ev_custom.sort_values("month_str").iloc[0]["month_str"] == "2024-01"

    # Assert get_monthly_contributions_by_year only includes 2024
    df_contribs_custom = AssetService.get_monthly_contributions_by_year(start_date="2024-01-01")
    assert "2021" not in df_contribs_custom["year"].values
    assert "2024" in df_contribs_custom["year"].values

def test_planning_initial_equity_integration(mock_db):
    """
    TDD Test to verify that when a planning_start_date is defined,
    the initial equity can be pre-populated from prior transactions and overridden manually.
    """
    birth_date = datetime.date(1990, 1, 1)

    # BBAS3 buy before: 100 @ 30.00 on 2021-01-01 -> Invested: 3000
    AssetService.add_transaction("BBAS3", "2021-01-01", "BUY", 100, 30.00)
    # BBAS3 buy after: 50 @ 40.00 on 2024-05-15 -> Invested: 2000
    AssetService.add_transaction("BBAS3", "2024-05-15", "BUY", 50, 40.00)

    # 1. Verify that calculate_prior_invested_amount works correctly standalone
    computed_prior = AssetService.calculate_prior_invested_amount("2024-01-01")
    assert computed_prior == 3000.0

    # 2. Save config with custom start date "2024-01-01" and the computed_prior (pre-population scenario)
    SimulationService.save_configuration(
        birth_date=birth_date.strftime("%Y-%m-%d"),
        retirement_age=65,
        desired_income_mw=10.0,
        annual_interest_rate=6.0,
        mw_value=1412.00,
        initial_equity_input=computed_prior,
        desired_income_type="MULTIPLIER",
        desired_income_fixed=10000.0,
        planning_start_date="2024-01-01"
    )

    sim = SimulationService.get_current_simulation()
    assert sim is not None
    assert sim["initial_equity_input"] == 3000.0
    assert sim["total_invested"] == 5000.0 # 2000 + 3000

    # 3. Save config with custom start date "2024-01-01" and a manual override (e.g., 10000.0)
    SimulationService.save_configuration(
        birth_date=birth_date.strftime("%Y-%m-%d"),
        retirement_age=65,
        desired_income_mw=10.0,
        annual_interest_rate=6.0,
        mw_value=1412.00,
        initial_equity_input=10000.0,
        desired_income_type="MULTIPLIER",
        desired_income_fixed=10000.0,
        planning_start_date="2024-01-01"
    )

    sim_override = SimulationService.get_current_simulation()
    assert sim_override is not None
    assert sim_override["initial_equity_input"] == 10000.0
    assert sim_override["total_invested"] == 12000.0 # 2000 + 10000

def test_projection_chart_does_not_override_zero_initial_equity(mock_db):
    """
    Verifies that when initial_equity_input is exactly 0.0, but total_invested is greater than 0.0,
    the projection and monthly cashflow dataframes are built using 0.0 and not overridden by total_invested.
    """
    # 1. Add some active holdings so that total_invested > 0
    AssetService.add_transaction("BBAS3", "2024-05-15", "BUY", 50, 40.00) # Invested: 2000.00

    # 2. Save configuration with planning start date, but initial_equity_input as 0.0
    SimulationService.save_configuration(
        birth_date="1990-01-01",
        retirement_age=65,
        desired_income_mw=10.0,
        annual_interest_rate=6.0,
        mw_value=1412.00,
        initial_equity_input=0.0,
        desired_income_type="MULTIPLIER",
        desired_income_fixed=10000.0,
        planning_start_date="2024-01-01"
    )

    sim = SimulationService.get_current_simulation()
    assert sim is not None
    assert sim["initial_equity_input"] == 0.0
    assert sim["total_invested"] == 2000.0 # 2000.0 from holdings + 0.0 initial_equity_input

    # 3. Test that build_projection_dataframe correctly uses 0.0 as initial_equity
    df_projection = SimulationService.build_projection_dataframe(
        sim["current_age"],
        sim["total_time_months"],
        sim["initial_equity_input"],
        sim["required_monthly_contribution"],
        sim["monthly_interest_rate"],
        sim["target_equity"]
    )

    assert not df_projection.empty
    first_month_invested = df_projection.iloc[0]["Valor Aportado Acumulado"]
    expected_first_month = 0.0 + sim["required_monthly_contribution"]
    assert abs(first_month_invested - expected_first_month) < 1e-5
