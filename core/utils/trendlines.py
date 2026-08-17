from typing import Protocol

import numpy as np
import pandas as pd


class TrendlineStrategy(Protocol):
    """Protocol defining the trendline projection calculation contract (LSP compliant)."""

    def calculate(self, df: pd.DataFrame, y_col: str, extrapolate_periods: int) -> list: ...


class PolynomialTrendlineStrategy:
    """Fits a 2nd degree (or higher) polynomial curve to the series, projecting it."""

    def __init__(self, deg: int = 2):
        self.deg = deg

    def calculate(self, df: pd.DataFrame, y_col: str, extrapolate_periods: int) -> list:
        df_clean = df.dropna(subset=[y_col])
        if df_clean.empty or len(df_clean) < self.deg + 1:
            total_len = len(df_clean) + extrapolate_periods
            return [0.0] * total_len if total_len > 0 else []

        x_idx = np.arange(len(df_clean))
        y_vals = df_clean[y_col].values
        coefs = np.polyfit(x_idx, y_vals, deg=self.deg)

        total_len = len(df_clean) + extrapolate_periods
        x_total = np.arange(total_len)
        trend = np.polyval(coefs, x_total)
        return [max(0.0, float(v)) for v in trend]


class LinearTrendlineStrategy:
    """Fits a 1st degree linear regression line (y = mx + b) and projects it."""

    def calculate(self, df: pd.DataFrame, y_col: str, extrapolate_periods: int) -> list:
        df_clean = df.dropna(subset=[y_col])
        if df_clean.empty or len(df_clean) < 2:
            total_len = len(df_clean) + extrapolate_periods
            return [0.0] * total_len if total_len > 0 else []

        x_idx = np.arange(len(df_clean))
        y_vals = df_clean[y_col].values
        coefs = np.polyfit(x_idx, y_vals, deg=1)

        total_len = len(df_clean) + extrapolate_periods
        x_total = np.arange(total_len)
        trend = np.polyval(coefs, x_total)
        return [max(0.0, float(v)) for v in trend]


class MovingAverageTrendlineStrategy:
    """Calculates rolling moving average, and forward-fills it constantly into the future."""

    def __init__(self, window: int = 3):
        self.window = window

    def calculate(self, df: pd.DataFrame, y_col: str, extrapolate_periods: int) -> list:
        df_clean = df.dropna(subset=[y_col])
        if df_clean.empty:
            total_len = extrapolate_periods
            return [0.0] * total_len if total_len > 0 else []

        series = df_clean[y_col].rolling(window=self.window, min_periods=1).mean()
        result = [max(0.0, float(v)) for v in series.fillna(0.0).tolist()]

        if extrapolate_periods > 0 and len(result) > 0:
            last_val = result[-1]
            result.extend([last_val] * extrapolate_periods)

        return result


class LinearMomentumTrendlineStrategy:
    """
    Fits a linear trendline projecting the historical average monthly cashflow rate.
    If you stop contributing (rate is 0), the projected future trend stays completely flat.
    """

    def __init__(self, window_months: int = 12):
        self.window_months = window_months

    def calculate(self, df: pd.DataFrame, y_col: str, extrapolate_periods: int) -> list:
        df_clean = df.dropna(subset=[y_col])
        if df_clean.empty:
            total_len = extrapolate_periods
            return [0.0] * total_len if total_len > 0 else []

        y_vals = df_clean[y_col].values
        result = [float(v) for v in y_vals]

        if len(y_vals) > 1:
            rates = np.diff(y_vals)
            avg_monthly_rate = np.mean(rates[-self.window_months :]) if len(rates) > 0 else 0.0
        else:
            avg_monthly_rate = 0.0

        if extrapolate_periods > 0 and len(result) > 0:
            last_val = result[-1]
            for step in range(1, extrapolate_periods + 1):
                result.append(max(0.0, last_val + step * avg_monthly_rate))

        return result


class TrendlineCalculator:
    """Utility class for computing statistical trendlines using the Strategy Pattern (OCP compliant)."""

    @staticmethod
    def calculate_trend(
        df: pd.DataFrame, y_col: str, strategy: TrendlineStrategy, extrapolate_periods: int = 0
    ) -> list:
        """Executes the supplied TrendlineStrategy algorithm on the dataset."""
        return strategy.calculate(df, y_col, extrapolate_periods)
