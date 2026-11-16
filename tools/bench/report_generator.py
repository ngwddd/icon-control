"""Summarize raw competitor_runner samples; never combine L1/L2/L3 results."""
from __future__ import annotations
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import statistics


def percentile(values, p):
    values = sorted(values)
    if not values:
        return None
    rank = (len(values)-1)*p
    lower = int(rank)
    return values[lower] + (values[min(lower+1, len(values)-1)]-values[lower])*(rank-lower)


def wilson(successes, n):
    if not n:
        return None
    z = 1.95996398454
    p = successes/n
    denominator = 1+z*z/n
    center = (p+z*z/(2*n))/denominator
    half = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/denominator
    return [max(0, center-half), min(1, center+half)]


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        if row.get('record_type') == 'manifest':
            continue
        # Keep experiments and machine profiles separate, including app versions.
        key = (row['run_id'], row['level'], row['task_id'], row['project'],
               row['version'], row['commit_sha'],
               json.dumps(row['machine_profile'], sort_keys=True))
        groups[key].append(row)
    report = []
    for key, samples in sorted(groups.items()):
        supported = [s for s in samples if s['status'] != 'unsupported']
        passed = sum(s['status'] == 'success' for s in supported)
        times = [s['latency_ms'] for s in supported if isinstance(s.get('latency_ms'), (int, float))
                 and math.isfinite(s['latency_ms']) and s['latency_ms'] >= 0]
        metrics = {}
        for name in sorted({k for s in supported for k in s.get('metrics', {})}):
            values = [s['metrics'][name] for s in supported if s.get('metrics', {}).get(name) is not None]
            metrics[name] = dict(samples=len(values), total=sum(values) if values else None)
        report.append(dict(run_id=key[0], level=key[1], task_id=key[2], project=key[3],
                           version=key[4], commit_sha=key[5], machine_profile=json.loads(key[6]),
                           samples=len(samples), supported=len(supported),
                           unsupported=len(samples)-len(supported), passed=passed,
                           failed=len(supported)-passed,
                           success_rate=passed/len(supported) if supported else None,
                           success_rate_95ci=wilson(passed, len(supported)),
                           latency_samples=len(times),
                           latency_p50_ms=statistics.median(times) if times else None,
                           latency_p95_ms=percentile(times, .95),
                           latency_max_ms=max(times) if times else None,
                           metrics=metrics))
    return dict(format=1, results=report,
                note='Adapter counters are reported telemetry, not independently verified metrics. '
                     'Missing counters remain null. Latency includes the independent verifier, excludes setup/reset. '
                     'Unsupported tasks remain visible; no aggregate competitor ranking is produced.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('samples', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.samples.read_text(encoding='utf-8').splitlines() if line.strip()]
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(summarize(rows), stream, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
