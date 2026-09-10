---
name: test-scenario-hygiene
description: Review tests added during a RendaPerene change and remove only approved scaffolding before final validation.
---

# Test Scenario Hygiene

Use after implementation and before final delivery. Review the complete worktree diff and classify changed tests as durable or scaffolding.

Keep tests that verify observable behavior, pure financial/domain rules, documented edge cases, crash-prone inputs, real service/DAO boundaries, or isolated persistence state. Treat interaction-only tests, redundant coverage, standard-library checks, and private implementation assertions as scaffolding candidates.

Do not delete candidates automatically. Present each candidate, its reason, and its path to the user; remove only those explicitly approved. Preserve the isolated database setup and injected adapters from `tests/conftest.py`.

After any approved cleanup, run:

```bash
venv/bin/pytest
venv/bin/ruff check .
venv/bin/ruff format --check .
```

Completion criterion: every changed test is intentionally retained or explicitly approved for removal, and the validation results are reported.
