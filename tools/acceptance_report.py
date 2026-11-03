"""Assemble docs/v1.3/acceptance.json from the raw S5 evidence files.

The release gate trusts a report only when every claim is backed by a hashed
raw file bound to the same commit. This tool is the only thing that builds that
report, so no one hand-edits evidence paths or timings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', type=Path, default=ROOT / 'docs/v1.3/evidence/s5')
    parser.add_argument('--unit', type=Path, default=ROOT / '.runtime/test-results.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/v1.3/acceptance.json')
    parser.add_argument('--review', type=Path, help='independent review JSON, when one exists')
    args = parser.parse_args()

    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    newest: dict[str, tuple[float, Path, dict]] = {}
    for path in sorted(args.evidence.glob('B*.json')):
        try:
            raw = load(path)
        except (OSError, ValueError):
            continue
        case = raw.get('case_id') or path.stem
        stamp = float(raw.get('timestamp') or 0)
        if case not in newest or stamp > newest[case][0]:
            newest[case] = (stamp, path, raw)

    tasks = []
    for case, (_stamp, path, raw) in sorted(newest.items()):
        fresh = (raw.get('source_commit') == commit and raw.get('source_dirty') is False
                 and raw.get('kind') == 'real_desktop' and raw.get('simulated') is False)
        passed = raw.get('status') == 'passed' and fresh
        tasks.append(dict(
            id=case,
            status='passed' if passed else ('stale' if not fresh else 'failed'),
            elapsed_ms=raw.get('elapsed_ms'),
            environment=raw.get('environment'),
            application_state=raw.get('application_state'),
            evidence=dict(path=str(path.relative_to(ROOT)), sha256=digest(path)),
        ))

    unit = None
    if args.unit.is_file():
        raw_unit = load(args.unit)
        unit = dict(path=str(args.unit.relative_to(ROOT)), sha256=digest(args.unit))
    else:
        raw_unit = {}

    review = None
    if args.review and args.review.is_file():
        review = load(args.review)

    passed = [task for task in tasks if task['status'] == 'passed']
    report = {
        'version': (ROOT / 'VERSION').read_text(encoding='utf-8').strip(),
        'source_commit': commit,
        'status': 'passed' if len(passed) == 32 else 'blocked',
        'p0_review': (review or {}).get('status', 'pending'),
        'clean_windows_install': 'pending',
        'known_false_success_paths': None,
        'unit_failures': len(raw_unit.get('failures', [])),
        'unit_errors': len(raw_unit.get('errors', [])),
        'unit_skipped': len(raw_unit.get('skipped', [])),
        'unit_evidence': unit,
        'desktop_tasks': tasks,
    }
    if review:
        report['independent_review'] = review
        report['implementer_id'] = review.get('implementer_id')
        report['p0_review'] = 'passed' if review.get('status') == 'passed' else 'pending'

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(
        output=str(args.output), version=report['version'], commit=commit[:8],
        passed=len(passed), total=len(tasks), status=report['status'],
    ), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
