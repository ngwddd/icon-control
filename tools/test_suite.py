"""Emit complete, machine-readable results including every failure and skip."""
import argparse
import json
from pathlib import Path
import sys
import unittest
import subprocess

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'tests'))
parser=argparse.ArgumentParser();parser.add_argument('--pattern',default='test_*.py');args=parser.parse_args()
directory=root/'.runtime';directory.mkdir(exist_ok=True)
with (directory/'tests.log').open('w',encoding='utf-8') as stream:
    suite=unittest.defaultTestLoader.discover(str(root/'tests'),pattern=args.pattern)
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
report=dict(source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
            pattern=args.pattern,run=result.testsRun,failures=[dict(test=t.id(),trace=trace) for t,trace in result.failures],
            errors=[dict(test=t.id(),trace=trace) for t,trace in result.errors],
            skipped=[dict(test=t.id(),reason=reason) for t,reason in result.skipped])
(directory/'test-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(run=report['run'],failures=len(report['failures']),errors=len(report['errors']),skipped=len(report['skipped']))))
for item in report['failures']+report['errors']:print(item['test']+': '+item['trace'].strip().splitlines()[-1])
raise SystemExit(0 if result.wasSuccessful() and result.testsRun>len(result.skipped) else 1)
