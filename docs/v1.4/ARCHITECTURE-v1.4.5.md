# v1.4.5 RC1 implementation scope

Recognition stays in ui_ext, ocr_ext and vision_state. WindowBinding captures an
HWND, process record (PID, creation time, executable) and rectangle before
explicit-window recognition. ui_click also captures the default foreground HWND.
Screen-wide OCR/template searches bind the resolved point's owner before moving.
They do not claim to establish business identity from text or image confidence.

pointer_contract.click_at validates identity/geometry/ownership, positions the
pointer, then delegates constraints to input_guard.MouseController. That existing
controller rechecks control authority, expected point, expected process and
top-level window immediately before press. There is no unconstrained fallback.
Failures after entering input are uncertain unless completed input is known.
Cleanup releases only this controller's recorded held inputs, without retrying
the click. OS scheduling races and same-process HWND reuse remain limitations.

result_outcome.normalize adds classification at direct API, dispatch and MCP
response boundaries. Legacy fields are retained. Observations and verified
business postconditions are distinguished by scope and existing verification
fields. This is an additive compatibility change.

The benchmark framework uses separately configured setup/action/verify/reset
commands. It randomizes project order within each task repetition and requires
independent verifier receipts bound to a unique sample ID. It cannot infer
missing RPC/token counters and does not fabricate competitor adapters.

Conditional work from the research plan remains pending measurement: advanced
target APIs, post-action diffs, UIA isolation and cross-process input leases.
