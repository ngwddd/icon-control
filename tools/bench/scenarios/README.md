# v1.4.5 task adapter contract

This is a configurable benchmark runner, not a completed competitor benchmark.
No competitor integration or real desktop result is claimed by this RC.

Run from the repository root. Create a local JSON config with:

- `level`: L1, L2 or L3; never mix layers.
- `repeats`: 20 by default; `seed`: 145 by default.
- `timeout_seconds`: per command timeout, default 60.
- `projects`: map each project label to its exact `version` and `commit_sha`.
- `display_profile`: resolution, scaling, monitor layout, negative coordinates.
- `application_versions`, `dependency_versions`: exact installed versions.
- L3 additionally requires `model_id` and `inference_budget`.
- `tasks`: T01 through T06. Each task contains `setup`, `verify`, `reset`
  argv arrays and an `adapters` map of project label to argv array.
  Unconfigured adapters are recorded as unsupported in every round.

Commands read one JSON object on stdin containing task_id, project, repeat,
run_id, sample_id, seed and level. Use synthetic applications and temporary test data.
Setup must establish the same initial state for every project. Adapters execute
the task through each project's recommended API. Verifiers independently read
application state, test-server receipts or files; never grade the adapter's own
success field. A verifier must exit zero and output
`{"verified": true, "run_id": "<current run_id>", "sample_id": "<current sample_id>"}`
to pass. The unique sample ID prevents a receipt from a preceding run passing.
Reset must clean only the fixture state. A reset failure aborts the experiment.
Commands must terminate their descendants before returning; subprocess timeouts
only stop the direct command. Do not launch detached desktop agents from adapters.

Optional adapter output: `{"metrics": {"tool_calls": 5, "request_bytes": 100}}`.
Supported counters are declared in competitor_runner.COUNTERS. Unavailable
measurements remain null, never zero. Counter telemetry is self-reported and must
be backed by RPC logs before publishing call/token/cost comparisons.
The runner records raw command output: do not use personal desktop content,
credentials or production documents.

```powershell
py -3.12 tools/bench/competitor_runner.py local-bench.json --output .runtime/bench/v145
py -3.12 tools/bench/report_generator.py .runtime/bench/v145/<run_id>.jsonl --output report.json
```

T01: native UIA form; verify field values and final app state.
T02: Explorer operations; verify filesystem effects and selected target.
T03: browser form; verify local server receipt or independently read page state.
T04: custom/Electron OCR; verify the actual intended control's event.
T05: duplicate/occluded/switched windows; verify no wrong-window input.
T06: long-list scroll/drag; verify final item position or business state.

Repeat with DPI 125/150/200/250%, secondary displays, focus switches, pointer
takeover, cancellation, duplicate OCR, UIA timeout, stale frames and concurrent
clients. Fault injection and competitor adapters are supplied by the operator.
Twenty clean repetitions do not establish a zero real-world error rate.
