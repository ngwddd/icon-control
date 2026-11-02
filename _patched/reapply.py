"""Legacy patching is replaced by the v1.3 isolated, reversible installer."""
import sys

def main():
    print('In-place site-packages patching is no longer supported.', file=sys.stderr)
    print('Build a wheel, then run: powershell -File tools/install.ps1 -Wheel dist/<wheel>', file=sys.stderr)
    print('Migration and rollback: docs/v1.3/INSTALL.md', file=sys.stderr)
    return 2

if __name__ == '__main__':
    raise SystemExit(main())

