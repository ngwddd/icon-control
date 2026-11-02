"""Wait for a human-scoped grant, then run every real smoke test on one fixture."""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

parser=argparse.ArgumentParser()
parser.add_argument('--home',type=Path,required=True)
parser.add_argument('--state',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--wait',type=float,default=180)
parser.add_argument('--start-signal',type=Path)
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
os.environ.update(ICON_CONTROL_HOME=str(args.home),DSH_MOUSE_STATE=str(args.home/'state'/'mouse-permission.json'),
                  DSH_E2E='1',ICON_CONTROL_E2E_STATE=str(args.state),PYTHONIOENCODING='utf-8')
from computer_mcp import agent_session,permission,control,input_guard
import computer_mcp
for source in (root/'_patched').rglob('*.py'):
    if '__pycache__' in source.parts: continue
    installed=Path(computer_mcp.__file__).parent/source.relative_to(root/'_patched')
    if not installed.is_file() or hashlib.sha256(source.read_bytes()).digest()!=hashlib.sha256(installed.read_bytes()).digest():
        raise RuntimeError('Installed candidate differs from source: '+str(source.relative_to(root)))
identity=agent_session.register('Desktop smoke: approve this test process')
report=dict(source_commit=source_commit,kind='real_desktop',simulated=False,agent_session=identity['id'],
            started=time.time(),results=[])
print(json.dumps(dict(waiting_for_human=True,agent=identity['label'],session=identity['id'][:10])),flush=True)
deadline=time.monotonic()+args.wait
while time.monotonic()<deadline and not permission.status().get('granted'):time.sleep(.2)
if args.start_signal and permission.status().get('granted'):
    while time.monotonic()<deadline and not args.start_signal.exists():time.sleep(.2)
    if not args.start_signal.exists():
        raise RuntimeError('Operator start acknowledgement not received; no desktop tests executed')
    print('Operator acknowledged; desktop smoke starts in 3 seconds',flush=True)
    time.sleep(3)
if not permission.status().get('granted'):
    report.update(error='Human approval not received',run=0,failures=[],errors=[],skipped=[])
    code=2
else:
    sys.path.insert(0,str(root/'tests'))
    module=importlib.import_module('test_e2e_smoke')
    suite=unittest.defaultTestLoader.loadTestsFromModule(module)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.with_suffix('.log').open('w',encoding='utf-8') as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    report.update(run=result.testsRun,failures=[dict(test=t.id(),trace=trace) for t,trace in result.failures],
                  errors=[dict(test=t.id(),trace=trace) for t,trace in result.errors],
                  skipped=[dict(test=t.id(),reason=reason) for t,reason in result.skipped],
                  observations=module.TestE2E.observations)
    code=0 if result.wasSuccessful() and result.testsRun==3 and not result.skipped else 1
input_guard.release_all()
control.release('Desktop smoke ended')
report['finished']=time.time()
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(exit_code=code,run=report['run'],failures=len(report['failures']),
                     errors=len(report['errors']),evidence=str(args.output))),flush=True)
raise SystemExit(code)
