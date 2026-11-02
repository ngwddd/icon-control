"""Refuse a formal release without complete desktop and P0 acceptance evidence."""
import argparse
import hashlib
import json
from pathlib import Path

def evaluate(report,root):
    errors=[]
    if report.get('p0_review')!='passed':errors.append('P0 independent acceptance missing')
    if report.get('clean_windows_install')!='passed':errors.append('Clean Windows account installation missing')
    if report.get('known_false_success_paths')!=0:errors.append('False-success audit incomplete')
    if report.get('unit_failures',1)!=0 or report.get('unit_errors',1)!=0:errors.append('Automated regression failed')
    cases={case.get('id'):case for case in report.get('desktop_tasks',[])}
    for number in range(1,33):
        name=f'B{number:02}';case=cases.get(name,{})
        if case.get('status')!='passed':errors.append(name+' desktop task not passed');continue
        if not isinstance(case.get('elapsed_ms'),(int,float)) or case['elapsed_ms']<0:
            errors.append(name+' timing missing')
        if not case.get('environment') or not case.get('application_state'):
            errors.append(name+' environment or application-state oracle missing')
        evidence=case.get('evidence',{})
        path=(root/str(evidence.get('path',''))).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():errors.append(name+' evidence missing');continue
        if hashlib.sha256(path.read_bytes()).hexdigest()!=evidence.get('sha256'):errors.append(name+' evidence hash mismatch')
    return errors

def main():
    parser=argparse.ArgumentParser();parser.add_argument('report',type=Path);args=parser.parse_args()
    if not args.report.is_file():print('BLOCKED: acceptance report missing');return 2
    errors=evaluate(json.loads(args.report.read_text(encoding='utf-8')),args.report.parent)
    for error in errors:print('BLOCKED: '+error)
    if errors:return 2
    print('Acceptance evidence complete; human release review still required.');return 0

if __name__=='__main__':raise SystemExit(main())
