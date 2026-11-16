"""Independent verifier, failure accounting and benchmark timing regressions."""
import importlib.util
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / 'bench' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


B = module('competitor_runner')
R = module('report_generator')


class ReportTests(unittest.TestCase):
    def row(self, success=True, latency=100, **overrides):
        row = dict(run_id='r', level='L2', task_id='T01', project='candidate',
                   version='1.4.5rc2', commit_sha='abc', machine_profile={},
                   status='success' if success else 'failed', task_success=success,
                   latency_ms=latency, tool_latency_ms=latency / 2 if latency is not None else None,
                   verifier_latency_ms=latency / 2 if latency is not None else None, metrics={})
        return dict(row, **overrides)

    def test_fast_failures_do_not_improve_success_latency(self):
        result = R.summarize([self.row(False, 1)] * 10 + [self.row(True, 1000)] * 10)['results'][0]
        self.assertEqual(result['success_rate'], .5)
        self.assertEqual(result['latency_p50_ms'], 1000)
        self.assertEqual(result['failure_latency']['p50_ms'], 1)
        self.assertEqual(result['success_tool_latency']['p50_ms'], 500)

    def test_all_failed_has_no_success_latency(self):
        result = R.summarize([self.row(False, 5)])['results'][0]
        self.assertIsNone(result['latency_p50_ms'])
        self.assertEqual(result['latency_samples'], 0)
        self.assertEqual(result['failed'], 1)

    def test_unsupported_stays_visible_and_outside_success_denominator(self):
        result = R.summarize([self.row(), self.row(False, None, status='unsupported')])['results'][0]
        self.assertEqual(result['samples'], 2)
        self.assertEqual(result['unsupported'], 1)
        self.assertEqual(result['success_rate'], 1)

    def test_bad_times_are_excluded_without_dropping_failures(self):
        rows = [self.row(False, value) for value in (None, -1, math.nan, math.inf, True)]
        result = R.summarize(rows)['results'][0]
        self.assertEqual(result['failed'], 5)
        self.assertEqual(result['failure_latency']['samples'], 0)

    def test_layers_and_machine_profiles_are_not_combined(self):
        rows = [self.row(), self.row(level='L1'), self.row(machine_profile={'dpi': 150})]
        self.assertEqual(len(R.summarize(rows)['results']), 3)

    def test_success_flag_disagreement_is_a_failure(self):
        row = self.row(task_success=False)
        result = R.summarize([row])['results'][0]
        self.assertEqual(result['passed'], 0)
        self.assertEqual(result['failed'], 1)

    def test_wilson_interval_reports_uncertainty_for_twenty_passes(self):
        lo, hi = R.wilson(20, 20)
        self.assertLess(lo, .9)
        self.assertAlmostEqual(hi, 1)


class RunnerTests(unittest.TestCase):
    def config(self):
        return dict(level='L2', seed=145, projects={'p': dict(version='1', commit_sha='abc')},
                    tasks={'T01': dict(setup=['setup'], reset=['reset'], verify=['verify'],
                                       adapters={'p': ['adapter']})})

    def run_one(self, *, adapter_ok=True, reset_ok=True, stale=False, setup_ok=True):
        def cmd(argv, context, timeout):
            return dict(ok=(adapter_ok if argv == ['adapter'] else
                            reset_ok if argv == ['reset'] else
                            setup_ok if argv == ['setup'] else True),
                        elapsed_ms=10 if argv == ['adapter'] else 5,
                        payload=dict(verified=True, run_id=context['run_id'],
                                     sample_id='old' if stale else context['sample_id'],
                                     metrics={'tool_calls': 2}))
        with patch.object(B, 'command', side_effect=cmd) as calls:
            row = B.run_one(self.config(), 'p', 'T01', 0, 'r', {})
        return row, calls

    def test_independent_verifier_receipt_is_required(self):
        self.assertFalse(self.run_one(stale=True)[0]['task_success'])
        self.assertTrue(self.run_one()[0]['task_success'])

    def test_failed_adapter_cannot_pass_from_verifier_alone(self):
        row, calls = self.run_one(adapter_ok=False)
        self.assertFalse(row['task_success'])
        self.assertEqual(len(calls.call_args_list), 4)

    def test_reset_failure_marks_failure(self):
        row, _ = self.run_one(reset_ok=False)
        self.assertEqual(row['failure_reason'], 'reset_failed')
        self.assertFalse(row['task_success'])

    def test_setup_failure_resets_without_executing_adapter(self):
        row, calls = self.run_one(setup_ok=False)
        self.assertEqual(row['failure_reason'], 'setup_failed')
        self.assertEqual([c.args[0] for c in calls.call_args_list], [['setup'], ['reset']])

    def test_adapter_and_verifier_durations_are_separate(self):
        row, _ = self.run_one()
        self.assertEqual(row['tool_latency_ms'], 10)
        self.assertEqual(row['verifier_latency_ms'], 5)

    def test_missing_adapter_is_unsupported(self):
        row = B.run_one(self.config(), 'p', 'T06', 0, 'r', {})
        self.assertEqual(row['status'], 'unsupported')

    def test_real_child_command_timeout(self):
        result = B.command([sys.executable, '-c', 'import time; time.sleep(5)'], {}, .05)
        self.assertFalse(result['ok'])
        self.assertEqual(result['reason'], 'command_timeout')
