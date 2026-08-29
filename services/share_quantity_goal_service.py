import datetime
import math
from decimal import ROUND_CEILING, Decimal

import pandas as pd

from core.constants import (
    DATE,
    GOAL_SHARE_QUANTITY,
    MARKET_AVG_DIV_5Y,
    MARKET_DIVIDEND_AVERAGE_YEARS,
    MARKET_DIVIDEND_HISTORY_STATUS,
    QUANTITY,
    TICKER,
    TRANSACTION_TYPE,
    UNIT_PRICE,
)
from core.daos.planning_dao import PlanningDAO
from core.ports import (
    AccumulationGoalPort,
    GoalSettingsPort,
    MarketDataPort,
    PlanningProviderPort,
    PortfolioProviderPort,
    hybridmethod,
)
from core.utils.market_data import MarketData


class ShareQuantityGoalService:
    """Calculates, persists, and evaluates the portfolio's investment goals."""

    MODE_DIVIDEND_INCOME = "DIVIDEND_INCOME"
    MODE_PERCENTAGE = "PERCENTAGE"
    MODE_QUANTITY = "QUANTITY"
    VALID_MODES = {MODE_DIVIDEND_INCOME, MODE_PERCENTAGE, MODE_QUANTITY}
    PLAN_TICKER = "ticker"
    PLAN_ACTIVE = "is_active"
    PLAN_WEIGHT = "allocation_weight"
    PLAN_AVERAGE_DIVIDEND = "average_dividend_5y"
    PLAN_ALLOCATED_DIVIDENDS = "allocated_annual_dividends"
    PLAN_CURRENT_QUANTITY = "current_quantity"
    PLAN_YEAR_START_QUANTITY = "year_start_quantity"
    PLAN_TARGET_QUANTITY = "target_quantity"
    PLAN_GROWTH_PERCENTAGE = "target_growth_percentage"
    PLAN_HISTORY_NOTE = "dividend_history_note"

    def __init__(
        self,
        goal_repo: AccumulationGoalPort = None,
        settings_repo: GoalSettingsPort = None,
        portfolio_provider: PortfolioProviderPort = None,
        market_data_api: MarketDataPort = None,
        planning_provider: PlanningProviderPort = None,
    ):
        self._goal_repo = goal_repo or PlanningDAO()
        self._settings_repo = settings_repo or PlanningDAO()
        self._portfolio_provider = portfolio_provider
        self._market_data_api = market_data_api or MarketData
        self._planning_provider = planning_provider

    _default_instance = None

    @classmethod
    def get_default(cls):
        if cls._default_instance is None:
            cls._default_instance = cls()
        return cls._default_instance

    @classmethod
    def set_adapters(
        cls,
        goal_repo: AccumulationGoalPort = None,
        settings_repo: GoalSettingsPort = None,
        portfolio_provider: PortfolioProviderPort = None,
        market_data_api: MarketDataPort = None,
        planning_provider: PlanningProviderPort = None,
    ):
        """Wires persistence, portfolio, market-data, and planning adapters."""
        instance = cls.get_default()
        if goal_repo is not None:
            instance._goal_repo = goal_repo
        if settings_repo is not None:
            instance._settings_repo = settings_repo
        if portfolio_provider is not None:
            instance._portfolio_provider = portfolio_provider
        if market_data_api is not None:
            instance._market_data_api = market_data_api
        if planning_provider is not None:
            instance._planning_provider = planning_provider

    @staticmethod
    def calculate_dividend_income_target(
        planned_annual_dividends: float,
        allocation_weight: float,
        average_dividend_5y: float,
    ) -> int:
        """Returns whole shares needed for the allocated annual dividend income."""
        if planned_annual_dividends <= 0:
            raise ValueError("O valor planejado de proventos no ano deve ser maior que zero.")
        if allocation_weight <= 0 or allocation_weight > 100:
            raise ValueError("O peso do ativo deve estar entre zero e 100%.")
        if average_dividend_5y <= 0:
            raise ValueError("Não há média positiva de proventos nos últimos 5 anos para o ativo.")
        allocated_income = planned_annual_dividends * allocation_weight / 100
        return math.ceil(allocated_income / average_dividend_5y)

    @staticmethod
    def calculate_percentage_target(start_quantity: float, target_percentage: float) -> int:
        """Returns a whole-share target for a percentage increase over the baseline."""
        if start_quantity < 0:
            raise ValueError("A quantidade inicial não pode ser negativa.")
        if target_percentage <= 0:
            raise ValueError("O percentual desejado deve ser maior que zero.")
        exact_target = Decimal(str(start_quantity)) * (
            Decimal("1") + Decimal(str(target_percentage)) / Decimal("100")
        )
        return int(exact_target.to_integral_value(rounding=ROUND_CEILING))

    @staticmethod
    def calculate_progress(
        start_quantity: float, current_quantity: float, target_quantity: float
    ) -> float:
        """Returns incremental progress from the frozen baseline without an upper limit."""
        incremental_target = target_quantity - start_quantity
        if incremental_target <= 0:
            raise ValueError("A quantidade-alvo deve ser maior que a quantidade inicial.")
        raw_progress = (current_quantity - start_quantity) / incremental_target * 100
        return max(0.0, raw_progress)

    @staticmethod
    def calculate_target_growth(start_quantity: float, target_quantity: float) -> float:
        """Returns the percentage increase required from the annual baseline."""
        if start_quantity <= 0 or not math.isfinite(target_quantity):
            return math.nan
        return max(0.0, (target_quantity - start_quantity) / start_quantity * 100)

    @staticmethod
    def calculate_weighted_progress(goals: list[dict]) -> float:
        """Returns portfolio goal progress weighted by each active allocation."""
        weighted_progress = 0.0
        total_weight = 0.0
        for goal in goals:
            weight = float(goal.get("allocation_weight", 0.0))
            progress = float(goal.get("progress_percentage", 0.0))
            if weight <= 0 or not math.isfinite(weight) or not math.isfinite(progress):
                continue
            weighted_progress += progress * weight
            total_weight += weight
        return weighted_progress / total_weight if total_weight > 0 else 0.0

    @hybridmethod
    def get_goal_enabled(self) -> bool:
        """Returns whether share-quantity goals are enabled for the portfolio."""
        return self._settings_repo.get_goal_settings()[GOAL_SHARE_QUANTITY]

    @hybridmethod
    def set_goal_enabled(self, enabled: bool) -> None:
        """Enables or hides share-quantity goals without deleting them."""
        self._settings_repo.set_goal_enabled(GOAL_SHARE_QUANTITY, enabled)

    def _get_positions(self) -> pd.DataFrame:
        if self._portfolio_provider is None:
            raise RuntimeError(
                "O provedor da carteira não está configurado para metas de acumulação."
            )
        return self._portfolio_provider.calculate_positions()

    def _get_position(self, ticker: str) -> tuple[pd.DataFrame, float]:
        positions = self._get_positions()
        normalized_ticker = ticker.strip().upper()
        if positions.empty or normalized_ticker not in positions[TICKER].values:
            raise ValueError("Somente ativos atualmente em carteira podem receber uma meta.")
        current_quantity = float(
            positions.loc[positions[TICKER] == normalized_ticker, QUANTITY].iloc[0]
        )
        return positions, current_quantity

    def _get_year_start_quantities(
        self, tickers: list[str], today_date: datetime.date | None = None
    ) -> dict[str, float]:
        """Returns quantities held on January 1 of the current year."""
        reference_date = today_date or datetime.date.today()
        year_start_date = f"{reference_date.year}-01-01"
        return {
            ticker: float(self._portfolio_provider.get_quantity_on_date(ticker, year_start_date))
            for ticker in tickers
        }

    def _get_qualifying_accumulation_quantities(
        self, tickers: list[str], year_start_date: str
    ) -> dict[str, float]:
        """Returns net paid acquisitions since January 1, excluding corporate actions."""
        quantities = {}
        for ticker in tickers:
            transactions = self._portfolio_provider.get_raw_transactions_for_chart(ticker)
            if transactions.empty:
                continue
            net_quantity = 0.0
            for _, transaction in transactions.iterrows():
                if str(transaction[DATE]) <= year_start_date:
                    continue
                quantity = float(transaction[QUANTITY])
                transaction_type = transaction[TRANSACTION_TYPE]
                if transaction_type == "BUY" and float(transaction[UNIT_PRICE]) > 0:
                    net_quantity += quantity
                elif transaction_type == "SELL":
                    net_quantity -= quantity
            quantities[ticker] = net_quantity
        return quantities

    @hybridmethod
    def list_available_tickers(self) -> list[str]:
        """Returns currently held tickers that can receive an accumulation goal."""
        positions = self._get_positions()
        return sorted(positions[TICKER].tolist()) if not positions.empty else []

    @hybridmethod
    def get_goal_suggestion(self, ticker: str, allocation_weight: float | None = None) -> dict:
        """Builds the annual dividend-income suggestion for a held ticker."""
        normalized_ticker = ticker.strip().upper()
        positions, current_quantity = self._get_position(normalized_ticker)
        if self._planning_provider is None:
            raise RuntimeError("O provedor de planejamento não está configurado para as metas.")

        market_analysis = self._market_data_api.get_ticker_market_analysis(normalized_ticker)
        average_dividend_5y = float(market_analysis.get(MARKET_AVG_DIV_5Y, 0.0) or 0.0)
        average_years = int(
            market_analysis.get(MARKET_DIVIDEND_AVERAGE_YEARS, 5 if average_dividend_5y > 0 else 0)
        )
        history_status = market_analysis.get(
            MARKET_DIVIDEND_HISTORY_STATUS,
            "complete" if average_years == 5 else "unavailable",
        )
        equal_allocation_weight = 100 / len(positions)
        stored_goal = next(
            (
                goal
                for goal in self._goal_repo.list_accumulation_goals()
                if goal[TICKER] == normalized_ticker
            ),
            None,
        )
        if allocation_weight is None:
            allocation_weight = (
                float(stored_goal["allocation_weight"])
                if stored_goal is not None
                else equal_allocation_weight
            )
        if allocation_weight <= 0 or allocation_weight > 100:
            raise ValueError("O peso do ativo deve estar entre zero e 100%.")

        planned_annual_dividends = float(self._planning_provider.get_planned_annual_dividends())
        suggested_target = None
        if planned_annual_dividends > 0 and average_dividend_5y > 0:
            suggested_target = self.calculate_dividend_income_target(
                planned_annual_dividends, allocation_weight, average_dividend_5y
            )
        return {
            TICKER: normalized_ticker,
            "current_quantity": current_quantity,
            "allocation_weight": allocation_weight,
            "equal_allocation_weight": equal_allocation_weight,
            MARKET_AVG_DIV_5Y: average_dividend_5y,
            "planned_annual_dividends": planned_annual_dividends,
            "allocated_annual_dividends": planned_annual_dividends * allocation_weight / 100,
            "suggested_target_quantity": suggested_target,
            MARKET_DIVIDEND_AVERAGE_YEARS: average_years,
            MARKET_DIVIDEND_HISTORY_STATUS: history_status,
            self.PLAN_HISTORY_NOTE: self._dividend_history_note(
                average_dividend_5y, average_years, history_status
            ),
        }

    @staticmethod
    def _dividend_history_note(
        average_dividend: float, average_years: int, history_status: str
    ) -> str:
        """Explains partial or unavailable dividend history to the user."""
        if average_dividend <= 0:
            if average_years > 0:
                return (
                    f"Sem proventos nos {average_years} ano(s) disponíveis; "
                    "a meta de cotas não pôde ser calculada."
                )
            return "Sem histórico de proventos; a meta de cotas não pôde ser calculada."
        if history_status == "partial" or average_years < 5:
            return (
                f"Histórico parcial: média calculada com {average_years} ano(s) desde a "
                "listagem; anos sem pagamento contam como zero."
            )
        return ""

    @staticmethod
    def validate_allocation_weights(
        allocation_weights: dict[str, float],
        expected_tickers: set[str],
    ) -> dict[str, float]:
        """Normalizes weights and requires active allocations to total 100%."""
        normalized_weights = {
            ticker.strip().upper(): float(weight) for ticker, weight in allocation_weights.items()
        }
        if set(normalized_weights) != expected_tickers:
            raise ValueError("Informe um peso para cada ativo atualmente em carteira.")
        if any(
            not math.isfinite(weight) or weight < 0 or weight > 100
            for weight in normalized_weights.values()
        ):
            raise ValueError("Cada peso deve estar entre zero e 100%.")
        active_weight = sum(weight for weight in normalized_weights.values() if weight > 0)
        if active_weight and abs(active_weight - 100) > 0.01:
            raise ValueError("A soma dos pesos das metas ativas deve ser igual a 100%.")
        return normalized_weights

    @classmethod
    def allocation_weights_from_dataframe(cls, plan_rows: pd.DataFrame) -> dict[str, float]:
        """Extracts the editable allocation values returned by the presentation table."""
        required_columns = {cls.PLAN_TICKER, cls.PLAN_WEIGHT}
        if plan_rows.empty or not required_columns.issubset(plan_rows.columns):
            return {}
        weights = {}
        for _, row in plan_rows.iterrows():
            ticker = str(row[cls.PLAN_TICKER]).strip().upper()
            try:
                weights[ticker] = float(row[cls.PLAN_WEIGHT])
            except (TypeError, ValueError):
                weights[ticker] = math.nan
        return weights

    @hybridmethod
    def get_portfolio_goal_plan(
        self,
        allocation_weights: dict[str, float] | None = None,
        today_date: datetime.date | None = None,
    ) -> dict:
        """Builds the annual accumulation plan for all currently held assets."""
        positions = self._get_positions()
        planned_annual_dividends = (
            float(self._planning_provider.get_planned_annual_dividends())
            if self._planning_provider is not None
            else 0.0
        )
        if positions.empty:
            return {
                "planned_annual_dividends": planned_annual_dividends,
                "allocation_weights": {},
                "active_tickers": set(),
                "rows": pd.DataFrame(),
            }

        positions = positions.sort_values(TICKER).reset_index(drop=True)
        tickers = positions[TICKER].tolist()
        year_start_quantities = self._get_year_start_quantities(tickers, today_date)
        expected_tickers = set(tickers)
        equal_weight = 100 / len(tickers)
        stored_goals = {goal[TICKER]: goal for goal in self._goal_repo.list_accumulation_goals()}
        stored_weights = {
            ticker: (
                float(stored_goals[ticker]["allocation_weight"])
                if bool(stored_goals[ticker].get("is_active", 1))
                else 0.0
            )
            for ticker in tickers
            if ticker in stored_goals
        }
        stored_active_tickers = {
            ticker
            for ticker in tickers
            if ticker in stored_goals and bool(stored_goals[ticker].get("is_active", 1))
        }
        stored_active_weight = sum(stored_weights[ticker] for ticker in stored_active_tickers)
        stored_weights_are_complete = set(stored_weights) == expected_tickers and (
            not stored_active_tickers or abs(stored_active_weight - 100) <= 0.01
        )

        if allocation_weights is not None:
            weights = {
                ticker.strip().upper(): float(weight)
                for ticker, weight in allocation_weights.items()
                if ticker.strip().upper() in expected_tickers
            }
            for ticker in tickers:
                weights.setdefault(ticker, equal_weight)
            selected_active_tickers = {ticker for ticker, weight in weights.items() if weight > 0}
        elif stored_weights_are_complete:
            weights = stored_weights
            selected_active_tickers = stored_active_tickers
        else:
            weights = dict.fromkeys(tickers, equal_weight)
            selected_active_tickers = expected_tickers

        rows = []
        for _, position in positions.iterrows():
            ticker = position[TICKER]
            weight = weights[ticker]
            is_active = ticker in selected_active_tickers and weight > 0
            weight_is_valid = math.isfinite(weight) and 0 <= weight <= 100
            market_analysis = self._market_data_api.get_ticker_market_analysis(ticker)
            average_dividend_5y = float(market_analysis.get(MARKET_AVG_DIV_5Y, 0.0) or 0.0)
            average_years = int(
                market_analysis.get(
                    MARKET_DIVIDEND_AVERAGE_YEARS, 5 if average_dividend_5y > 0 else 0
                )
            )
            history_status = market_analysis.get(
                MARKET_DIVIDEND_HISTORY_STATUS,
                "complete" if average_years == 5 else "unavailable",
            )
            allocated_dividends = (
                planned_annual_dividends * weight / 100 if weight_is_valid and is_active else 0.0
            )
            if (
                planned_annual_dividends > 0
                and average_dividend_5y > 0
                and weight_is_valid
                and is_active
            ):
                target_quantity = self.calculate_dividend_income_target(
                    planned_annual_dividends,
                    weight,
                    average_dividend_5y,
                )
            elif is_active:
                target_quantity = math.nan
            else:
                target_quantity = float(position[QUANTITY])
            history_note = self._dividend_history_note(
                average_dividend_5y, average_years, history_status
            )
            if is_active and planned_annual_dividends <= 0:
                history_note = "Configure os proventos planejados no ano para calcular a meta."
            year_start_quantity = year_start_quantities[ticker]
            target_growth_percentage = (
                self.calculate_target_growth(year_start_quantity, target_quantity)
                if is_active
                else 0.0
            )
            if is_active and year_start_quantity <= 0 and math.isfinite(target_quantity):
                growth_note = (
                    "Sem posição em 01/01; o crescimento percentual não pode ser calculado."
                )
                history_note = f"{history_note} {growth_note}" if history_note else growth_note
            rows.append(
                {
                    self.PLAN_TICKER: ticker,
                    self.PLAN_ACTIVE: is_active,
                    self.PLAN_WEIGHT: weight,
                    self.PLAN_AVERAGE_DIVIDEND: average_dividend_5y,
                    self.PLAN_ALLOCATED_DIVIDENDS: allocated_dividends,
                    self.PLAN_YEAR_START_QUANTITY: year_start_quantity,
                    self.PLAN_CURRENT_QUANTITY: float(position[QUANTITY]),
                    self.PLAN_TARGET_QUANTITY: target_quantity,
                    self.PLAN_GROWTH_PERCENTAGE: target_growth_percentage,
                    self.PLAN_HISTORY_NOTE: history_note,
                }
            )

        return {
            "planned_annual_dividends": planned_annual_dividends,
            "allocation_weights": weights,
            "active_tickers": selected_active_tickers,
            "rows": pd.DataFrame(rows),
        }

    @hybridmethod
    def save_portfolio_goal_plan(
        self,
        allocation_weights: dict[str, float],
        today_date: datetime.date | None = None,
    ) -> list[dict]:
        """Validates and persists annual dividend-income goals for every held asset."""
        positions = self._get_positions()
        if positions.empty:
            raise ValueError("Adicione ativos à carteira antes de salvar as metas.")
        expected_tickers = set(positions[TICKER].tolist())
        normalized_weights = self.validate_allocation_weights(allocation_weights, expected_tickers)
        plan = self.get_portfolio_goal_plan(normalized_weights, today_date)

        for _, row in plan["rows"].iterrows():
            ticker = row[self.PLAN_TICKER]
            start_quantity = float(row[self.PLAN_YEAR_START_QUANTITY])
            calculated_target = float(row[self.PLAN_TARGET_QUANTITY])
            persistence_target = (
                max(calculated_target, start_quantity + 1)
                if math.isfinite(calculated_target)
                else start_quantity + 1
            )
            is_active = bool(row[self.PLAN_ACTIVE]) and math.isfinite(calculated_target)
            self._goal_repo.upsert_accumulation_goal(
                ticker=ticker,
                start_quantity=start_quantity,
                target_quantity=persistence_target,
                target_mode=self.MODE_DIVIDEND_INCOME,
                target_percentage=None,
                allocation_weight=float(row[self.PLAN_WEIGHT]),
                average_dividend_5y=float(row[self.PLAN_AVERAGE_DIVIDEND]),
                is_active=is_active,
            )
        return self.list_goals_with_progress()

    @hybridmethod
    def create_goal(
        self,
        ticker: str,
        target_mode: str,
        target_value: float | None = None,
        allocation_weight: float | None = None,
    ) -> dict:
        """Persists a new goal while freezing the ticker's current quantity as baseline."""
        if target_mode not in self.VALID_MODES:
            raise ValueError("O tipo de meta de acumulação é inválido.")

        suggestion = self.get_goal_suggestion(ticker, allocation_weight)
        start_quantity = suggestion["current_quantity"]
        target_percentage = None
        target_available = True
        if target_mode == self.MODE_DIVIDEND_INCOME:
            if suggestion["suggested_target_quantity"] is None:
                target_quantity = start_quantity + 1
                target_available = False
            else:
                target_quantity = float(suggestion["suggested_target_quantity"])
        elif target_mode == self.MODE_PERCENTAGE:
            if target_value is None:
                raise ValueError("Informe o percentual desejado para esta meta.")
            target_percentage = float(target_value)
            target_quantity = float(
                self.calculate_percentage_target(start_quantity, target_percentage)
            )
        else:
            if target_value is None:
                raise ValueError("Informe a quantidade-alvo para esta meta.")
            target_quantity = float(math.ceil(float(target_value)))

        if not math.isfinite(target_quantity) or target_quantity <= start_quantity:
            raise ValueError("A quantidade-alvo deve ser maior que a quantidade atual.")

        self._goal_repo.upsert_accumulation_goal(
            ticker=suggestion[TICKER],
            start_quantity=start_quantity,
            target_quantity=target_quantity,
            target_mode=target_mode,
            target_percentage=target_percentage,
            allocation_weight=suggestion["allocation_weight"],
            average_dividend_5y=suggestion[MARKET_AVG_DIV_5Y],
            is_active=target_available,
        )
        stored_goal = next(
            goal
            for goal in self._goal_repo.list_accumulation_goals()
            if goal[TICKER] == suggestion[TICKER]
        )
        result = self._build_progress(stored_goal, {suggestion[TICKER]: start_quantity})
        result["target_available"] = target_available
        result[self.PLAN_HISTORY_NOTE] = suggestion[self.PLAN_HISTORY_NOTE]
        return result

    @staticmethod
    def _build_progress(
        goal: dict,
        current_quantities: dict[str, float],
        progress_quantities: dict[str, float] | None = None,
    ) -> dict:
        current_quantity = current_quantities.get(goal[TICKER], 0.0)
        if progress_quantities is None or goal[TICKER] not in progress_quantities:
            progress_quantity = current_quantity
        else:
            progress_quantity = goal["start_quantity"] + progress_quantities[goal[TICKER]]
        result = dict(goal)
        result["current_quantity"] = current_quantity
        result["progress_percentage"] = ShareQuantityGoalService.calculate_progress(
            goal["start_quantity"], progress_quantity, goal["target_quantity"]
        )
        return result

    @hybridmethod
    def list_goals_with_progress(self, today_date: datetime.date | None = None) -> list[dict]:
        """Combines stored baselines and targets with current portfolio quantities."""
        goals = [
            goal
            for goal in self._goal_repo.list_accumulation_goals()
            if bool(goal.get("is_active", 1))
            and (
                goal["target_mode"] != self.MODE_DIVIDEND_INCOME or goal["average_dividend_5y"] > 0
            )
        ]
        if not goals:
            return []
        positions = self._get_positions()
        current_quantities = (
            dict(zip(positions[TICKER], positions[QUANTITY], strict=False))
            if not positions.empty
            else {}
        )
        planned_annual_dividends = (
            float(self._planning_provider.get_planned_annual_dividends())
            if self._planning_provider is not None
            else 0.0
        )
        year_start_quantities = self._get_year_start_quantities(
            [goal[TICKER] for goal in goals], today_date
        )
        reference_date = today_date or datetime.date.today()
        year_start_date = f"{reference_date.year}-01-01"
        progress_quantities = self._get_qualifying_accumulation_quantities(
            [goal[TICKER] for goal in goals], year_start_date
        )
        results = []
        for stored_goal in goals:
            goal = dict(stored_goal)
            goal["start_quantity"] = year_start_quantities[goal[TICKER]]
            if (
                goal["target_mode"] == self.MODE_DIVIDEND_INCOME
                and planned_annual_dividends > 0
                and goal["average_dividend_5y"] > 0
            ):
                goal["target_quantity"] = float(
                    self.calculate_dividend_income_target(
                        planned_annual_dividends,
                        goal["allocation_weight"],
                        goal["average_dividend_5y"],
                    )
                )
            if goal["target_quantity"] <= goal["start_quantity"]:
                current_quantity = current_quantities.get(goal[TICKER], 0.0)
                goal["current_quantity"] = current_quantity
                goal["progress_percentage"] = (
                    100.0 if current_quantity >= goal["target_quantity"] else 0.0
                )
                results.append(goal)
            else:
                results.append(self._build_progress(goal, current_quantities, progress_quantities))
        return results

    @hybridmethod
    def delete_goal(self, ticker: str) -> bool:
        """Deletes a ticker's accumulation goal."""
        return self._goal_repo.delete_accumulation_goal(ticker.strip().upper())
