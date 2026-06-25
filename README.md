<div align="center">

# 💼 RendaPerene

**A Local-First, Production-Grade Investment & Retirement Cockpit**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?style=flat&logo=streamlit&logoColor=white)](https://streamlit.io/)
[![SQLite](https://img.shields.io/badge/SQLite-003B57?style=flat&logo=sqlite&logoColor=white)](https://sqlite.org/index.html)
[![Pytest](https://img.shields.io/badge/Tested_with-Pytest-0A9EDC?style=flat&logo=pytest&logoColor=white)](https://docs.pytest.org/)
[![Code Style: Clean Architecture](https://img.shields.io/badge/Code_Style-Clean_Architecture-brightgreen.svg)]()

</div>

---

## 📖 Overview

**RendaPerene** is a high-performance, 100% offline investment portfolio tracker designed to completely replace complex and fragile legacy financial spreadsheets. Built with Python and Streamlit, it provides a localized (PT-BR) interactive dashboard, B3 (Brazilian Stock Exchange) transaction parsing, and an advanced mathematical retirement simulator aligned with Luiz Barsi's previdenciary strategy.

Security and data sovereignty are at the core of this project: **Zero cloud database dependencies, no external telemetry, and fully local execution.**

---

## ✨ Key Features

* 📊 **Interactive Dashboard:** Beautiful, localized Plotly charts (donut sectors, profit/loss bars, chronologically ordered monthly timeline bar charts).
* 🏦 **B3 Excel Parser Integration:** Drag-and-drop support for official B3 `.xlsx` reports. Dynamically parses Buy, Sell, Stock Splits (*Desdobros*), and Redemptions (*Resgates*) with automatic chronological weighted average price (PM) calculations.
* 🔮 **Course-Corrected Retirement Simulator:** Advanced Annuity Due (PMT) financial math. It projects your lifetime retirement goals side-by-side with a real-world, course-corrected timeline based on your *actual* invested capital today.
* 🗄️ **Dual-Database Architecture:** Reference market assets (Tickers, Sectors, Segments) are completely decoupled from your personal transactions, allowing for seamless database migrations and resets.
* 🇧🇷 **Exclusive B3 / Brazilian Market Support:** Currently optimized exclusively for the Brazilian market. It automatically appends `.SA` to `yfinance` queries, parses localized B3 spreadsheets, fetches real-time macroeconomic indicators (IPCA, SELIC, Minimum Wage) from the Brazilian Central Bank (BCB) API, and enforces strict BRL (R$) formatting.
* 📈 **Advanced Dividend Tracking:** Automatically calculates YTD (Year-to-Date), L12M (Last 12 Months), YoC (Yield on Cost), and Bazin/Barsi-aligned pricing parameters based on dynamic market data.

---

## 🛠️ Technology Stack

* **Language:** Python 3.10+
* **Framework:** Streamlit (Implementing a strict MVC-like pattern)
* **Database:** SQLite3 (Dual File Pools)
* **Data Science & Math:** Pandas, NumPy
* **Market Integration:** `yfinance` (with intelligent TTLCache for fast batch queries)
* **Visualization:** Plotly Express & Plotly Graph Objects
* **Testing:** Pytest (Automated Regression Testing with `pytest.ini` pythonpath integration)

---

## 🚀 Installation & Execution

### 1. Clone and Setup Environment
Clone the repository and create an isolated virtual environment:
```bash
git clone https://github.com/your-username/rendaperene.git
cd rendaperene

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Launch the Application
Run the Streamlit server to open the interactive dashboard in your browser:
```bash
streamlit run app.py
```

### 3. Run Automated Tests
To execute the comprehensive Pytest regression suite:
```bash
pytest
```

---

## 🏗️ Architecture & Conventions

This project strictly adheres to **SOLID** principles, **Clean Architecture**, and **DRY** (Don't Repeat Yourself). 
* **Language Policy:** The codebase (classes, variables, SQL, comments) is entirely in **English**, while the User Interface (strings, chart labels, tooltips) is rigorously localized to **Portuguese (PT-BR)**.
* **Separation of Concerns:** Views (`views/`) handle exclusively GUI rendering via Streamlit. All business logic, SQLite operations, and DataFrame manipulations occur in Domain Services (`services/`).
* **Strategy Pattern:** Financial projections and statistical trendlines are implemented using Open/Closed Principle (OCP) compliant strategies (e.g., Polynomial, Linear Momentum) located in `core/utils/trendlines.py`.

---

## 🔒 Security & Privacy Notice

**Local-First Mandate:** This application operates entirely on your local machine. Your financial data is saved strictly to local SQLite `.db` files. There are no cloud APIs, third-party authentication services, or data telemetry scrapers.

**Disclaimer:** This project is a strictly personal, independent development portfolio.

---

<div align="center">
  <i>Developed with ❤️ for financial independence.</i>
</div>