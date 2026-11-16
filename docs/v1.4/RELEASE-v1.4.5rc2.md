# v1.4.5 RC2 — audit remediation and automated validation

RC1 base: c4797168e5fff516bdb47dcd55f15fd75aba0552.
Stable base remains v1.4.4 (30cbae7feee4f965812260eda663484384ec363b).
Package version: 1.4.5rc2. The candidate remains separate from Stable.

## Audit fixes

- OCR/template clicks capture an explicit or default foreground HWND, process
  identity and geometry before recognition. The executor refuses a missing
  pre-observation binding instead of binding a later window at an old pixel.
  Read-only find_text/match_template retain desktop discovery. To click a
  different window, pass its HWND explicitly; omission now selects the captured
  foreground window, not an unbound desktop search.
- click_template exposes x/y/w/h in its schema, with dependentRequired enforcing
  all four or none. Dispatch rejects partial regions before recognition. Direct
  dictionary regions must also be complete.
- Performance reports separate verified successful-task latency from failed-task
  duration. Missing/unsupported results stay visible; success-rate denominators
  retain failures. Adapter and independent-verifier timings are separate from
  total task time. Legacy latency fields now describe successful tasks only.
- Result normalization carries tool context through dispatch and formatting.
  Unknown context and unverified mutations cannot become verified_success just
  from success=true. Read-only completion uses outcome=observed; the five action
  outcomes remain available. Independent postcondition evidence is required for
  verified_success. Cancellation/partial-input evidence remains intact.
- Preserve the formatter's established consumption of extra image blocks.

## Validation

RC1's no-test handoff no longer applies: the owner authorized the implementation
agent to build packages, run tests and execute Windows CI for RC2.

The candidate workflow now runs the full suite, dependency consistency,
97-tool schema snapshot checks, official stdio/HTTP interoperability, a native
window probe, and an isolated installation/upgrade/rollback probe. The latter
upgrades v1.4.4 to RC2 with an emergency stop already latched, checks configuration
generation and bad-hash refusal, and rolls back while preserving that stop.

Native probe scope: 100 occlusions, 100 geometry changes and 100 destroyed-window
cases use real HWND/process/ownership APIs and a simulated input sink. A separate
positive case requests actual guarded input and independently counts the
fixture's window messages. The report labels these two kinds of evidence.
300 refused attempts do not establish a zero real-world error rate.

Every final claim must be checked against the workflow run for the exact
candidate commit. Artifacts contain test-results.json, tests.log,
protocol/protocol-smoke.json, native-window-report.json and install-report.json.
Wheel and source archives are in the icon-control-candidate artifact. A
successful workflow does not prove competitive performance or all monitor/DPI
combinations.

The initial validation iteration found 3 failures and 3 errors in 1,012 tests.
It identified an in-place response compatibility regression and outdated
fake-HWND fixtures. These were corrected rather than skipped. The final
workflow artifacts are authoritative for the current result and skip reasons.

## Remaining evidence limits

No measured competitor advantage is claimed. Windows-MCP, desktop-touch-mcp and
desk-mcp task adapters and comparative results remain separate baseline work.
The new benchmark framework itself has automated regression coverage.
Wide DPI/multi-monitor matrices, actual user takeover hardware, long-running
UIA fault isolation and application-specific workflows require their own
recorded trials. Conditional architecture work remains evidence-gated.
