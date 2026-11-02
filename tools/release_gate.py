"""Formal release requires SHA-bound independent review and raw, complete evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import math

def evidence_file(evidence, root, errors, label):
    path=(root/str(evidence.get('path',''))).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        errors.append(label+' evidence missing');return None
    if hashlib.sha256(path.read_bytes()).hexdigest()!=evidence.get('sha256'):
        errors.append(label+' evidence hash mismatch');return None
    return path

def evaluate(report,root,expected_commit=None):
    errors=[]
    source=report.get('source_commit')
    if not expected_commit or not re.fullmatch(r'[0-9a-f]{40}',str(source or '')) or source!=expected_commit:
        errors.append('Evidence is not bound to the expected source commit')
    if report.get('p0_review')!='passed':errors.append('P0 independent acceptance missing')
    review=report.get('independent_review',{})
    if (review.get('status')!='passed' or review.get('source_commit')!=expected_commit or
            not review.get('reviewer_id') or not report.get('implementer_id') or
            review.get('reviewer_id')==report.get('implementer_id') or
            review.get('open_p0')!=0 or review.get('open_p1')!=0):
        errors.append('Independent reviewer identity, exact commit or unresolved findings invalid')
    review_path=evidence_file(review.get('evidence',{}),root,errors,'Independent review')
    if review_path:
        try:
            raw_review=json.loads(review_path.read_text(encoding='utf-8'))
            if (raw_review.get('source_commit')!=expected_commit or raw_review.get('status')!='passed' or
                    raw_review.get('reviewer_id')!=review.get('reviewer_id') or
                    raw_review.get('implementer_id')!=report.get('implementer_id') or
                    raw_review.get('open_p0')!=0 or raw_review.get('open_p1')!=0 or
                    any(f.get('severity') in ('P0','P1') and f.get('status')!='resolved'
                        for f in raw_review.get('findings',[]))):
                errors.append('Raw independent review does not support the release claim')
        except (ValueError,TypeError,AttributeError):errors.append('Raw independent review is invalid')
    if report.get('clean_windows_install')!='passed':errors.append('Clean Windows account installation missing')
    if report.get('known_false_success_paths')!=0:errors.append('False-success audit incomplete')
    if (report.get('unit_failures',1)!=0 or report.get('unit_errors',1)!=0 or
            report.get('unit_skipped',1)!=0):errors.append('Automated regression failed or skipped validation')
    unit_path=evidence_file(report.get('unit_evidence',{}),root,errors,'Automated regression')
    if unit_path:
        try:
            unit=json.loads(unit_path.read_text(encoding='utf-8'))
            if (unit.get('source_commit')!=expected_commit or unit.get('source_dirty') is not False or
                    unit.get('scope')!='full_suite' or unit.get('pattern')!='test_*.py' or unit.get('run',0)<1 or
                    unit.get('failures')!=[] or unit.get('errors')!=[] or unit.get('skipped')!=[]):
                errors.append('Raw automated regression does not support the release claim')
        except (ValueError,TypeError):errors.append('Raw automated regression is invalid')
    tasks=report.get('desktop_tasks',[])
    cases={case.get('id'):case for case in tasks}
    if len(tasks)!=32 or len(cases)!=32:errors.append('Exactly 32 unique desktop cases are required')
    for number in range(1,33):
        name=f'B{number:02}';case=cases.get(name,{})
        if case.get('status')!='passed':errors.append(name+' desktop task not passed');continue
        if type(case.get('elapsed_ms')) not in (int,float) or not math.isfinite(case['elapsed_ms']) or case['elapsed_ms']<0:
            errors.append(name+' timing missing')
        if not case.get('environment') or not case.get('application_state'):
            errors.append(name+' environment or application-state oracle missing')
        path=evidence_file(case.get('evidence',{}),root,errors,name)
        if path:
            try:
                raw=json.loads(path.read_text(encoding='utf-8'))
                if (raw.get('source_commit')!=expected_commit or raw.get('kind')!='real_desktop' or
                        raw.get('simulated') is not False):
                    errors.append(name+' raw evidence is stale or is not actual desktop execution')
            except (ValueError,TypeError):errors.append(name+' raw evidence is invalid')
    return errors

def main():
    parser=argparse.ArgumentParser();parser.add_argument('report',type=Path)
    parser.add_argument('--expected-commit')
    args=parser.parse_args()
    if not args.report.is_file():print('BLOCKED: acceptance report missing');return 2
    expected=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    if args.expected_commit and args.expected_commit!=expected:
        print('BLOCKED: requested source commit is not the checked-out commit');return 2
    errors=evaluate(json.loads(args.report.read_text(encoding='utf-8')),args.report.parent,expected)
    for error in errors:print('BLOCKED: '+error)
    if errors:return 2
    print('SHA-bound evidence complete; ready for formal release.');return 0

if __name__=='__main__':raise SystemExit(main())
