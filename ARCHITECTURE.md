# RendaPerene Architecture

## Overview

RendaPerene is a Python and Streamlit application for tracking Brazilian (B3) investment portfolios and planning retirement. It keeps portfolio data in local SQLite files, imports B3 Excel exports, obtains market data from existing public integrations, and presents the interface in Brazilian Portuguese.

The application is local-first. It does not use a cloud database, user authentication, telemetry, or automated scraping of the B3 portal.

## Runtime and composition

`app.py` is the composition root. It:

1. selects and initializes the active portfolio database;
2. configures Streamlit;
3. wires the production adapters for portfolio, planning, B3 parsing, and cached market data;
4. initializes session state; and
5. routes the three top-level views: Dashboard, Assets, and Planning.

On a normal local run, the active database is `database/portfolio.db` or another `portfolio_*.db` selected in the sidebar. When a Streamlit shared-host environment is detected, the runtime creates a session-specific database cloned from `database/portfolio_demo.db`; this is demonstration support, not the primary persistence model.

Run the application with:

```bash
venv/bin/streamlit run app.py
```

## Layers and dependencies

The repository has three top-level layers:

- **`core/`** holds technical infrastructure and shared contracts. It includes `DatabaseManager`, protocols in `core/ports.py`, SQLite DAOs, constants, localized strings, formatting, session management, the B3 parser, and headless market-data integration.
- **`services/`** holds application and domain logic. Services depend on ports rather than presentation code.
- **`views/`** holds Streamlit rendering and interaction. `StreamlitCachedMarketData` is the presentation-boundary adapter that adds Streamlit caching to the headless market-data implementation.

Dependency direction is `views` → `services` → `core` contracts and adapters. The composition root selects concrete adapters. Views must not contain business calculations, raw SQL, or B3 parsing logic.

### Domain services

- `AssetService` is the source of truth for transactions, dividends, asset positions, historical evolution, and the monitored-assets list.
- `SimulationService` owns retirement configuration and annuity-due calculations. Consumers use `get_current_simulation()` instead of reimplementing contribution calculations.
- `ValuationService` contains pure Bazin target-yield and ceiling-price rules; it has no Streamlit, database, or market-data dependency.

### Ports and adapters

`core/ports.py` defines the boundaries for portfolio persistence, asset catalog access, market data, planning configuration, database schema registration, B3 Excel parsing, and cross-service providers. Production adapters are the SQLite DAOs, `MarketData`, and `B3ExcelParserAdapter`. Tests replace these boundaries with isolated databases, mocks, or injected adapters.

## Persistence

`DatabaseManager` discovers schema providers in `core/daos/` and asks each registered DAO to create or migrate its tables. The tables live together in the active portfolio SQLite database; the static asset catalog is a separate `assets.csv` file.

| Store | Purpose |
| --- | --- |
| `transactions` | Portfolio ledger: `id`, `date`, `ticker`, `transaction_type`, `quantity`, `unit_price`, and `fees`. Transaction types persisted by the application are `BUY`, `SELL`, and `GROUP`. |
| `dividends` | Received income: `id`, `date`, `ticker`, `dividend_type`, and `total_value`; types are `DIVIDEND`, `JCP`, and `YIELD`. |
| `tracked_market_assets` | Manually tracked tickers. Owned assets are combined with this list for market monitoring. |
| `dividend_corrections` | Per-ticker, per-year dividend overrides, keyed by `(ticker, year)`. |
| `planning_configuration` | Singleton configuration (`id = 1`): birth date, retirement age, income inputs, annual interest rate, minimum wage, initial equity, income mode, Bazin model inputs, and optional planning start date. |
| `assets.csv` | Static B3 catalog with ticker metadata. Unknown imported tickers can be added as fallback catalog entries. |

SQLite does not declare cross-store foreign keys. Services preserve the required consistency programmatically.

## Financial and import rules

The B3 importer receives an Excel file selected by the user, normalizes its columns and dates, and emits English internal transaction and dividend records.

- Purchases update the weighted average price, including fees.
- Sales reduce the held quantity while retaining the average price of the remaining position.
- B3 splits and bonuses are stored as zero-cost `BUY` transactions.
- Reverse splits are stored as `GROUP` transactions, which replace the current quantity with the reported quantity.
- Redemptions are stored as `SELL` transactions.
- Zero-cost custodian transfers are ignored; non-zero transfers are interpreted from their credit/debit direction.
- Retirement contribution calculations use annuity-due payments (`type = 1`) through `SimulationService.pmt_annuity_due()`.

## External integrations

- `yfinance` supplies B3 quotes, price history, and dividend/valuation data. Tickers are requested with the `.SA` suffix.
- Banco Central do Brasil (BCB) SGS endpoints supply IPCA, Selic, and minimum-wage values. The headless integration uses fallbacks when a request fails.
- The Streamlit adapter caches market results: quotes and detailed analysis for 10 minutes, history for one hour, and BCB indicators for 30 days.

These integrations support local use but require network access when fresh data is requested. The application does not scrape the B3 portal; users import the official B3 Excel export themselves.

## Presentation

All code, identifiers, SQL, comments, and developer documentation are in English. All user-facing labels, messages, chart labels, help text, and rendered tables are in PT-BR. BRL values displayed to users use `Formatter.format_currency()`.

- **Dashboard** renders annual contribution progress, portfolio summary metrics, charts, and detailed holdings.
- **Assets** coordinates three subviews: portfolio details, market monitoring and Bazin valuation, and manual/B3-import operations.
- **Planning** edits persisted retirement parameters, supports a sandbox simulation, and renders timing, required-contribution, and projection components.

## Validation

Pytest uses `pytest.ini` to make the repository root importable. The shared test fixture redirects persistence to an isolated database and configures test adapters.

```bash
venv/bin/pytest
venv/bin/ruff check .
venv/bin/ruff format --check .
```

Ruff targets Python 3.10 with a 100-character line length and intentionally excludes `tests/`.
