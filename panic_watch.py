"""Compatibility entry point for the registered-process-only watchdog."""
from computer_mcp.panic_watch import automation_pids, main

if __name__ == '__main__':
    raise SystemExit(main())
