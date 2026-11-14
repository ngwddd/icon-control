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
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=all'], cwd=ROOT, text=True).strip())
    return dict(source_commit=sha, source_dirty=dirty)


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
