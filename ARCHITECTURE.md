# Carteira App - Architecture & Implementation Specification

## 1. Project Overview
The goal of this project is to build a modern, local-first web application to entirely replace the legacy `Carteira - Rafael Mascarenhas.ods` spreadsheet. It provides automated average price calculations, live real-time quotes, a drag-and-drop B3 data importer, and interactive retirement planning simulations.

## 2. Technology Stack
*   **Language:** Python 3.10+
*   **Frontend / UI:** Streamlit
*   **Database:** SQLite3 (Local file)
*   **Data Processing:** Pandas
*   **Live Quotes API:** `yfinance` (Free, no authentication required. Tickers use `.SA` suffix for B3).

## 3. Deployment & Data Privacy
*   **Strictly Local:** The application runs entirely on the user's local machine via `streamlit run app.py`.
*   **Data Sovereignty:** The SQLite database (`portfolio.db`) lives locally. There is no cloud database and no mandatory Google Drive synchronization (the user explicitly opted for independent local instances).
*   **No Web Scraping:** The app will *not* attempt to automatically scrape the B3 portal due to 2FA and anti-bot measures.

## 4. Data Ingestion Strategy
*   **Historical Data (ODS):** The user opted to **abandon** automated migration of the legacy ODS file. The user will manually start fresh by typing their current holdings/history into the new app interface.
*   **Ongoing Integration (B3 Import):** The app will feature a Drag-and-Drop file uploader. The user downloads the official Excel (`.xlsx`) export from the B3 Investor Portal and drops it into the app. Pandas will parse this file to automatically populate the `Transações` and `Proventos` tables.

## 5. Database Schema (SQLite)

### Table: `ativos`
*   `ticker` (TEXT, Primary Key) - e.g., 'BBAS3'
*   `nome` (TEXT)
*   `tipo_ativo` (TEXT) - e.g., 'Ação', 'FII'
*   `setor` (TEXT)

### Table: `transacoes`
*   `id` (INTEGER, Primary Key, Auto-increment)
*   `data` (TEXT) - YYYY-MM-DD
*   `ticker` (TEXT, Foreign Key)
*   `tipo_movimentacao` (TEXT) - 'Compra' / 'Venda'
*   `quantidade` (INTEGER)
*   `preco_unitario` (REAL)
*   `taxas` (REAL)

### Table: `proventos`
*   `id` (INTEGER, Primary Key, Auto-increment)
*   `data` (TEXT)
*   `ticker` (TEXT, Foreign Key)
*   `tipo_provento` (TEXT) - 'Dividendo', 'JCP', etc.
*   `valor_total` (REAL)

### Table: `configuracao_planejamento`
*   `id` (INTEGER, Primary Key)
*   `idade_atual` (INTEGER)
*   `idade_aposentadoria` (INTEGER)
*   `meta_patrimonio` (REAL)

## 6. Core Application Views (Streamlit Tabs)

1.  **Dashboard (Resumo Carteira):**
    *   Joins `transacoes` to calculate the current position (quantity) and Preço Médio (Average Price) dynamically.
    *   Calls `yfinance` to get the real-time `lastPrice`.
    *   Displays key metrics: Total Invested, Current Value, Unrealized Profit/Loss, and overall Portfolio Yield on Cost.
2.  **Lançamentos & B3 Import:**
    *   Forms for manual entry of new buys, sells, and dividends.
    *   The "B3 Drag & Drop" zone to process `.xlsx` files.
3.  **Simulador de Aposentadoria (Planejamento):**
    *   Interactive sliders for `Aporte Mensal` (Monthly Contribution) and `Taxa de Juros Anual` (Annual Interest Rate).
    *   Dynamic line charts (using Plotly or Streamlit native charts) projecting compound interest growth over 35 years until the `meta_patrimonio` is reached.
