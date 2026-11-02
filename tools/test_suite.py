"""Emit complete, machine-readable results including every failure and skip."""
import argparse
import json
from pathlib import Path
import sys
import unittest
import subprocess
import os
import time
import shutil

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'tests'))
parser=argparse.ArgumentParser();parser.add_argument('--pattern',default='test_*.py');args=parser.parse_args()
directory=root/'.runtime';directory.mkdir(exist_ok=True)
def source_head():
    return subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
def source_dirty():
    return bool(subprocess.check_output(['git','status','--porcelain','--untracked-files=all','--',
        '_patched','plugin','tools','tests','.github','pyproject.toml','VERSION','constraints-windows-py312.txt',
        'MANIFEST.in','panic_watch.py','macros','recipes','programs'],cwd=root,text=True).strip())
tested_commit=os.environ.get('ICON_CONTROL_TEST_SOURCE_SHA') or source_head()
dirty_at_start=source_dirty() or source_head()!=tested_commit
with (directory/'tests.log').open('w',encoding='utf-8') as stream:
    suite=unittest.defaultTestLoader.discover(str(root/'tests'),pattern=args.pattern)
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
report=dict(source_commit=tested_commit,
            source_dirty=dirty_at_start or source_dirty() or source_head()!=tested_commit,
            scope='full_suite' if args.pattern=='test_*.py' else 'selected_tests',
            pattern=args.pattern,run=result.testsRun,failures=[dict(test=t.id(),trace=trace) for t,trace in result.failures],
            errors=[dict(test=t.id(),trace=trace) for t,trace in result.errors],
            skipped=[dict(test=t.id(),reason=reason) for t,reason in result.skipped])
(directory/'test-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
archive=directory/'test-runs';archive.mkdir(exist_ok=True)
run_id=str(time.time_ns())
shutil.copyfile(directory/'test-results.json',archive/(run_id+'.json'))
shutil.copyfile(directory/'tests.log',archive/(run_id+'.log'))
print(json.dumps(dict(run=report['run'],failures=len(report['failures']),errors=len(report['errors']),skipped=len(report['skipped']))))
for item in report['failures']+report['errors']:print(item['test']+': '+item['trace'].strip().splitlines()[-1])
raise SystemExit(0 if result.wasSuccessful() and result.testsRun>len(result.skipped) else 1)
