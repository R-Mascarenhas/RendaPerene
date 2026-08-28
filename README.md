<div align="center">

# 💼 RendaPerene

**Local-first portfolio tracking and retirement planning for Brazilian investors**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?style=flat&logo=streamlit&logoColor=white)](https://streamlit.io/)
[![SQLite](https://img.shields.io/badge/SQLite-003B57?style=flat&logo=sqlite&logoColor=white)](https://sqlite.org/)
[![Pytest](https://img.shields.io/badge/Tested_with-Pytest-0A9EDC?style=flat&logo=pytest&logoColor=white)](https://docs.pytest.org/)

</div>

## Overview

RendaPerene is a Streamlit application for recording Brazilian (B3) investment portfolios and simulating retirement. It stores the portfolio and planning configuration in local SQLite files, while using existing public integrations to obtain current market and macroeconomic data.

The interface is in Brazilian Portuguese (PT-BR); source code and developer documentation are in English.

## Features

- **Portfolio dashboard:** portfolio totals, annual contribution progress, performance metrics, holdings tables, and Plotly charts.
- **Manual operations and B3 import:** record purchases, sales, dividends, JCP, and yields manually, or import the official B3 `.xlsx` export.
- **Ledger rules:** calculates weighted average price including fees; handles splits/bonuses, reverse splits, redemptions, and duplicate imports.
- **Asset details and market monitor:** follows owned and manually selected assets, displays price history and dividend information, supports Bazin ceiling-price models, and includes a catalog-wide Raio-X consultation with valuation metrics and annual dividend yields based on each year's closing price.
- **Retirement planning:** calculates lifetime and course-corrected monthly contributions using annuity-due math, with projections based on the stored plan and portfolio history.
- **Investment goals:** the Planning screen has a dedicated Goals tab where dividend reinvestment and per-asset share quantities can be enabled independently. Disabling reinvestment removes that metric from the Dashboard. Share-goal progress uses the quantity held on January 1 as its annual baseline and shows the target position-growth percentage. The Dashboard consolidates active share goals into one allocation-weighted progress bar, with per-ticker details on hover and in an expandable section. Asset weights may be equal or custom, 0% means inactive, and progress can exceed 100%. For recently listed assets, dividend averages use only available listed years, count listed years without payments as zero, and display an observation when the history is partial or unavailable.
- **Multiple local portfolios:** select an existing portfolio database or create a new local portfolio from the sidebar.

## Data and privacy

Portfolio data is stored locally in SQLite databases under `database/`. The application does not use a cloud database, accounts, or telemetry, and it does not scrape the B3 portal.

Fresh market data requires network access:

- Yahoo Finance (`yfinance`) provides B3 prices, market metrics, price history, and dividend data. If a live quote is unavailable, the application uses the latest valid daily close for the asset analysis.
- Banco Central do Brasil (BCB) provides IPCA, Selic, and minimum-wage indicators.

The B3 import is user-directed: download the official Excel export from the B3 Investor Portal and upload it in the application. Local databases and personal spreadsheets are ignored by Git; do not commit them.

## Requirements

- Python 3.10 or newer
- `pip`
- Network access only when requesting fresh Yahoo Finance or BCB data

## Installation

Clone the repository, create a virtual environment, and install the application:

```bash
git clone https://github.com/R-Mascarenhas/RendaPerene.git
cd RendaPerene

python3 -m venv venv
source venv/bin/activate
python -m pip install .
```

For development, install the optional test and lint dependencies:

```bash
python -m pip install -e ".[dev]"
```

On Windows PowerShell, activate the environment with:

```powershell
.\venv\Scripts\Activate.ps1
```

## Run

Start the Streamlit application:

```bash
venv/bin/streamlit run app.py
```

If the environment is activated, `streamlit run app.py` is equivalent. The first run creates and initializes `database/portfolio.db` when it does not already exist.

## Validation

Run the regression suite and lint checks:

```bash
venv/bin/pytest
venv/bin/ruff check .
venv/bin/ruff format --check .
```

Ruff targets Python 3.10, uses a 100-character line length, and intentionally excludes `tests/` from its configured scope.
GitHub Actions runs the three validation commands independently for pull requests targeting `main` and pushes to `main`.

## Architecture

The application is divided into three layers:

- `core/`: database infrastructure, DAO implementations, ports, formatting, B3 parsing, and headless market-data integration.
- `services/`: framework-agnostic portfolio, planning, and valuation rules.
- `views/`: Streamlit views and presentation components.

`app.py` is the composition root that initializes persistence, wires production adapters, initializes session state, and routes the Dashboard, Assets, and Planning views. See [ARCHITECTURE.md](ARCHITECTURE.md) for the persistence model, dependency boundaries, financial rules, and integrations.

## License

This project is distributed under the [GNU Affero General Public License v3.0](LICENSE).
