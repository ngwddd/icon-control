"""Run interleaved, same-machine task adapters with separate result verifiers.

No project is installed or launched implicitly. Commands are argv arrays in a
local config. Missing adapters are unsupported, never omitted from the report.
This runner does not rank competitors or treat adapter self-reports as success.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import random
import subprocess
import time
import uuid

SCENARIOS = {
    'T01': 'Native UIA form: field values and final application state',
    'T02': 'Explorer selection/menu/move: independent file-system result',
    'T03': 'Browser form: page or local test-server receipt',
    'T04': 'Electron/custom UI OCR: intended control event receipt',
    'T05': 'Duplicate/occluded/switched target: no wrong-window input',
    'T06': 'Long-list scroll/cross-window drag: final item or business state',
}
COUNTERS = ('tool_calls', 'request_bytes', 'response_bytes', 'input_tokens',
            'output_tokens', 'ocr_calls', 'uia_calls', 'screenshot_calls',
            'wrong_target_events', 'human_interventions', 'recoveries', 'retries')


def command(argv, context, timeout):
    if (not isinstance(argv, list) or not argv
            or not all(isinstance(item, str) for item in argv)):
        raise ValueError('Commands must be nonempty argv arrays; shell syntax is unsupported')
    began = time.perf_counter()
    try:
        proc = subprocess.run(argv, input=json.dumps(context), capture_output=True,
                              text=True, encoding='utf-8', timeout=timeout,
                              shell=False)
    except subprocess.TimeoutExpired:
        return dict(ok=False, reason='command_timeout', elapsed_ms=(time.perf_counter()-began)*1000)
    try:
        payload = json.loads(proc.stdout)
    except (ValueError, TypeError):
        payload = None
    return dict(ok=proc.returncode == 0, returncode=proc.returncode,
                elapsed_ms=(time.perf_counter()-began)*1000, payload=payload,
                # Only synthetic fixture output belongs in benchmark evidence.
                stdout=proc.stdout, stderr=proc.stderr)


def counters(payload):
    values = payload.get('metrics', {}) if isinstance(payload, dict) else {}
    if not isinstance(values, dict):
        values = {}
    return {name: (value if isinstance(value, int) and not isinstance(value, bool)
                   and value >= 0 else None)
            for name in COUNTERS for value in [values.get(name)]}


def run_one(config, project, task_id, repeat, run_id, machine):
    tasks = config.get('tasks', {})
    task = tasks.get(task_id, {})
    adapter = task.get('adapters', {}).get(project)
    project_meta = config['projects'][project]
    row = dict(run_id=run_id, task_id=task_id, project=project, repeat=repeat,
               level=config['level'], machine_profile=machine,
               version=project_meta['version'], commit_sha=project_meta['commit_sha'],
               model_id=config.get('model_id'), status='unsupported',
               task_success=False, verified_result=None, latency_ms=None,
               metrics={name: None for name in COUNTERS})
    if not adapter:
        row['failure_reason'] = 'adapter_not_configured'
        return row
    if not task.get('setup') or not task.get('verify') or not task.get('reset'):
        row.update(status='failed', failure_reason='missing_independent_fixture_command')
        return row
    sample_id = uuid.uuid4().hex
    row['sample_id'] = sample_id
    context = dict(task_id=task_id, project=project, repeat=repeat, run_id=run_id, sample_id=sample_id,
                   seed=config['seed'], level=config['level'])
    timeout = config.get('timeout_seconds', 60)
    began = None
    row['status'] = 'failed'
    row['evidence'] = {}
    try:
        row['evidence']['setup'] = command(task['setup'], context, timeout)
        if not row['evidence']['setup']['ok']:
            row['failure_reason'] = 'setup_failed'
            return row
        began = time.perf_counter()
        run = row['evidence']['adapter'] = command(adapter, context, timeout)
        row['metrics'] = counters(run.get('payload'))
        # Even failed/partial execution is observed, but never counted as a pass.
        verify = row['evidence']['verifier'] = command(task['verify'], context, timeout)
        row['latency_ms'] = (time.perf_counter()-began)*1000
        payload = verify.get('payload')
        verified = (verify['ok'] and isinstance(payload, dict)
                    and payload.get('verified') is True
                    and payload.get('run_id') == run_id
                    and payload.get('sample_id') == sample_id)
        row['verified_result'] = payload
        passed = run['ok'] and verified
        row.update(status='success' if passed else 'failed', task_success=passed,
                   failure_reason=None if passed else 'adapter_or_independent_verification_failed')
    except (OSError, ValueError, TypeError) as exc:
        row.update(failure_reason=type(exc).__name__)
    finally:
        if began is not None and row['latency_ms'] is None:
            row['latency_ms'] = (time.perf_counter()-began)*1000
        try:
            reset = command(task['reset'], context, timeout)
        except (OSError, ValueError, TypeError) as exc:
            reset = dict(ok=False, reason=type(exc).__name__)
        row['evidence']['reset'] = reset
        if not reset['ok']:
            row.update(status='failed', task_success=False, failure_reason='reset_failed')
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding='utf-8-sig'))
    if cfg.get('level') not in ('L1', 'L2', 'L3'):
        raise ValueError('Set one benchmark level L1/L2/L3 per run')
    if cfg['level'] == 'L3' and not (cfg.get('model_id') and cfg.get('inference_budget')):
        raise ValueError('L3 requires the same recorded model and inference budget')
    repeats = cfg.get('repeats', 20)
    if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats < 1:
        raise ValueError('repeats must be a positive integer')
    timeout = cfg.get('timeout_seconds', 60)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('timeout_seconds must be positive and finite')
    projects = cfg.get('projects', {})
    if not isinstance(projects, dict) or len(projects) < 2:
        raise ValueError('Configure at least a baseline and a candidate')
    for metadata in projects.values():
        if not (isinstance(metadata, dict) and metadata.get('version') and metadata.get('commit_sha')):
            raise ValueError('Every project needs exact version and commit_sha')
    for key in ('display_profile', 'application_versions', 'dependency_versions'):
        if not cfg.get(key):
            raise ValueError('Record ' + key + ' for same-machine comparisons')
    cfg.setdefault('seed', 145)
    machine = dict(os=platform.platform(), architecture=platform.machine(),
                   python=platform.python_version(), display=cfg['display_profile'],
                   applications=cfg['application_versions'], dependencies=cfg['dependency_versions'])
    run_id = uuid.uuid4().hex
    args.output.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents mixing samples from different experiments.
    path = args.output / (run_id + '.jsonl')
    rng = random.Random(cfg['seed'])
    with path.open('x', encoding='utf-8') as stream:
        manifest = dict(record_type='manifest', run_id=run_id, machine_profile=machine,
                        recorded_at=datetime.now(timezone.utc).isoformat(),
                        config_sha256=hashlib.sha256(args.config.read_bytes()).hexdigest(),
                        config=cfg, scenarios=SCENARIOS)
        stream.write(json.dumps(manifest, ensure_ascii=False) + '\n')
        stream.flush()
        for repeat in range(repeats):
            for task_id in SCENARIOS:
                order = list(projects)
                rng.shuffle(order)
                for project in order:
                    row = run_one(cfg, project, task_id, repeat, run_id, machine)
                    stream.write(json.dumps(row, ensure_ascii=False) + '\n')
                    stream.flush()
                    if row.get('failure_reason') == 'reset_failed':
                        raise RuntimeError('Fixture reset failed; stopped to avoid contaminating subsequent runs')
    print(path)


if __name__ == '__main__':
    main()
