@AGENTS.md

## Claude Code specifics

- The main session is the **Orchestrator** (§2). Delegate implementation to the
  `implementer` subagent and mechanical work to the `chore` subagent; use
  `reviewer` for a second read on non-trivial diffs.
- Give delegates a complete task spec: they start with no conversation context.
