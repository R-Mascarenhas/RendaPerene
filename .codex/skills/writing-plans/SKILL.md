---
name: writing-plans
description: Create an actionable implementation plan for an approved RendaPerene specification and design.
---

# Implementation Plans

Use after the SDD specification and design have been approved. Inspect the repository before writing the plan.

Each plan step must include:

- the exact repository-relative file path;
- the responsibility and concrete change;
- dependencies or schema effects, if any;
- the behavior test or verification that proves the step;
- risks, compatibility, cache/session, and privacy effects when relevant.

Organize steps in dependency order and map them to the approved acceptance criteria. Prefer existing services, DAOs, ports, and test fixtures over new abstractions. Keep business logic out of views and wire production implementations through `app.py`.

Use English for code-facing names and Brazilian Portuguese for user-visible text. Do not prescribe Gradle, Koin, Android modules, or other conventions absent from RendaPerene.

Completion criterion: another engineer can execute the plan without inventing missing file locations, ownership, behavior, or verification steps.
