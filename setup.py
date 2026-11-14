"""Embed source provenance when packaging; never fabricate acceptance data."""
import json
from pathlib import Path
import subprocess
from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist

ROOT = Path(__file__).resolve().parent


def provenance():
    # Always derive from the working tree when git is available: reusing a stale
    # _patched/_build_info.json let an old "dirty" flag travel into release builds
    # whose committed state was clean.
    if not (ROOT / '.git').exists():
        packaged = ROOT / '_patched' / '_build_info.json'
        if packaged.is_file():
            return json.loads(packaged.read_text(encoding='utf-8'))
        return dict(source_commit=None, source_dirty=None)
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    # Only tracked changes count: build output (dist/, build/, egg-info) is written
    # by the release workflow itself and made every CI wheel claim a dirty tree.
    dirty = subprocess.call(['git', 'diff', '--quiet', 'HEAD'], cwd=ROOT) != 0
    return dict(source_commit=sha, source_dirty=dirty)


def _unused_has_source_changes(status: str) -> bool:
    """True only for changes that are not build output.

    A CI build writes dist/ and .runtime/ before it packages, so the raw status is
    always 'dirty' there even though the commit is exactly the tagged one. What the
    flag should answer is 'does this wheel contain something the commit does not'.
    """
    ignored = ('dist/', 'build/', '.runtime/', '.verify-artifacts/', '.pytest_cache/')
    ignored_files = ('@AutomationLog.txt',)
    for line in status.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip().strip('"')
        if path in ignored_files or path.startswith(ignored):
            continue
        if '.egg-info/' in path:
            continue
        return True
    return False


def write_info(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(provenance(), sort_keys=True) + '\n', encoding='utf-8')


class BuildWithProvenance(build_py):
    def run(self):
        super().run()
        write_info(Path(self.build_lib) / 'computer_mcp' / '_build_info.json')


class SourceWithProvenance(sdist):
    def make_release_tree(self, base_dir, files):
        super().make_release_tree(base_dir, files)
        write_info(Path(base_dir) / '_patched' / '_build_info.json')


setup(cmdclass={'build_py': BuildWithProvenance, 'sdist': SourceWithProvenance})
