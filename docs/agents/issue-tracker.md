# Issue tracker: GitHub via MCP

Issues and specs for this repository live in GitHub Issues under `R-Mascarenhas/RendaPerene`.

Use the connected GitHub MCP tools as the primary interface. Use the `gh` CLI only when MCP is unavailable or does not expose the required operation.

Never embed GitHub tokens in remote URLs, commands, documentation, or logs.

## Conventions

- **Create an issue**: use the GitHub MCP issue-creation operation.
- **Read an issue**: fetch the issue through MCP, including its labels and comments.
- **List or search issues**: use the GitHub MCP issue-search operation with repository, state, and label filters.
- **Comment on an issue**: use the GitHub MCP comment operation.
- **Apply or remove labels**: use the GitHub MCP issue-update or label operations.
- **Close or reopen an issue**: use the GitHub MCP issue-update operation.
- **Read a pull request**: fetch its metadata, comments, review threads, and diff through MCP.
- **Resolve a review thread**: use the GitHub MCP review-thread operation.

When an MCP operation is unavailable, use the equivalent `gh issue`, `gh pr`, or `gh api` command as a fallback.

## Pull requests as a triage surface

**PRs as a request surface: no.**

Set this flag to `yes` only if external pull requests should enter the same triage queue as issues.

GitHub shares one number space across issues and pull requests. Resolve ambiguous references through MCP by checking the object type before acting.

## When a skill says "publish to the issue tracker"

Create a GitHub issue through MCP.

## When a skill says "fetch the relevant ticket"

Fetch the GitHub issue through MCP, including its body, labels, and comments.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with child issues as tickets.

- **Map**: an issue labelled `wayfinder:map`, containing Notes, Decisions-so-far, and Fog.
- **Child ticket**: a GitHub sub-issue linked to the map. If sub-issues are unavailable, use a task list and add `Part of #<map>` to the child.
- **Blocking**: use GitHub's native issue dependencies. If MCP does not expose them, fall back to `gh api`. If dependencies are unavailable, use a `Blocked by: #<n>` line.
- **Frontier query**: select the first open, unassigned child without open blockers.
- **Claim**: assign the ticket to the current GitHub user through MCP.
- **Resolve**: comment with the answer, close the issue, and append the context pointer to the map's Decisions-so-far.
