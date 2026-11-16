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
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FALLBACK_TOOLS = 90


def expected_tools() -> int:
    """The tool count the running package actually publishes (no hardcoding)."""
    try:
        from computer_mcp import tool_registry
        return len(tool_registry.all_tools())
    except Exception:
        return 0


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


def check_tag(errors: list[str], version: str | None, tag: str | None,
              stable: bool = False) -> None:
    """Bind release identity to the version, not just three matching sources."""
    if tag is not None:
        if not re.fullmatch(r'v\d+\.\d+\.\d+(?:rc\d+)?', tag):
            errors.append('Invalid release tag: expected vX.Y.Z or vX.Y.ZrcN')
        elif tag[1:] != version:
            errors.append(f'Release tag {tag!r} does not match package version {version!r}')
        # A stable-looking tag cannot wrap any pre-release package.
        if re.fullmatch(r'v\d+\.\d+\.\d+', tag):
            stable = True
    if stable:
        if tag is None:
            errors.append('A stable release requires an explicit release tag')
        if not version or not re.fullmatch(r'\d+\.\d+\.\d+', version):
            errors.append('Stable release cannot contain a prerelease/dev/local package')
        if tag and not re.fullmatch(r'v\d+\.\d+\.\d+', tag):
            errors.append('Stable release cannot use a prerelease tag')


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
    expected = expected_tools() or FALLBACK_TOOLS
    for transport in ("stdio", "http"):
        part = report.get(transport) or {}
        if part.get("tools") != expected:
            errors.append(f'{transport}: expected {expected} tools, got {part.get("tools")}')
        if version and part.get("server_version") != version:
            errors.append(f'{transport}: server version {part.get("server_version")!r} != {version!r}')
    if report.get("http_unauthenticated_status") != 401:
        errors.append("HTTP without credentials must answer 401")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-commit", default=None)
    parser.add_argument("--expected-tag", default=None)
    parser.add_argument("--stable", action="store_true")
    parser.add_argument("--version-only", action="store_true",
                        help="Check release identity before any build or publish step")
    args = parser.parse_args()
    commit = args.expected_commit or ""
    errors: list[str] = []
    version = check_version(errors)
    tag = args.expected_tag
    if tag is None and os.environ.get('GITHUB_REF_TYPE') == 'tag':
        tag = os.environ.get('GITHUB_REF_NAME')
    check_tag(errors, version, tag, args.stable)
    if not args.version_only:
        check_tests(errors, commit)
        check_protocol(errors, version)
    if errors:
        for line in errors:
            print(f"BLOCKED: {line}")
        print(f"{len(errors)} blocker(s); the release may not be promoted.")
        return 1
    if args.version_only:
        print(f"PASS: release identity {tag or version} matches source version {version}.")
    else:
        print(f"PASS: {version} automated release evidence is valid (commit {commit[:8] or 'unbound'}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
