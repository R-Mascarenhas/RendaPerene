# Portfolio App - Architecture & Implementation Specification

## 1. Project Overview
The goal of this project is to build a modern, local-first web application to entirely replace the legacy `Carteira - Rafael Mascarenhas.ods` spreadsheet. It provides automated average price calculations, live real-time quotes, a drag-and-drop B3 data importer, and interactive retirement planning simulations.

## 2. Technology Stack
*   **Language:** Python 3.10+ (100% English codebase and variables)
*   **Frontend / UI:** Streamlit (100% Portuguese PT-BR user-facing UI labels)
*   **Database:** SQLite3 (Local file `database/portfolio.db`)
*   **Data Processing:** Pandas
*   **Live Quotes API:** `yfinance` (Free, no authentication required. Tickers use `.SA` suffix for B3).

## 3. Deployment & Data Privacy
*   **Strictly Local:** The application runs entirely on the user's local machine via `streamlit run app.py`.
*   **Data Sovereignty:** The SQLite database (`portfolio.db`) lives locally. There is no cloud database and no mandatory Google Drive synchronization (the user explicitly opted for independent local instances).
*   **No Web Scraping:** The app will *not* attempt to automatically scrape the B3 portal due to 2FA and anti-bot measures.

## 4. Data Ingestion Strategy
*   **Historical Data (ODS):** The user opted to **abandon** automated migration of the legacy ODS file. The user will manually start fresh by typing their current holdings/history into the new app interface.
*   **Ongoing Integration (B3 Import):** The app features a Drag-and-Drop file uploader. The user downloads the official Excel (`.xlsx`) export from the B3 Investor Portal and drops it into the app. Pandas will parse this file to automatically populate the `transactions` and `dividends` tables, translating categories to English in real-time.

## 5. Database Schema (SQLite)

### Table: `transactions`
*   `id` (INTEGER, Primary Key, Auto-increment)
*   `date` (TEXT) - YYYY-MM-DD
*   `ticker` (TEXT) - e.g., 'BBAS3'
*   `transaction_type` (TEXT) - 'BUY' / 'SELL'
*   `quantity` (INTEGER)
*   `unit_price` (REAL)
*   `fees` (REAL)

### Table: `dividends`
*   `id` (INTEGER, Primary Key, Auto-increment)
*   `date` (TEXT)
*   `ticker` (TEXT)
*   `dividend_type` (TEXT) - 'DIVIDEND' / 'JCP' / 'YIELD'
*   `total_value` (REAL)

### Table: `planning_configuration`
*   `id` (INTEGER, Primary Key, Default 1)
*   `birth_date` (TEXT)
*   `retirement_age` (INTEGER)
*   `desired_income_mw` (REAL)
*   `annual_interest_rate` (REAL)
*   `mw_value` (REAL)
*   `initial_equity_input` (REAL)

### Table: `tracked_market_assets`
*   `ticker` (TEXT, Primary Key)

### Table: `dividend_corrections`
*   `ticker` (TEXT)
*   `year` (INTEGER)
*   `total_value` (REAL)
*   *Primary Key:* `(ticker, year)`

## 6. Project Structure (Unified SOLID Layers)

The codebase is structured into three clean, un-nested top-level layers to maximize maintainability, readability, and prepare for a future Kotlin Multiplatform (KMP) or Desktop JVM migration:

*   **`core/`** - Shares technical infrastructure (Database SQLite managers, PT-BR `Formatter`, local-caching `MarketData`, and `TrendlineCalculator` implementing OCP Strategy Pattern).
*   **`services/`** - Unified, framework-agnostic mathematical domain services. Contains `AssetService` (the single source of truth for holdings, trades, and average prices) and `SimulationService` (the single source of truth for planning and annuity PMT calculations).
*   **`views/`** - 100% presentation/UI. Houses the top-level Streamlit coordinators (`dashboard_view.py`, `planning_view.py`, `assets_view.py`) and their decoupled sub-components (`components/`).

## 7. Core Application Views (Streamlit Tabs)

1.  **📊 Dashboard:**
    *   `AnnualPlanningWidget` - Displays the progress towards your annual out-of-pocket contribution target.
    *   `PatrimonySummaryWidget` - Renders cards with key metrics (Total Invested, Current Value, Unrealized Profit/Loss, and overall Portfolio Yield on Cost).
    *   `DashboardCharts` - Plots pie allocation and progressive comparison bar charts.
    *   `DetailedHoldingsWidget` - Displays the active stock/FII holdings data grid with high-contrast performance colored cell styling.
2.  **🎯 Planejamento:**
    *   Simulates retirement age, desired income, and linear linear-momentum growth projections.
    *   Renders interactive area/monthly and comparative charts projecting compound interest growth.
3.  **📝 Ativos:**
    *   `📥 Importar & Lançar` - Form for manual transactions and B3 drag-and-drop zone.
    *   `📁 Meus Ativos` - Subtabs with unblocked B3 sector logos, dynamic 5y historical dividend pivot tables, and Google Finance-style price charts with interactive trade transaction markers.
    *   `📈 Mercado` - Searchable watchlist with auto-completing search and Bazin price teto valuation grids.
