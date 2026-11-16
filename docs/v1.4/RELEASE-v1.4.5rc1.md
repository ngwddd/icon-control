# v1.4.5 RC1 — Project Precision

Base: v1.4.4 Stable, commit `30cbae7feee4f965812260eda663484384ec363b`.
Package version: `1.4.5rc1` (the requested 1.45 RC).

Implementation only. No build, tests, desktop acceptance or competitor benchmark
was executed for this change. The owner performs validation and release approval.
This document does not declare Stable readiness or performance leadership.

## Changes

- UIA/OCR/template clicks use a shared constrained executor. No TypeError retry
  may turn a bound click into unbound input. HWND, process creation identity,
  window geometry and exact pointer position are checked. Template button-down
  retains its 60 ms hold. Partial/uncertain execution blocks automatic retry.
- Default ui_click HWND is captured before the UIA name/element-id lookup.
- click_text.index has no schema default. Omission means automatic ambiguity
  handling; explicit 0 selects candidate zero. The stored schema oracle follows.
- wait_template uses a monotonic deadline. A disappearance timeout is timeout,
  never absent; ambiguous/failed final observations remain inconclusive.
- Additive `outcome`: verified_success, executed_unverified, refused, failed,
  cancelled. Existing ok/success/status/verdict fields remain available.
- Local client JSON generator: `icon-control config`. It provisions no grants
  or credentials and does not clear stop state.
- Installer supports optional `-ExpectedSha256` before staging.
- Configurable benchmark runner, independent verifiers, unique sample receipts,
  raw JSONL, per-layer P50/P95 and Wilson success intervals.

## Result migration

Consumers should prefer outcome over legacy success alone. For wait_template,
legacy success=true means the polling API completed; matched=false and
outcome=failed mean the requested condition was not established.

For input tools, executed_unverified means submitted events, not business success.
action_executed=null means an input attempt raised and execution is uncertain.
Do not automatically retry. cancelled may still have action_executed=true when a
stop interrupted settling or cleanup after button-down.

Observation-only verified_success has verification_scope=tool_completion. It
does not prove an earlier click changed a page. Explicit verified postconditions
keep their existing status/verification fields.

MCP entry points share the taxonomy for stdio and HTTP. Direct Python calls
through existing execution boundaries also receive it. Arbitrary exception
messages remain masked at the MCP boundary.

## Pending owner validation

See [ACCEPTANCE-v1.4.5.md](ACCEPTANCE-v1.4.5.md).
The benchmark runner is an adapter framework: task fixture commands, competitor
adapters and real measurements must be supplied and executed by the owner.
No UIA worker isolation, new semantic MCP tool, visual diff engine, or
cross-process input lease was added without the required baseline evidence.
