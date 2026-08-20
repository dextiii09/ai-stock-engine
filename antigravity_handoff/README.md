# Antigravity handoff — weekly trading-report audit

Teaches Google Antigravity to generate the weekly AI Stock paper-trading report
**and** hunt for bugs/glitches the same way it was done manually. Two files:

- `rules/trading-report-audit.md` — a **Rule** (persistent context): the ten audit
  smell-tests, the known failure-pattern catalog, the source-of-truth hierarchy,
  and reporting discipline.
- `workflows/weekly-trading-report.md` — a **Workflow** (runnable via
  `/weekly-trading-report`): the step-by-step procedure, with the exact endpoints,
  dedupe key, stat formulas, and the bug-audit step.

They are designed to work together — the workflow tells Antigravity *what to do*,
the rule tells it *what to watch for*.

## Install (in Antigravity, on the `E:\Ai Stock` workspace)
Antigravity reads workspace customizations from the `.agents/` folder at the repo
/ git root. Copy the two files into place:

```
E:\Ai Stock\.agents\rules\trading-report-audit.md
E:\Ai Stock\.agents\workflows\weekly-trading-report.md
```

(Antigravity also keeps backward support for `.agent/rules`. Global equivalents:
Rules → `~/.gemini/GEMINI.md`; but workspace-scoped is better here.)

Then, in Antigravity: open the **Customizations** panel (the "..." menu at the top
of the agent panel).
- **Rules** tab: confirm `trading-report-audit` appears; set its activation to
  **Always On** (or **Model Decision** so it loads when the topic is relevant).
  Each rule file is capped at 12,000 characters.
- **Workflows** tab: confirm `weekly-trading-report` appears. Run it by typing
  `/weekly-trading-report` in the agent input.

## Notes / gotchas baked in
- The sandbox/agent shell can't reach `localhost` — the workflow tells it to query
  the backend through the browser tools.
- The file mount can serve stale copies — the rule makes the live API the source of
  truth and treats on-disk JSON state as suspect.
- If the server is down, it reports and stops instead of inventing numbers.
- It won't delete or rewrite state files without confirmation.

## Keeping it current
When you fix a new class of bug, add it to the failure-pattern catalog in the rule
so future runs check for it. Antigravity can also regenerate/extend the workflow
from a working session ("Agent-Generated Workflows").
