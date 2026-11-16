"""Bounded tests against disposable native windows; never use user applications."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--inject', action='store_true',
                        help='Also send one real click to the disposable fixture')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='icon-rc2-window-') as folder:
        # Set isolation before importing any product module.
        os.environ['ICON_CONTROL_HOME'] = folder
        os.environ['ICON_CONTROL_POLICY'] = 'local'
        os.environ['DSH_MOUSE_BRIDGE'] = 'off'
        import win32api
        import win32con as C
        import win32gui as W
        from computer_mcp import pointer_contract as P, policy, input_guard as G
        from computer_mcp.native_mouse import physical_coordinates, cursor_position, move_absolute
        from computer_mcp import execution
        counts = {'a': 0, 'b': 0}
        handles = {}
        def wndproc(hwnd, message, wp, lp):
            if message == C.WM_LBUTTONDOWN:
                label = next((k for k, v in handles.items() if v == hwnd), None)
                if label:
                    counts[label] += 1
            if message == C.WM_PAINT:
                hdc, paint = W.BeginPaint(hwnd)
                W.DrawText(hdc, 'Apply RC2 fixture', -1, (20, 20, 280, 70), C.DT_SINGLELINE)
                W.EndPaint(hwnd, paint)
                return 0
            return W.DefWindowProc(hwnd, message, wp, lp)
        klass = W.WNDCLASS()
        klass.lpszClassName = 'IconControlRC2Probe' + str(os.getpid())
        klass.lpfnWndProc = wndproc
        klass.hInstance = win32api.GetModuleHandle(None)
        klass.hbrBackground = C.COLOR_WINDOW + 1
        atom = W.RegisterClass(klass)
        original_point = cursor_position()
        report = dict(source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                      source_dirty=bool(subprocess.check_output(['git', 'status', '--porcelain'], text=True).strip()),
                      kind='real_hwnd_fault_probe', faults=[], wrong_target_events=0,
                      fault_sink='simulated; validates real Win32 ownership before input',
                      injection_requested=args.inject)
        def create(label):
            hwnd = W.CreateWindowEx(C.WS_EX_TOPMOST, atom, 'Icon RC2 ' + label,
                                    C.WS_POPUP | C.WS_BORDER, 30, 30, 320, 160,
                                    0, 0, klass.hInstance, None)
            handles[label] = hwnd
            return hwnd
        def front(label, x=30):
            hwnd = handles[label]
            W.ShowWindow(hwnd, C.SW_SHOWNOACTIVATE)
            W.SetWindowPos(hwnd, C.HWND_TOPMOST, x, 30, 320, 160, C.SWP_NOACTIVATE)
            W.UpdateWindow(hwnd)
            W.PumpWaitingMessages()
        class Sink(G.MouseController):
            def __init__(self):
                self.point = (0, 0)
                self.calls = 0
                self.held = set()
            @property
            def position(self):
                return self.point
            @position.setter
            def position(self, point):
                self.point = point
            def click(self, *args, **kwargs):
                self.calls += 1
            def cleanup(self):
                self.held.clear()
        point = (150, 110)
        try:
            with physical_coordinates():
                create('a')
                create('b')
                for fault in ('occluded', 'moved', 'destroyed'):
                    refused = attempted = 0
                    for _ in range(100):
                        W.ShowWindow(handles['b'], C.SW_HIDE)
                        front('a')
                        binding = P.bind_window(handles['a'])
                        if fault == 'occluded':
                            front('b')
                        elif fault == 'moved':
                            front('a', x=35)
                        else:
                            W.DestroyWindow(handles['a'])
                        sink = Sink()
                        result = P.click_at(sink, point, G.Button.left, binding=binding, move_delay=0)
                        refused += int(result.get('outcome') == 'refused'
                                       and result.get('action_executed') is False)
                        attempted += sink.calls
                        if fault == 'destroyed':
                            create('a')
                    report['faults'].append(dict(fault=fault, samples=100, refused=refused,
                                                  input_sink_calls=attempted))
                    report['wrong_target_events'] += attempted
                if args.inject:
                    W.ShowWindow(handles['b'], C.SW_HIDE)
                    front('a')
                    binding = P.bind_window(handles['a'])
                    policy.ensure_initialised()
                    mouse = G.MouseController()
                    denials = []
                    from computer_mcp.permission import PermissionDenied
                    def trace(frame, event, value):
                        if event == 'exception' and isinstance(value[1], PermissionDenied):
                            denials.append(str(value[1]))
                        return trace
                    # Real guarded SendInput, to this fixture's exact HWND only.
                    try:
                        sys.settrace(trace)
                        with execution.operation('click', {'x': point[0], 'y': point[1]}):
                            result = P.click_at(mouse, point, G.Button.left, binding=binding,
                                                move_delay=.04)
                    finally:
                        sys.settrace(None)
                    deadline = time.monotonic() + 1
                    while time.monotonic() < deadline and counts['a'] < 1:
                        W.PumpWaitingMessages()
                        time.sleep(.01)
                    report['injection'] = dict(result=result, events=dict(counts),
                                               verified=counts == {'a': 1, 'b': 0},
                                               denials=sorted(set(denials)))
                    mouse.cleanup()
                report['passed'] = (all(r['refused'] == r['samples'] and not r['input_sink_calls']
                                        for r in report['faults'])
                                    and (not args.inject or report['injection']['verified']))
        except Exception as exc:
            report.update(passed=False, error=type(exc).__name__ + ': ' + str(exc))
        finally:
            for hwnd in handles.values():
                if W.IsWindow(hwnd):
                    W.DestroyWindow(hwnd)
            W.UnregisterClass(atom, klass.hInstance)
            # Do not override a pointer that a physical user moved meanwhile.
            if cursor_position() == point:
                move_absolute(*original_point)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report))
        return 0 if report.get('passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
