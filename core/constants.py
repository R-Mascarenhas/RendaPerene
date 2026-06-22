# Friendly mapping of months to the Brazilian Portuguese standard
MONTHS_PT = {
    "01": "Jan", "02": "Fev", "03": "Mar", "04": "Abr",
    "05": "Mai", "06": "Jun", "07": "Jul", "08": "Ago",
    "09": "Set", "10": "Out", "11": "Nov", "12": "Dez"
}

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
MARKET_LOW_52W = "low_52w"
MARKET_HIGH_52W = "high_52w"
MARKET_AVG_DIV_5Y = "avg_dividend_5y"
MARKET_AVG_DY_5Y = "avg_dy_5y"
MARKET_DIVIDENDS_5Y = "dividends_5y"
