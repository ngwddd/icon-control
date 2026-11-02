"""Build an isolated overlay and run selected tests; never patch the live host."""
from __future__ import annotations
import argparse
import ast
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--pattern', default='test_stability*.py')
    args = parser.parse_args()
    runtime = ROOT / '.runtime'
    package = runtime / 'computer_mcp'
    package.mkdir(parents=True, exist_ok=True)
    # The baseline repository is an overlay, not a complete distributable.
    base = importlib.util.find_spec('computer_mcp')
    if base and base.origin and package.resolve() not in Path(base.origin).resolve().parents:
        shutil.copytree(Path(base.origin).parent, package, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(ROOT / '_patched', package, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    state = runtime / 'state'
    state.mkdir(exist_ok=True)
    env = dict(os.environ, PYTHONPATH=str(runtime), PYTHONIOENCODING='utf-8',
               ICON_CONTROL_HOME=str(runtime), DSH_MOUSE_STATE=str(state / 'mouse-permission.json'),
               DSH_MOUSE_BRIDGE='off', DSH_E2E='0', DSH_LIVE='0')
    if args.baseline:
        code = ('import json; from computer_mcp import tool_registry as r; '
                'print(json.dumps([dict(name=s.name,zone=s.zone,read_only=s.read_only,'
                'schema=s.schema) for s in r.iter_specs()],ensure_ascii=False))')
        result = subprocess.run([sys.executable, '-c', code], env=env, cwd=ROOT,
                                capture_output=True, text=True, encoding='utf-8', check=True)
        tools = json.loads(result.stdout)
        count = 0
        for path in (ROOT / 'tests').glob('test_*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
            count += sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                         and n.name.startswith('test_') for n in ast.walk(tree))
        report = dict(source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                      version=(ROOT/'VERSION').read_text().strip(),tools=tools,
                      discovered_test_functions=count,
                      baseline_test_scope='test_v13_program.py; no desktop actions',
                      historical_full_suite='not reproduced; desktop tests require explicit opt-in')
        target = ROOT / 'docs' / 'v1.3' / 'baseline.json'
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        args.pattern='test_v13_program.py'
    return subprocess.call([sys.executable,str(ROOT/'tools'/'test_suite.py'),
                            '--pattern',args.pattern],cwd=ROOT,env=env)

if __name__ == '__main__':
    raise SystemExit(main())
