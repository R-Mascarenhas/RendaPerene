import datetime
import math
from decimal import ROUND_CEILING, Decimal

import pandas as pd

from core.constants import (
    CURRENT_PRICE,
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
    MarketAnalysisPort,
    PlanningProviderPort,
    PortfolioProviderPort,
    hybridmethod,
)


class ShareQuantityGoalService:
    """Calculates, persists, and evaluates the portfolio's investment goals."""

    MODE_DIVIDEND_INCOME = "DIVIDEND_INCOME"
    MODE_PERCENTAGE = "PERCENTAGE"
    MODE_QUANTITY = "QUANTITY"
    VALID_MODES = {MODE_DIVIDEND_INCOME, MODE_PERCENTAGE, MODE_QUANTITY}
    PLAN_TICKER = "ticker"
    PLAN_WEIGHT = "allocation_weight"
    PLAN_AVERAGE_DIVIDEND = "average_dividend_5y"
    PLAN_CURRENT_QUANTITY = "current_quantity"
    PLAN_YEAR_START_QUANTITY = "year_start_quantity"
    PLAN_TARGET_QUANTITY = "target_quantity"
    PLAN_GROWTH_PERCENTAGE = "target_growth_percentage"
    PLAN_HISTORY_NOTE = "dividend_history_note"
    PLAN_CURRENT_PRICE = "current_price"
    PLAN_ESTIMATED_COST = "estimated_cost"
    PLAN_REMAINING_COST = "remaining_estimated_cost"
    PLAN_PROJECTED_DIVIDENDS = "projected_annual_dividends"

    def __init__(
        self,
        goal_repo: AccumulationGoalPort = None,
        settings_repo: GoalSettingsPort = None,
        portfolio_provider: PortfolioProviderPort = None,
        market_analysis_api: MarketAnalysisPort = None,
        planning_provider: PlanningProviderPort = None,
    ):
        self._goal_repo = goal_repo or PlanningDAO()
        self._settings_repo = settings_repo or PlanningDAO()
        self._portfolio_provider = portfolio_provider
        self._market_analysis_api = market_analysis_api
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
        market_analysis_api: MarketAnalysisPort = None,
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
        if market_analysis_api is not None:
            instance._market_analysis_api = market_analysis_api
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
        """Returns a whole-share target for a percentage change from the baseline."""
        if start_quantity < 0:
            raise ValueError("A quantidade inicial não pode ser negativa.")
        if not math.isfinite(target_percentage) or target_percentage < -100:
            raise ValueError("O percentual desejado deve ser finito e no mínimo −100%.")
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
        if math.isclose(incremental_target, 0.0, rel_tol=0.0, abs_tol=1e-9):
            return 100.0 if math.isclose(current_quantity, start_quantity) else 0.0
        raw_progress = (current_quantity - start_quantity) / incremental_target * 100
        return max(0.0, raw_progress)

    @staticmethod
    def calculate_target_growth(start_quantity: float, target_quantity: float) -> float:
        """Returns the percentage change required from the annual baseline."""
        if start_quantity <= 0 or not math.isfinite(target_quantity):
            return math.nan
        return (target_quantity - start_quantity) / start_quantity * 100

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
        if total_weight > 0:
            return weighted_progress / total_weight
        finite_progress = [
            float(goal.get("progress_percentage", 0.0))
            for goal in goals
            if math.isfinite(float(goal.get("progress_percentage", 0.0)))
        ]
        return sum(finite_progress) / len(finite_progress) if finite_progress else 0.0

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
        return self._portfolio_provider.read_planning().positions

    def _get_goal_positions(self, today_date: datetime.date | None = None) -> pd.DataFrame:
        """Keep closed reductions visible using the effective baseline for the requested year."""
        positions = self._get_positions()
        held_tickers = set(positions[TICKER]) if not positions.empty else set()
        closed_goals = [
            goal
            for goal in self._goal_repo.list_accumulation_goals()
            if bool(goal.get("is_active", 1))
            and goal["target_mode"] in (self.MODE_QUANTITY, self.MODE_PERCENTAGE)
            and goal[TICKER] not in held_tickers
        ]
        baselines = self._get_year_start_quantities(
            [goal[TICKER] for goal in closed_goals], today_date
        )
        year_start_date = f"{(today_date or datetime.date.today()).year}-01-01"
        closed_positions = []
        for goal in closed_goals:
            baseline = baselines[goal[TICKER]]
            target = float(goal["target_quantity"])
            adjusted = self._get_corporate_action_adjusted_progress(
                {**goal, "start_quantity": baseline},
                year_start_date,
                str(goal.get("created_at", ""))[:10] or None,
            )
            if adjusted is not None:
                baseline, target, _ = adjusted
            if target <= baseline or math.isclose(target, baseline, rel_tol=0.0, abs_tol=1e-9):
                closed_positions.append({TICKER: goal[TICKER], QUANTITY: 0.0})
        if closed_positions:
            return pd.concat([positions, pd.DataFrame(closed_positions)], ignore_index=True)
        return positions

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
        quantities = self._portfolio_provider.read_planning(
            quantity_date=year_start_date
        ).quantities
        return {ticker: float(quantities.get(ticker, 0)) for ticker in tickers}

    @staticmethod
    def _is_corporate_action(transaction: pd.Series) -> bool:
        """Treat explicit corporate events and unprovenanced zero-cost buys as actions."""
        event_kind = transaction.get("event_kind")
        return pd.isna(event_kind) or event_kind == "CORPORATE"

    def _get_corporate_action_adjusted_progress(
        self, goal: dict, year_start_date: str, target_action_cutoff: str | None = None
    ) -> tuple[float, float, float] | None:
        """Calculates progress and goal quantities rebased through corporate actions."""
        transactions = self._portfolio_provider.read_planning().transactions.get(
            goal[TICKER], pd.DataFrame()
        )
        if transactions.empty:
            return None

        transactions = transactions.copy()
        transactions["_action_priority"] = transactions.apply(
            lambda row: (
                0
                if row[TRANSACTION_TYPE] == "GROUP"
                or (
                    row[TRANSACTION_TYPE] == "BUY"
                    and row.get("cost_status") != "PENDING"
                    and self._is_corporate_action(row)
                    and float(row[UNIT_PRICE]) <= 0
                )
                else 1
            ),
            axis=1,
        )
        transactions = transactions.sort_values([DATE, "_action_priority"], kind="stable")

        baseline = float(goal["start_quantity"])
        target = float(goal["target_quantity"])
        quantity_before_action = baseline
        adjusted_baseline = baseline
        adjusted_target = target
        adjusted_acquisition_delta = 0.0
        for _, transaction in transactions.iterrows():
            if str(transaction[DATE]) <= year_start_date:
                continue
            quantity = float(transaction[QUANTITY])
            transaction_type = transaction[TRANSACTION_TYPE]
            if transaction_type == "TRANSFER_IN":
                quantity_before_action += quantity
                continue
            if transaction_type == "BUY":
                unit_price = float(transaction[UNIT_PRICE])
                is_corporate_action = self._is_corporate_action(transaction)
                if (
                    transaction.get("cost_status") == "PENDING"
                    or (math.isfinite(unit_price) and unit_price > 0)
                    or not is_corporate_action
                ):
                    adjusted_acquisition_delta += quantity
                elif quantity_before_action > 0:
                    factor = (quantity_before_action + quantity) / quantity_before_action
                    adjusted_baseline *= factor
                    if (
                        target_action_cutoff is None
                        or str(transaction[DATE]) > target_action_cutoff
                    ):
                        adjusted_target *= factor
                    adjusted_acquisition_delta *= factor
                quantity_before_action += quantity
            elif transaction_type == "SELL":
                adjusted_acquisition_delta -= quantity
                quantity_before_action = max(0.0, quantity_before_action - quantity)
            elif transaction_type == "GROUP" and quantity_before_action > 0:
                factor = quantity / quantity_before_action
                adjusted_baseline *= factor
                if target_action_cutoff is None or str(transaction[DATE]) > target_action_cutoff:
                    adjusted_target *= factor
                adjusted_acquisition_delta *= factor
                quantity_before_action = quantity

        # Corporate actions can produce fractions or floating-point noise near whole shares.
        nearest_whole_target = round(adjusted_target)
        adjusted_target = float(
            nearest_whole_target
            if math.isclose(adjusted_target, nearest_whole_target, rel_tol=0.0, abs_tol=1e-9)
            else math.ceil(adjusted_target)
        )
        incremental_target = adjusted_target - adjusted_baseline
        if math.isclose(incremental_target, 0.0, rel_tol=0.0, abs_tol=1e-9):
            progress = 100.0 if math.isclose(adjusted_acquisition_delta, 0.0, abs_tol=1e-9) else 0.0
        else:
            progress = max(0.0, adjusted_acquisition_delta / incremental_target * 100)
        return adjusted_baseline, adjusted_target, progress

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

        market_analysis = self._market_analysis_api.get_ticker_market_analysis(normalized_ticker)
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
        if not math.isfinite(average_dividend) or average_dividend <= 0:
            if average_years > 0 and math.isfinite(average_dividend):
                return f"Sem proventos nos {average_years} ano(s) disponíveis."
            if average_years > 0:
                return "Dados de proventos indisponíveis; os proventos projetados são N/D."
            return "Sem histórico de proventos; os proventos projetados são N/D."
        if history_status == "partial" or average_years < 5:
            return (
                f"Histórico parcial: média calculada com {average_years} ano(s) desde a "
                "listagem; anos sem pagamento contam como zero."
            )
        return ""

    @staticmethod
    def _validate_targets(targets: dict[str, float], baselines: dict[str, float]) -> dict[str, int]:
        if set(targets) != set(baselines):
            raise ValueError("Informe uma meta de cotas para cada ativo em carteira.")
        validated = {}
        for ticker, raw_target in targets.items():
            try:
                target = float(raw_target)
            except (TypeError, ValueError) as error:
                raise ValueError(f"A meta de cotas de {ticker} é inválida.") from error
            if not math.isfinite(target) or target != math.ceil(target) or target < 0:
                raise ValueError(f"A meta de cotas de {ticker} deve ser inteira e não negativa.")
            validated[ticker] = int(target)
        return validated

    @classmethod
    def targets_from_edited_rows(
        cls, original_rows: pd.DataFrame, edited_rows: pd.DataFrame
    ) -> dict[str, float]:
        """Resolve share and growth edits against each row's January baseline."""
        if len(original_rows) != len(edited_rows):
            raise ValueError("A tabela de metas mudou; recarregue a página.")
        targets = {}
        baselines = {}
        for (_, original), (_, edited) in zip(
            original_rows.iterrows(), edited_rows.iterrows(), strict=True
        ):
            ticker = original[cls.PLAN_TICKER]
            baseline = float(original[cls.PLAN_YEAR_START_QUANTITY])
            target = edited[cls.PLAN_TARGET_QUANTITY]
            growth_input = edited[cls.PLAN_GROWTH_PERCENTAGE]
            try:
                growth = (
                    math.nan
                    if pd.isna(growth_input) or str(growth_input).strip().upper() == "N/D"
                    else float(str(growth_input).replace(",", "."))
                )
            except (TypeError, ValueError) as error:
                raise ValueError(f"O crescimento de {ticker} é inválido.") from error
            if target != original[cls.PLAN_TARGET_QUANTITY]:
                targets[ticker] = target
            elif baseline > 0 and (
                not math.isfinite(growth)
                or round(growth, 2) != round(float(original[cls.PLAN_GROWTH_PERCENTAGE]), 2)
            ):
                try:
                    targets[ticker] = cls.calculate_percentage_target(baseline, float(growth))
                except (TypeError, ValueError) as error:
                    raise ValueError(f"O crescimento de {ticker} é inválido.") from error
            elif baseline <= 0 and not pd.isna(growth):
                raise ValueError(f"O crescimento de {ticker} é N/D sem posição em 01/01.")
            else:
                targets[ticker] = original[cls.PLAN_TARGET_QUANTITY]
            baselines[ticker] = baseline
        return cls._validate_targets(targets, baselines)

    @classmethod
    def targets_from_editor_changes(
        cls, original_rows: pd.DataFrame, editing_state: dict
    ) -> dict[str, float]:
        """Resolve Streamlit cell deltas against the rows shown before the rerun."""
        edited_rows = original_rows.copy()
        editable_columns = {cls.PLAN_TARGET_QUANTITY, cls.PLAN_GROWTH_PERCENTAGE}
        for row_index, changes in editing_state.get("edited_rows", {}).items():
            try:
                index = int(row_index)
            except (TypeError, ValueError) as error:
                raise ValueError("A tabela de metas mudou; recarregue a página.") from error
            if index < 0 or index >= len(original_rows):
                raise ValueError("A tabela de metas mudou; recarregue a página.")
            for column, value in changes.items():
                if column in editable_columns:
                    # Text edits must retain PT-BR decimal separators until validation.
                    edited_rows[column] = edited_rows[column].astype(object)
                    edited_rows.iat[index, edited_rows.columns.get_loc(column)] = value
        return cls.targets_from_edited_rows(original_rows, edited_rows)

    @hybridmethod
    def get_portfolio_goal_plan(
        self,
        targets: dict[str, float] | None = None,
        today_date: datetime.date | None = None,
        ticker: str | None = None,
    ) -> dict:
        """Build an independent annual share target and financial estimate per asset."""
        positions = self._get_goal_positions(today_date)
        if ticker is not None and not positions.empty:
            positions = positions.loc[positions[TICKER] == ticker].copy()
        planned_dividends = (
            float(self._planning_provider.get_planned_annual_dividends())
            if self._planning_provider is not None
            else 0.0
        )
        simulation = (
            self._planning_provider.get_current_simulation()
            if self._planning_provider is not None
            and hasattr(self._planning_provider, "get_current_simulation")
            else None
        )
        monthly_contribution = (
            simulation.get("updated_monthly_contribution") if simulation else None
        )
        planned_external = (
            max(0.0, float(monthly_contribution) * 12)
            if monthly_contribution is not None and math.isfinite(float(monthly_contribution))
            else None
        )
        if positions.empty:
            return {
                "planned_annual_dividends": planned_dividends,
                "planned_external_contribution": planned_external,
                "total_estimated_cost": 0.0,
                "total_remaining_cost": 0.0,
                "projected_annual_dividends": 0.0,
                "estimated_external_contribution": 0.0,
                "exceeds_planned_resources": False,
                "rows": pd.DataFrame(),
            }

        positions = positions.sort_values(TICKER).reset_index(drop=True)
        tickers = positions[TICKER].tolist()
        baselines = self._get_year_start_quantities(tickers, today_date)
        stored_goals = {goal[TICKER]: goal for goal in self._goal_repo.list_accumulation_goals()}
        if targets is not None:
            targets = self._validate_targets(targets, dict.fromkeys(tickers, -1.0))
        reference_date = today_date or datetime.date.today()
        adjusted_baselines = {}
        rows = []
        for _, position in positions.iterrows():
            ticker = position[TICKER]
            baseline = baselines[ticker]
            current = float(position[QUANTITY])
            stored = stored_goals.get(ticker)
            target = (
                targets[ticker]
                if targets is not None
                else float(stored["target_quantity"])
                if stored is not None and bool(stored.get("is_active", 1))
                else math.ceil(max(baseline, current)) + 1
            )
            action_cutoff = (
                str(stored.get("created_at", ""))[:10] or None
                if targets is None and stored is not None and bool(stored.get("is_active", 1))
                else reference_date.isoformat()
            )
            action_result = self._get_corporate_action_adjusted_progress(
                {TICKER: ticker, "start_quantity": baseline, "target_quantity": target},
                f"{reference_date.year}-01-01",
                action_cutoff,
            )
            if action_result is not None:
                baseline, target, _ = action_result
            adjusted_baselines[ticker] = baseline
            analysis = self._market_analysis_api.get_ticker_market_analysis(ticker)
            price = float(analysis.get(CURRENT_PRICE, math.nan) or math.nan)
            if not math.isfinite(price) or price <= 0:
                price = math.nan
            average_dividend = float(analysis.get(MARKET_AVG_DIV_5Y, math.nan))
            if not math.isfinite(average_dividend) or average_dividend < 0:
                average_dividend = math.nan
            years = int(
                analysis.get(MARKET_DIVIDEND_AVERAGE_YEARS, 5 if average_dividend > 0 else 0)
            )
            status = analysis.get(
                MARKET_DIVIDEND_HISTORY_STATUS, "complete" if years == 5 else "unavailable"
            )
            if years == 0:
                average_dividend = math.nan
            note = self._dividend_history_note(average_dividend, years, status)
            if baseline <= 0:
                note = f"{note} Crescimento N/D: sem posição em 01/01.".strip()
            if math.isnan(price) and (target > baseline or target > current):
                note = f"{note} Cotação indisponível; custo estimado N/D.".strip()
            rows.append(
                {
                    self.PLAN_TICKER: ticker,
                    self.PLAN_YEAR_START_QUANTITY: baseline,
                    self.PLAN_CURRENT_QUANTITY: current,
                    self.PLAN_TARGET_QUANTITY: target,
                    self.PLAN_GROWTH_PERCENTAGE: self.calculate_target_growth(baseline, target),
                    self.PLAN_CURRENT_PRICE: price,
                    self.PLAN_AVERAGE_DIVIDEND: average_dividend,
                    self.PLAN_ESTIMATED_COST: (target - baseline) * price
                    if target > baseline
                    else 0.0,
                    self.PLAN_REMAINING_COST: (target - current) * price
                    if target > current
                    else 0.0,
                    self.PLAN_PROJECTED_DIVIDENDS: target * average_dividend if target > 0 else 0.0,
                    self.PLAN_HISTORY_NOTE: note,
                }
            )
        if targets is not None:
            self._validate_targets(targets, adjusted_baselines)
        frame = pd.DataFrame(rows)
        return self._summarize_goal_plan(frame, planned_dividends, planned_external)

    @classmethod
    def _summarize_goal_plan(
        cls, frame: pd.DataFrame, planned_dividends: float, planned_external: float | None
    ) -> dict:
        """Summarize already loaded estimates without consulting any adapters."""
        costs = frame[cls.PLAN_ESTIMATED_COST]
        complete_cost = bool(costs.notna().all())
        total_cost = float(costs.sum()) if complete_cost else None
        if complete_cost and total_cost > 0:
            frame[cls.PLAN_WEIGHT] = costs / total_cost * 100
        elif complete_cost:
            frame[cls.PLAN_WEIGHT] = 0.0
        else:
            frame[cls.PLAN_WEIGHT] = math.nan
        remaining_costs = frame[cls.PLAN_REMAINING_COST]
        total_remaining_cost = (
            float(remaining_costs.sum()) if remaining_costs.notna().all() else None
        )
        dividends = frame[cls.PLAN_PROJECTED_DIVIDENDS]
        projected_dividends = float(dividends.sum()) if dividends.notna().all() else None
        external = (
            max(0.0, total_cost - projected_dividends)
            if total_cost is not None and projected_dividends is not None
            else None
        )
        return {
            "planned_annual_dividends": planned_dividends,
            "planned_external_contribution": planned_external,
            "total_estimated_cost": total_cost,
            "total_remaining_cost": total_remaining_cost,
            "projected_annual_dividends": projected_dividends,
            "estimated_external_contribution": external,
            "exceeds_planned_resources": (
                external > planned_external
                if external is not None and planned_external is not None
                else False
            ),
            "rows": frame,
        }

    @classmethod
    def recalculate_goal_plan(cls, plan: dict, targets: dict[str, float]) -> dict:
        """Apply edits to the displayed snapshot without reloading portfolio or market data."""
        frame = plan["rows"].copy()
        baselines = dict(
            zip(frame[cls.PLAN_TICKER], frame[cls.PLAN_YEAR_START_QUANTITY], strict=True)
        )
        validated = cls._validate_targets(targets, baselines)
        frame[cls.PLAN_TARGET_QUANTITY] = frame[cls.PLAN_TICKER].map(validated)
        target = frame[cls.PLAN_TARGET_QUANTITY]
        baseline = frame[cls.PLAN_YEAR_START_QUANTITY]
        current = frame[cls.PLAN_CURRENT_QUANTITY]
        price = frame[cls.PLAN_CURRENT_PRICE]
        frame[cls.PLAN_GROWTH_PERCENTAGE] = [
            cls.calculate_target_growth(start, desired)
            for start, desired in zip(baseline, target, strict=True)
        ]
        frame[cls.PLAN_ESTIMATED_COST] = ((target - baseline) * price).where(target > baseline, 0.0)
        frame[cls.PLAN_REMAINING_COST] = ((target - current) * price).where(target > current, 0.0)
        frame[cls.PLAN_PROJECTED_DIVIDENDS] = (target * frame[cls.PLAN_AVERAGE_DIVIDEND]).where(
            target > 0, 0.0
        )
        quote_note = "Cotação indisponível; custo estimado N/D."
        frame[cls.PLAN_HISTORY_NOTE] = [
            (
                str(note).replace(quote_note, "").strip()
                + (
                    " " + quote_note
                    if not math.isfinite(quote) and (desired > start or desired > held)
                    else ""
                )
            ).strip()
            for note, quote, desired, start, held in zip(
                frame[cls.PLAN_HISTORY_NOTE], price, target, baseline, current, strict=True
            )
        ]
        return cls._summarize_goal_plan(
            frame, plan["planned_annual_dividends"], plan["planned_external_contribution"]
        )

    @hybridmethod
    def save_asset_goal(
        self, original_plan: dict, ticker: str, target_mode: str, target_value: float
    ) -> dict:
        """Save just one annual target using the displayed January baseline."""
        rows = original_plan["rows"]
        selected = rows.loc[rows[self.PLAN_TICKER] == ticker]
        if selected.empty:
            raise ValueError("Este ativo não está disponível para configurar uma meta.")
        baseline = float(selected.iloc[0][self.PLAN_YEAR_START_QUANTITY])
        if target_mode == self.MODE_PERCENTAGE:
            if baseline <= 0:
                raise ValueError("Informe a meta por cotas: não há posição em 01/01.")
            target = self.calculate_percentage_target(baseline, float(target_value))
        elif target_mode == self.MODE_QUANTITY:
            target = float(target_value)
        else:
            raise ValueError("O tipo de meta de acumulação é inválido.")
        targets = dict(zip(rows[self.PLAN_TICKER], rows[self.PLAN_TARGET_QUANTITY], strict=True))
        targets[ticker] = target
        updated = self.recalculate_goal_plan(original_plan, targets)
        self.save_prepared_goal_plan(updated, {ticker})
        return updated

    @hybridmethod
    def has_saved_goals(self) -> bool:
        """Whether any active target exists, independently of dashboard tracking."""
        return any(
            bool(goal.get("is_active", 1)) for goal in self._goal_repo.list_accumulation_goals()
        )

    @hybridmethod
    def save_edited_goal_plan(self, original_plan: dict, targets: dict[str, float]) -> dict:
        """Recalculate and persist only edited targets using the displayed snapshot."""
        updated_plan = self.recalculate_goal_plan(original_plan, targets)
        changed_tickers = {
            row[self.PLAN_TICKER]
            for _, row in original_plan["rows"].iterrows()
            if targets[row[self.PLAN_TICKER]] != row[self.PLAN_TARGET_QUANTITY]
        }
        if changed_tickers:
            self.save_prepared_goal_plan(updated_plan, changed_tickers)
        return updated_plan

    @hybridmethod
    def save_prepared_goal_plan(self, plan: dict, changed_tickers: set[str] | None = None) -> None:
        """Persist validated edits from a loaded plan without market or simulation work."""
        rows = plan["rows"]
        if rows.empty:
            raise ValueError("Adicione ativos à carteira antes de salvar as metas.")
        self._validate_targets(
            dict(zip(rows[self.PLAN_TICKER], rows[self.PLAN_TARGET_QUANTITY], strict=True)),
            dict(zip(rows[self.PLAN_TICKER], rows[self.PLAN_YEAR_START_QUANTITY], strict=True)),
        )
        goals = []
        for _, row in rows.iterrows():
            if changed_tickers is not None and row[self.PLAN_TICKER] not in changed_tickers:
                continue
            average = row[self.PLAN_AVERAGE_DIVIDEND]
            weight = row[self.PLAN_WEIGHT]
            goals.append(
                {
                    "ticker": row[self.PLAN_TICKER],
                    "start_quantity": float(row[self.PLAN_YEAR_START_QUANTITY]),
                    "target_quantity": float(row[self.PLAN_TARGET_QUANTITY]),
                    "target_mode": self.MODE_QUANTITY,
                    "target_percentage": None,
                    "allocation_weight": float(weight) if math.isfinite(weight) else 0.0,
                    "average_dividend_5y": float(average) if math.isfinite(average) else 0.0,
                    "is_active": True,
                }
            )
        self._goal_repo.upsert_accumulation_goals(goals)

    @hybridmethod
    def save_portfolio_goal_plan(
        self,
        targets: dict[str, float],
        today_date: datetime.date | None = None,
    ) -> list[dict]:
        """Validate and save share targets without using income allocation as a limit."""
        plan = self.get_portfolio_goal_plan(targets, today_date)
        self.save_prepared_goal_plan(plan)
        return self.list_goals_with_progress(today_date)

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
            raw_target = float(target_value)
            if not math.isfinite(raw_target) or raw_target < 0:
                raise ValueError("A quantidade-alvo deve ser finita e não negativa.")
            target_quantity = float(math.ceil(raw_target))

        if not math.isfinite(target_quantity) or target_quantity < 0:
            raise ValueError("A quantidade-alvo deve ser finita e não negativa.")

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
    def _build_progress(goal: dict, current_quantities: dict[str, float]) -> dict:
        current_quantity = current_quantities.get(goal[TICKER], 0.0)
        result = dict(goal)
        result["current_quantity"] = current_quantity
        result["progress_percentage"] = ShareQuantityGoalService.calculate_progress(
            goal["start_quantity"], current_quantity, goal["target_quantity"]
        )
        return result

    def _refresh_annual_progress_weights(self, goals: list[dict]) -> None:
        """Derive current annual effort weights without changing persisted goals."""
        quantity_goals = [
            goal
            for goal in goals
            if goal["target_mode"] in (self.MODE_QUANTITY, self.MODE_PERCENTAGE)
        ]
        costs = []
        for goal in quantity_goals:
            additional_quantity = max(0.0, goal["target_quantity"] - goal["start_quantity"])
            if additional_quantity == 0:
                costs.append(0.0)
                continue
            try:
                analysis = (
                    self._market_analysis_api.get_ticker_market_analysis(goal[TICKER])
                    if self._market_analysis_api is not None
                    else {}
                )
                price = float(analysis.get(CURRENT_PRICE, math.nan))
            except Exception:
                # Market availability must not hide transaction-based progress.
                price = math.nan
            costs.append(
                additional_quantity * price if math.isfinite(price) and price > 0 else math.nan
            )
        complete_quotes = all(math.isfinite(cost) for cost in costs)
        if not complete_quotes:
            costs = [
                1.0 if goal["target_quantity"] > goal["start_quantity"] else 0.0
                for goal in quantity_goals
            ]
        total_cost = sum(costs)
        for goal, cost in zip(quantity_goals, costs, strict=True):
            goal["allocation_weight"] = cost / total_cost * 100 if total_cost > 0 else 0.0
            goal["equal_progress_weights"] = not complete_quotes

    @hybridmethod
    def list_goals_with_progress(
        self, today_date: datetime.date | None = None, ticker: str | None = None
    ) -> list[dict]:
        """Combines stored baselines and targets with current portfolio quantities."""
        positions = self._get_goal_positions(today_date)
        held_tickers = set(positions[TICKER].tolist()) if not positions.empty else set()
        goals = [
            goal
            for goal in self._goal_repo.list_accumulation_goals()
            if bool(goal.get("is_active", 1))
            and (ticker is None or goal[TICKER] == ticker)
            and goal[TICKER] in held_tickers
            and (
                goal["target_mode"] != self.MODE_DIVIDEND_INCOME or goal["average_dividend_5y"] > 0
            )
        ]
        if not goals:
            return []
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
        results = []
        for stored_goal in goals:
            if (
                stored_goal["target_mode"] == self.MODE_DIVIDEND_INCOME
                and planned_annual_dividends <= 0
            ):
                continue
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
            elif (
                goal["target_mode"] == self.MODE_PERCENTAGE
                and goal.get("target_percentage") is not None
            ):
                goal["target_quantity"] = float(
                    self.calculate_percentage_target(
                        goal["start_quantity"], float(goal["target_percentage"])
                    )
                )
            corporate_action_result = self._get_corporate_action_adjusted_progress(
                goal,
                year_start_date,
                str(goal.get("created_at", ""))[:10] or None,
            )
            if corporate_action_result is not None:
                adjusted_baseline, adjusted_target, _ = corporate_action_result
                goal["start_quantity"] = adjusted_baseline
                goal["target_quantity"] = adjusted_target
            if (
                goal["target_mode"] == self.MODE_DIVIDEND_INCOME
                and goal["target_quantity"] <= goal["start_quantity"]
            ):
                current_quantity = current_quantities.get(goal[TICKER], 0.0)
                goal["current_quantity"] = current_quantity
                goal["progress_percentage"] = (
                    max(0.0, current_quantity / goal["target_quantity"] * 100)
                    if goal["target_quantity"] > 0
                    else 0.0
                )
                results.append(goal)
            elif math.isclose(
                goal["target_quantity"], goal["start_quantity"], rel_tol=0.0, abs_tol=1e-9
            ):
                results.append(self._build_progress(goal, current_quantities))
            elif corporate_action_result is not None:
                _, _, corporate_action_progress = corporate_action_result
                goal["current_quantity"] = current_quantities.get(goal[TICKER], 0.0)
                goal["progress_percentage"] = corporate_action_progress
                results.append(goal)
            else:
                results.append(self._build_progress(goal, current_quantities))
        self._refresh_annual_progress_weights(results)
        return results

    @hybridmethod
    def delete_goal(self, ticker: str) -> bool:
        """Deletes a ticker's accumulation goal."""
        return self._goal_repo.delete_accumulation_goal(ticker.strip().upper())
