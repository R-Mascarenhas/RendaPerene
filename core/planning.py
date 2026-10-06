"""Inputs and public results for retirement planning use cases."""

import datetime
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, fields

import pandas as pd


@dataclass(frozen=True)
class PlanningConfiguration:
    birth_date: datetime.date | str
    retirement_age: int
    desired_income_mw: float
    annual_interest_rate: float
    mw_value: float
    initial_equity_input: float = 0.0
    desired_income_type: str = "MULTIPLIER"
    desired_income_fixed: float = 10000.0
    planning_start_date: datetime.date | str | None = None
    initial_equity_auto: bool = False
    initial_equity_manual_override: bool = False


@dataclass(frozen=True)
class PlanningScenario:
    duration_years: int
    target_monthly_income: float
    annual_interest_rate: float
    initial_equity_input: float = 0.0


@dataclass(frozen=True)
class SimulationResult(Mapping):
    """Named metrics with mapping access for existing planning consumers."""

    current_age: float
    start_age_years: float
    total_time_months: int
    remaining_time_months: int
    target_monthly_income: float
    monthly_interest_rate: float
    target_equity: float
    required_monthly_contribution: float
    updated_monthly_contribution: float
    total_invested: float
    initial_equity_input: float
    annual_interest_rate: float
    mw_value: float = 0.0
    retirement_age: int = 0
    desired_income_mw: float = 0.0
    desired_income_fixed: float = 0.0
    desired_income_type: str = "FIXED"
    planning_start_date: str | None = None
    effective_planning_start_date: str | None = None

    def __getitem__(self, key):
        if key not in self:
            raise KeyError(key)
        return getattr(self, key)

    def __contains__(self, key):
        return key in (field.name for field in fields(self))

    def __iter__(self) -> Iterator[str]:
        return (field.name for field in fields(self))

    def __len__(self) -> int:
        return len(fields(self))


@dataclass(frozen=True)
class ScenarioProjection:
    cumulative: pd.DataFrame
    monthly: pd.DataFrame
