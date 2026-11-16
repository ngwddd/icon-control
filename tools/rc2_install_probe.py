"""Install a baseline and RC wheel under one disposable root, preserve stop, roll back."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run(argv, env, timeout=180):
    process = subprocess.run(list(map(str, argv)), env=env, cwd=ROOT, capture_output=True,
                             encoding='utf-8', errors='replace', timeout=timeout)
    if process.returncode:
        raise RuntimeError('Command failed: ' + repr(argv) + '\n' + process.stdout + process.stderr)
    return process.stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline-wheel', type=Path, required=True)
    parser.add_argument('--candidate-wheel', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    runtime = ROOT / '.runtime'
    runtime.mkdir(exist_ok=True)
    baseline, candidate = args.baseline_wheel.resolve(), args.candidate_wheel.resolve()
    report = dict(kind='isolated_install_upgrade_rollback', baseline=baseline.name,
                  candidate=candidate.name, candidate_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),
                  source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip())
    with tempfile.TemporaryDirectory(prefix='installer-', dir=runtime) as folder:
        home = Path(folder).resolve()
        if home.parent != runtime.resolve():
            raise RuntimeError('Installation fixture escaped its intended parent')
        env = dict(os.environ, ICON_CONTROL_HOME=str(home), ICON_CONTROL_POLICY='local',
                   PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
        # Child installers create only managed paths below the disposable root.
        installer = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                     '-File', ROOT / 'tools/install.ps1', '-InstallRoot', home]
        def install(wheel):
            digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
            return run(installer + ['-Python', sys.executable, '-Wheel', wheel,
                                    '-ExpectedSha256', digest], env)
        python = home / 'current/Scripts/python.exe'
        code = ("import json,computer_mcp,sys; from computer_mcp import permission,security;"
                "print(json.dumps(dict(version=computer_mcp.__version__,prefix=sys.prefix,"
                "granted=permission.status()['granted'],stop=(security.data_home()/'state'/'emergency-stop.json').exists())))")
        def state():
            return json.loads(run([python, '-I', '-c', code], env).strip())
        try:
            report['baseline_install'] = install(baseline)
            first = report['baseline_state'] = state()
            run([python, '-I', '-c', 'from computer_mcp import security; security.latch_stop()'], env)
            stopped = state()
            if stopped['granted'] or not stopped['stop']:
                raise AssertionError('Fixture emergency stop did not latch')
            report['upgrade_install'] = install(candidate)
            upgraded = report['upgraded_state'] = state()
            if upgraded['version'] != '1.4.5rc2' or upgraded['granted'] or not upgraded['stop']:
                raise AssertionError('Upgrade changed pending stop or installed the wrong version')
            config = report['generated_config'] = json.loads(run([python, '-I', '-m', 'computer_mcp.launcher', 'config'], env))
            if config['mcpServers']['icon-control']['env']['ICON_CONTROL_HOME'] != str(home):
                raise AssertionError('Generated client configuration points outside the fixture')
            bad = subprocess.run(list(map(str, installer + ['-Python', sys.executable,
                    '-Wheel', candidate, '-ExpectedSha256', '0' * 64])), env=env, cwd=ROOT,
                    capture_output=True, encoding='utf-8', errors='replace', timeout=30)
            report['bad_hash_refused'] = bad.returncode != 0
            if not report['bad_hash_refused']:
                raise AssertionError('Installer accepted a wrong hash')
            report['rollback'] = run(installer + ['-Rollback'], env)
            rolled = report['rolled_back_state'] = state()
            if rolled['version'] != first['version'] or rolled['granted'] or not rolled['stop']:
                raise AssertionError('Rollback did not restore the baseline and preserve pending stop')
            report['passed'] = True
        except Exception as exc:
            report.update(passed=False, error=type(exc).__name__ + ': ' + str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
