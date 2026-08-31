# Friendly mapping of months to the Brazilian Portuguese standard
MONTHS_PT = {
    "01": "Jan",
    "02": "Fev",
    "03": "Mar",
    "04": "Abr",
    "05": "Mai",
    "06": "Jun",
    "07": "Jul",
    "08": "Ago",
    "09": "Set",
    "10": "Out",
    "11": "Nov",
    "12": "Dez",
}

MILLION = 1_000_000
BILLION = 1_000_000_000
TRILLION = 1_000_000_000_000

# Core DataFrame column names and dictionary keys to prevent Magic Strings (DRY-compliant)
TICKER = "ticker"
NAME = "name"
ASSET_TYPE = "asset_type"
SECTOR = "sector"
QUANTITY = "quantity"
AVERAGE_PRICE = "average_price"
INVESTED_AMOUNT = "invested_amount"
TOTAL_DIVIDENDS = "total_dividends"
L12M_DIVIDENDS = "l12m_dividends"
YTD_DIVIDENDS = "ytd_dividends"

# Dynamic real-time market data keys
CURRENT_PRICE = "current_price"
CURRENT_VALUE = "current_value"
PROFIT_LOSS = "profit_loss"

# Custom computed portfolio metrics keys
ADJUSTED_PRICE = "adjusted_price"
RETURN_PCT_CUSTOM = "return_pct_custom"
YOC_CUSTOM = "yoc_custom"
YOC_12_CUSTOM = "yoc_12_custom"

# Planning configuration keys to prevent magic strings in financial projections
BIRTH_DATE = "birth_date"
RETIREMENT_AGE = "retirement_age"
DESIRED_INCOME_MW = "desired_income_mw"
ANNUAL_INTEREST_RATE = "annual_interest_rate"
MW_VALUE = "mw_value"
INITIAL_EQUITY_INPUT = "initial_equity_input"
DESIRED_INCOME_TYPE = "desired_income_type"
DESIRED_INCOME_FIXED = "desired_income_fixed"
PLANNING_START_DATE = "planning_start_date"

# Planning Independence Income type enums
INCOME_TYPE_MULTIPLIER = "MULTIPLIER"
INCOME_TYPE_FIXED = "FIXED"

# Database transactions and dividends column keys
TRANSACTION_TYPE = "transaction_type"
UNIT_PRICE = "unit_price"
FEES = "fees"
DATE = "date"
DIVIDEND_TYPE = "dividend_type"
TOTAL_VALUE = "total_value"

# Historical evolution and contributions column keys
MONTH_STR = "month_str"
NET_CASHFLOW = "net_cashflow"
CUMULATIVE_INVESTED = "cumulative_invested"
CUMULATIVE_DIVIDENDS = "cumulative_dividends"
MONTHLY_DIVIDEND = "monthly_dividend"
YEAR = "year"
MONTH = "month"
AMOUNT = "amount"
PLANNED_INVESTED = "planned_invested"
PLANNED_DIVIDENDS = "planned_dividends"
MONTH_DISPLAY = "month_display"

# Planning simulation dictionary keys
SIM_CURRENT_AGE = "current_age"
SIM_START_AGE_YEARS = "start_age_years"
SIM_TOTAL_TIME_MONTHS = "total_time_months"
SIM_REMAINING_TIME_MONTHS = "remaining_time_months"
SIM_TARGET_MONTHLY_INCOME = "target_monthly_income"
SIM_MONTHLY_INTEREST_RATE = "monthly_interest_rate"
SIM_TARGET_EQUITY = "target_equity"
SIM_REQUIRED_CONTRIBUTION = "required_monthly_contribution"
SIM_UPDATED_CONTRIBUTION = "updated_monthly_contribution"
SIM_TOTAL_INVESTED = "total_invested"

# Yahoo Finance & Market Analysis API backend dictionary keys
MARKET_NAME = "name"
CEILING_PRICE = "ceiling_price"
MARKET_PB = "pb"
MARKET_PE = "pe"
CURRENT_DY = "dy"
MARKET_ROE = "roe"
MARKET_NET_MARGIN = "net_margin"
MARKET_LOW_52W = "low_52w"
MARKET_HIGH_52W = "high_52w"
MARKET_AVG_DIV_5Y = "avg_dividend_5y"
MARKET_AVG_DY_5Y = "avg_dy_5y"
MARKET_DIVIDENDS_5Y = "dividends_5y"
MARKET_DIVIDENDS_HISTORY = "dividends_history"
MARKET_DIVIDEND_AVERAGE_YEARS = "dividend_average_years"
MARKET_DIVIDEND_HISTORY_STATUS = "dividend_history_status"

# Persisted investment goal setting keys
GOAL_REINVEST_DIVIDENDS = "reinvest_dividends"
GOAL_SHARE_QUANTITY = "share_quantity"

# Price-Ceiling Model Selection and custom params database configuration keys
CEILING_MODEL_SELECTION = "ceiling_model_selection"
BAZIN_TARGET_YIELD = "bazin_target_yield"
BAZIN_TARGET_SPREAD = "bazin_target_spread"

# Streamlit Global Session State key constants to prevent volatile runtime key mismatches
SESSION_BIRTH_DATE = "birth_date"
SESSION_RETIREMENT_AGE = "retirement_age"
SESSION_DESIRED_INCOME_MW = "desired_income_mw_val"
SESSION_ANNUAL_INTEREST_RATE = "annual_interest_rate"
SESSION_MW_VALUE = "mw_value"
SESSION_INITIAL_EQUITY = "initial_equity_input"
SESSION_DESIRED_INCOME_TYPE = "desired_income_type"
SESSION_DESIRED_INCOME_FIXED = "desired_income_fixed_val"
SESSION_CEILING_MODEL_SELECTION = "ceiling_model_selection"
SESSION_BAZIN_TARGET_YIELD = "bazin_target_yield"
SESSION_BAZIN_TARGET_SPREAD = "bazin_target_spread"
SESSION_REQUIRED_CONTRIBUTION_CACHE = "required_monthly_contribution_cache"
SESSION_CALCULATED_EQUITY_CACHE = "calculated_equity_cache"
SESSION_PLANNING_START_DATE = "planning_start_date"
SESSION_PLANNING_START_DATE_ENABLED = "planning_start_date_enabled"

# Streamlit Interactive Widget key constants (Safe Value-Binding Pattern keys)
WIDGET_BIRTH_DATE = "birth_date_input"
WIDGET_RETIREMENT_AGE = "retirement_age_input"
WIDGET_INTEREST_RATE = "annual_interest_rate_input"
WIDGET_INCOME_TYPE = "desired_income_type_selector"
WIDGET_INCOME_MW = "desired_income_mw_input"
WIDGET_INCOME_FIXED = "desired_income_fixed_input"
WIDGET_CEILING_MODEL_SELECTOR = "ceiling_model_selection_selector"
WIDGET_BAZIN_YIELD_INPUT = "bazin_target_yield_input"
WIDGET_BAZIN_SPREAD_INPUT = "bazin_target_spread_input"
WIDGET_PLANNING_START_DATE = "planning_start_date_input"
WIDGET_PLANNING_START_DATE_ENABLED = "planning_start_date_enabled_input"
WIDGET_INITIAL_EQUITY = "initial_equity_input_widget"
WIDGET_REINVESTMENT_GOAL_PREFIX = "enable_dividend_reinvestment_goal_"
WIDGET_SHARE_QUANTITY_GOAL_PREFIX = "enable_share_quantity_goal_"
WIDGET_ACCUMULATION_PLAN_WEIGHTS_PREFIX = "accumulation_plan_weights_"
WIDGET_ACCUMULATION_PLAN_EDITOR_PREFIX = "accumulation_plan_editor_"

WEIGHT_PCT = "weight_pct"
CEILING_PRICE_GRID = "ceiling_price_grid"
