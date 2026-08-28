from core.constants import GOAL_REINVEST_DIVIDENDS
from core.daos.planning_dao import PlanningDAO
from core.ports import (
    GoalSettingsPort,
    PlanningProviderPort,
    PortfolioProviderPort,
    hybridmethod,
)


class GoalService:
    """Calculates and configures portfolio-wide investment goals."""

    def __init__(
        self,
        settings_repo: GoalSettingsPort = None,
        portfolio_provider: PortfolioProviderPort = None,
        planning_provider: PlanningProviderPort = None,
    ):
        self._settings_repo = settings_repo or PlanningDAO()
        self._portfolio_provider = portfolio_provider
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
        settings_repo: GoalSettingsPort = None,
        portfolio_provider: PortfolioProviderPort = None,
        planning_provider: PlanningProviderPort = None,
    ) -> None:
        """Wires persistence, portfolio, and planning adapters."""
        instance = cls.get_default()
        if settings_repo is not None:
            instance._settings_repo = settings_repo
        if portfolio_provider is not None:
            instance._portfolio_provider = portfolio_provider
        if planning_provider is not None:
            instance._planning_provider = planning_provider

    @hybridmethod
    def get_reinvestment_goal_enabled(self) -> bool:
        """Returns whether dividend reinvestment is included on the Dashboard."""
        return self._settings_repo.get_goal_settings()[GOAL_REINVEST_DIVIDENDS]

    @hybridmethod
    def set_reinvestment_goal_enabled(self, enabled: bool) -> None:
        """Enables or hides dividend reinvestment for this portfolio."""
        self._settings_repo.set_goal_enabled(GOAL_REINVEST_DIVIDENDS, enabled)

    @hybridmethod
    def get_annual_investment_goal(
        self, current_year: int, ytd_dividends: float
    ) -> dict[str, float | bool]:
        """Returns annual contribution and optional dividend-reinvestment progress."""
        if self._portfolio_provider is None or self._planning_provider is None:
            raise RuntimeError("Os provedores das metas anuais não estão configurados.")

        reinvestment_enabled = self.get_reinvestment_goal_enabled()
        annual_salary_goal = max(
            0.0, float(self._planning_provider.get_updated_required_contribution()) * 12
        )
        reinvestment_goal = max(0.0, float(ytd_dividends)) if reinvestment_enabled else 0.0
        total_goal = annual_salary_goal + reinvestment_goal
        ytd_contributions = max(
            0.0, float(self._portfolio_provider.get_ytd_contributions(current_year))
        )
        progress_percentage = ytd_contributions / total_goal * 100 if total_goal > 0 else 0.0
        return {
            "reinvestment_enabled": reinvestment_enabled,
            "annual_salary_goal": annual_salary_goal,
            "reinvestment_goal": reinvestment_goal,
            "total_goal": total_goal,
            "ytd_contributions": ytd_contributions,
            "remaining_to_invest": max(0.0, total_goal - ytd_contributions),
            "progress_percentage": progress_percentage,
        }
