"""Release readiness gate for the headless line.

v1.4 removed the human-approval flow, and with it the 32-item approval
benchmark. What still gates a release is that the artefact is the code that was
tested, that the suite is green, and that the MCP transports speak the same tool
contract. Run it from the repository root:

    python tools/release_gate.py --expected-commit <sha>

Exit code 0 means the release may be promoted; 1 means blocked (each blocker is
printed as a BLOCKED line).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS_EXPECTED = 90


def _version_from(path: Path, pattern: str) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(pattern, text, re.MULTILINE)
    return match.group(1) if match else None


def check_version(errors: list[str]) -> str | None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip() if (ROOT / "VERSION").exists() else ""
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:rc\d+)?", version):
        errors.append(f'VERSION is not a release version: {version!r}')
        return None
    pyproject = _version_from(ROOT / "pyproject.toml", r'^version\s*=\s*"([^"]+)"')
    package = _version_from(ROOT / "_patched/__init__.py", r'__version__\s*=\s*"([^"]+)"')
    for label, value in (("pyproject.toml", pyproject), ("_patched/__init__.py", package)):
        if value != version:
            errors.append(f'{label} version {value!r} != VERSION {version!r}')
    return version


def check_tests(errors: list[str], expected_commit: str) -> None:
    path = ROOT / ".runtime/test-results.json"
    if not path.exists():
        errors.append("automated regression report missing (.runtime/test-results.json)")
        return
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        errors.append("automated regression report is not valid JSON")
        return
    if report.get("source_commit") != expected_commit:
        errors.append("regression report is bound to a different commit")
    if report.get("source_dirty") is not False:
        errors.append("regression ran against a dirty tree")
    if report.get("failures") or report.get("errors"):
        errors.append("regression reported failures or errors")
    if int(report.get("run") or 0) <= 0:
        errors.append("regression ran no tests")
    if report.get("scope") != "full_suite" or report.get("pattern") != "test_*.py":
        errors.append("regression did not run the full suite")


def check_protocol(errors: list[str], version: str | None) -> None:
    path = ROOT / ".runtime/protocol/protocol-smoke.json"
    if not path.exists():
        errors.append("MCP protocol smoke report missing (.runtime/protocol/protocol-smoke.json)")
        return
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        errors.append("protocol smoke report is not valid JSON")
        return
    for transport in ("stdio", "http"):
        part = report.get(transport) or {}
        if part.get("tools") != TOOLS_EXPECTED:
            errors.append(f'{transport}: expected {TOOLS_EXPECTED} tools, got {part.get("tools")}')
        if version and part.get("server_version") != version:
            errors.append(f'{transport}: server version {part.get("server_version")!r} != {version!r}')
    if report.get("http_unauthenticated_status") != 401:
        errors.append("HTTP without credentials must answer 401")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-commit", default=None)
    args = parser.parse_args()
    commit = args.expected_commit or ""
    errors: list[str] = []
    version = check_version(errors)
    check_tests(errors, commit)
    check_protocol(errors, version)
    if errors:
        for line in errors:
            print(f"BLOCKED: {line}")
        print(f"{len(errors)} blocker(s); the release may not be promoted.")
        return 1
    print(f"PASS: {version} is ready to be promoted (commit {commit[:8] or 'unbound'}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
