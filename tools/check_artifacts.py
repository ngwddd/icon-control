"""Check the deliverable archives, including source-only regression fixtures."""
import json
from pathlib import Path
import tarfile
import zipfile

root=Path(__file__).resolve().parents[1]
version=(root/'VERSION').read_text().strip()
prefix='icon_control-'+version
wheel=root/'dist'/(prefix+'-py3-none-any.whl')
source=root/'dist'/(prefix+'.tar.gz')
with zipfile.ZipFile(wheel) as archive:
    assert archive.testzip() is None, 'Corrupt wheel member'
    for name in archive.namelist():
        assert '.runtime/' not in name and not name.endswith(('bridge-token.txt','mcp-token.txt','.pyc'))
    for name in ('__init__.py','mcp.py','security.py','permission_bridge.py','actions/keyboard.py'):
        assert archive.read('computer_mcp/'+name)==(root/'_patched'/name).read_bytes(), name+' differs from source'
with tarfile.open(source) as archive:
    for name in ('tests/_bootstrap.py','tests/authority_fixture.py','tools/verify.py',
                 'tools/test_suite.py','tools/install.ps1','constraints-windows-py312.txt'):
        member=archive.extractfile(prefix+'/'+name)
        assert member is not None and member.read()==(root/name).read_bytes(), name+' missing or stale'
print(json.dumps(dict(wheel_integrity='passed',source_test_fixtures='included',credentials_packaged=False)))
