---
name: sdd-workflow
description: Orchestrate contract-first changes in the RendaPerene repository when a request needs a written specification, design review, tests, implementation, and final validation.
---

# Spec-Driven Development (SDD)

Use this workflow for non-trivial RendaPerene changes. Keep the work contract-first: clarify user-visible behavior before implementation details, and keep the approved contract visible through design, tests, implementation, and delivery.

Follow the repository's `AGENTS.md` instructions. RendaPerene is a local-first Python/Streamlit application for Brazilian (B3) portfolio tracking and retirement planning.

## Phase 1: Intent

Extract the user's outcome, motivation, scope, and business rules.

- Describe what the user or system should do and why.
- Separate stated requirements from assumptions.
- Ask one concise question when an unresolved assumption would materially change behavior, data integrity, or financial calculations.
- Keep implementation and architecture out of this phase.

Completion criterion: desired behavior, scope, and unresolved decisions are explicit.

## Phase 2: Spec

Write a Functional Specification in the conversation before changing production code. Invoke `$domain-modeling` when terminology, `CONTEXT.md`, or an ADR needs to be created or updated. Invoke `$grilling` to stress-test unresolved business decisions. Read `CONTEXT.md` and `CONTEXT-MAP.md` when present; read relevant `docs/adr/` files and the relevant backlog item when the request maps to one.

Include:

1. Behavioral contract from the user/system perspective.
2. Objective, verifiable acceptance criteria.
3. Execution scope and permissions, including local-data boundaries.
4. Error scenarios and expected responses.
5. Edge cases, especially empty, invalid, partial, duplicated, and stale data.
6. Business-plan validation: identify user-provided rules and remaining assumptions.
7. Persistence and integration impact when applicable.

Before requesting approval, answer explicitly:

- Who or what can execute the action?
- Are the relevant errors mapped?
- Does the business logic reflect the user's plan exactly?
- Are the acceptance criteria objective and verifiable?
- Which blind spots or assumptions remain?

Completion criterion: the specification covers normal behavior, failures, edge cases, and relevant persistence/integration effects.

## Phase 3: Spec Review

Present the specification and questionnaire to the user and stop. Wait for explicit approval before designing. If approval changes behavior, update and re-present the specification.

If the conversation is approaching context limits, invoke `$handoff` to checkpoint the approved artifacts before continuing in a new session.

Completion criterion: the user has explicitly approved the current specification.

## Phase 4: Design

After spec approval, invoke `$writing-plans` when a detailed implementation plan is useful, then produce a focused implementation design. Inspect existing code before proposing new seams.

- Respect `views → services → core`; wire concrete adapters in `app.py`.
- Depend on protocols in `core/ports.py` at boundaries.
- Keep business rules, DataFrame transformations, and persistence behind services, DAOs, or adapters.
- Read `ARCHITECTURE.md` for changes to module boundaries, persistence, ingestion, or integrations.
- Describe exact files, responsibilities, data flow, persistence/schema effects, error handling, and test seams.
- Preserve ownership: `AssetService` owns transactions/positions/dividends, `SimulationService` owns retirement calculations, and `ValuationService` owns pure Bazin rules.
- Identify migrations, cache/session invalidation, concurrency, privacy, and backwards-compatibility concerns when relevant.
- Use `codebase-design` for module-boundary or interface work. Use `domain-modeling` when documenting domain terms or ADRs.
- Record an ADR only for a durable architectural decision.

Completion criterion: every acceptance criterion maps to concrete code and verification locations, with no unresolved architectural branch.

## Phase 5: Design Review

Present the design to the user and stop. Wait for explicit approval before writing tests or production code. Revise and re-present it if scope or contract changes.

Completion criterion: the user has explicitly approved the current design.

## Phase 6: Test (Red)

Translate the approved contract into behavior-focused tests at the narrowest useful level. Invoke `$tdd` before writing tests when test-first development is requested or beneficial. Confirm the public seams under test and follow the red → green → refactor loop.

- Reuse the isolated database and injected test adapters from `tests/conftest.py`.
- Cover acceptance criteria, failure paths, and important edge cases.
- Keep financial calculations deterministic and network-independent.
- Run the smallest relevant subset and confirm new tests fail for the intended missing behavior when practical.

Completion criterion: every acceptance criterion has a test or an explicitly justified verification method.

## Phase 7: Implement (Green)

Implement the smallest coherent change that satisfies the approved contract and tests.

- Use `apply_patch` for edits.
- Keep code, identifiers, SQL, and technical comments in English; keep user-visible text and rendered labels in Brazilian Portuguese.
- Use `Formatter.format_currency()` for displayed BRL values.
- Preserve transaction semantics, annuity-due retirement calculations, local-first storage, and `.gitignore` protections.
- Do not add cloud databases, authentication, telemetry, or B3 portal scraping.
- Do not modify personal databases, spreadsheets, or generated artifacts.

Completion criterion: implementation satisfies the approved contract and relevant tests pass.

## Phase 7.5: Self-Audit

Review the complete resulting diff independently. Invoke `$code-review` when reviewing a branch, PR, or changes since a fixed point; otherwise perform the same audit directly. Look for correctness bugs, financial-calculation regressions, data loss, stale cache/session state, concurrency issues, security/privacy problems, architecture leaks, and missing edge-case tests.

Fix actionable findings within scope, then inspect the complete diff again.

Completion criterion: no known actionable P1/P2 defect remains and the diff stays within the approved spec and design.

## Phase 8: Hygiene and Verification

Invoke `$test-scenario-hygiene` after implementation when temporary or exploratory tests were added. Run proportionate checks, then the full suite when practical:

```bash
venv/bin/pytest
venv/bin/ruff check .
venv/bin/ruff format --check .
```

For UI changes, consider `venv/bin/streamlit run app.py` as a manual check when supported. Report commands not run and why. Update `ARCHITECTURE.md` and `README.md` when repository instructions require it.

Completion criterion: relevant tests, lint, formatting, and required documentation checks are complete, with failures understood and reported.

## Phase 9: Final Delivery

Return a self-contained handoff in the final response:

- summarize delivered behavior;
- list changed files;
- report validation commands and results, including failures or skipped checks;
- call out migrations, cache/session effects, assumptions, and follow-up requiring user action.

Keep progress updates in `commentary` while working and the completed handoff in `final`. Do not claim completion until the implementation and validation criteria are met.
