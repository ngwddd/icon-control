# Owner validation — v1.4.5 RC1

RC1 status: implementation only. For RC2 the owner authorized the implementation
agent to run tests, builds and CI. The current automated validation contract and
evidence locations are in RELEASE-v1.4.5rc2.md; use the exact commit's workflow
artifacts for results. Items below define the wider acceptance matrix and are
not all implied by automated CI.

Use an isolated Windows test environment and synthetic application data. Install
the RC from its actual GitHub commit before invoking the checks below.

1. Run the existing full suite and new test_v145_* tests. Some legacy recognition
   mocks need window/process identity fixtures now that clicks bind before lookup.
2. Build wheel/sdist and confirm VERSION, project metadata and runtime version
   all report 1.4.5rc1. Keep source commit, dependency versions and hashes.
3. Check the stored tools snapshot and the stdio/HTTP contracts from the same
   installed package. There remain 97 public tools.
4. Exercise click_text, ui_click and click_template with TypeError before input,
   after button-down, during release, and during settling. No second press is
   allowed. Check uncertain execution and cleanup flags.
5. Repeat default ui_click resolution while the foreground window changes.
   Include PID/HWND reuse, process restart, movement and occlusion.
6. Compare omitted click_text.index with explicit zero and client-generated
   defaults. Duplicate equal OCR candidates must be refused when index is absent.
7. Test template appearance/disappearance success, always-present disappearance
   timeout, ambiguous matches, failed capture and zero timeout.
8. Exercise user takeover, emergency stop and revocation during click/hold/settle.
   Check held button cleanup and confirm that no automatic retry occurs.
9. Verify config JSON points at the intended Python and ICON_CONTROL_HOME.
   Test fresh installation, upgrade and rollback with a pending stop. Test an
   intentionally wrong -ExpectedSha256 before installing a wheel.
10. Supply independent T01–T06 fixtures/adapters, then run the benchmark
    framework described in tools/bench/scenarios/README.md. Record unsupported
    tasks, raw samples, displays, app versions, commit SHAs and dependencies.

Suggested release gates remain those in the supplied v1.4.5 research plan:
full regression and protocol consistency, targeted wrong-window injection
coverage, real task success, cancellation cleanup, same-machine baselines,
and independent audit. Their completion is not implied by code delivery.
