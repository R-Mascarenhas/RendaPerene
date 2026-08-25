# RendaPerene agent guide

## Scope

RendaPerene is a local-first Streamlit application for Brazilian (B3) portfolio tracking and retirement planning. Personal portfolios are stored in local SQLite databases; market quotes and Brazilian macroeconomic indicators use the existing Yahoo Finance and Banco Central integrations. Do not add cloud databases, telemetry, authentication services, or B3 portal scraping.

## Repository map

- `app.py` is the composition root: it initializes the database, wires production adapters, initializes Streamlit session state, and routes the main views.
- `core/` contains infrastructure and cross-cutting code: database management, ports, DAOs, constants, strings, formatting, session utilities, B3 parsing, and market-data integrations.
- `services/` contains framework-agnostic domain logic. `AssetService` owns transactions, positions, and dividends; `SimulationService` owns retirement calculations; `ValuationService` contains pure Bazin valuation rules.
- `views/` contains Streamlit presentation and view components. `views/cached_market_data.py` adapts cached market data for the UI.
- `tests/` contains the pytest regression suite. Test adapters and isolated database setup live in `tests/conftest.py`.

Read `ARCHITECTURE.md` when a task changes module boundaries, persistence, data ingestion, or the application’s integrations. Read the relevant backlog item in `docs/backlog/` before implementing it.

## Development rules

- Write code, identifiers, SQL, comments, and developer documentation in English. Keep all user-visible UI text, chart labels, tooltips, and rendered tables in Brazilian Portuguese (PT-BR).
- Keep views focused on rendering and interaction. Put business rules, DataFrame transformations, and persistence behind services, DAOs, or adapters.
- Depend on protocols in `core/ports.py` at boundaries. Wire production implementations in `app.py`; inject fakes or mocks in tests.
- Preserve the existing service ownership. Use `SimulationService.get_current_simulation()` for required-contribution values; do not duplicate retirement math in views or other services.
- Use `Formatter.format_currency()` for BRL values shown to users.
- Preserve the current transaction semantics: purchases update weighted average price including fees; sales reduce quantity without changing average price; B3 splits are zero-cost transactions; redemptions map to sales.
- Preserve the annuity-due (`type=1`) retirement calculation implemented by `SimulationService.pmt_annuity_due()`.
- When a change affects the documented architecture, persistence model, integration, user workflow, setup, or validation commands, update `ARCHITECTURE.md` and `README.md` in the same change as needed.
- Keep changes scoped to the request. Ask before a destructive change, an external write, or a material expansion of scope.

## Data and privacy

- Treat local `.db`, `.ods`, `.xlsx`, `.csv`, and generated package artifacts as potentially sensitive or generated data. Do not add or modify them unless the task explicitly requires it.
- Keep `.gitignore` protections for personal databases and spreadsheets intact. The committed B3 test fixture is the explicit exception.
- Do not expose personal financial data in logs, documentation, commits, or responses.

## Commands

Use the repository virtual environment when available:

```bash
venv/bin/pytest
venv/bin/ruff check .
venv/bin/ruff format --check .
venv/bin/streamlit run app.py
```

Run the smallest relevant test subset during iteration and `venv/bin/pytest` before handing off code changes. Run Ruff for changed production Python files; Ruff intentionally excludes `tests/` by configuration.

## Completion

For code changes, report the files changed and the validation commands run, including any failures or checks not run.

## Agent skills

### Issue tracker

Issues and specs are tracked in GitHub Issues through the connected GitHub MCP, with `gh` as a fallback. See `docs/agents/issue-tracker.md`.

### Triage labels

The default canonical triage labels are used. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository. See `docs/agents/domain.md`.
