"""Signed authority fixture for fake actuator tests; never grants the real host."""
import copy
import os
from pathlib import Path
import tempfile
from unittest.mock import patch,Mock
from computer_mcp import security,permission,permission_bridge as bridge,control,panic

class AuthorityFixture:
    def __init__(self,authorized=False,monitoring=False):
        self.authorized=authorized;self.monitoring=monitoring;self.patches=[]
    def __enter__(self):
        self.temp=tempfile.TemporaryDirectory();state=Path(self.temp.name)/'state';state.mkdir()
        self.old_control=copy.deepcopy(control.STATE)
        self.patches=[patch.dict(os.environ,ICON_CONTROL_HOME=self.temp.name),
            patch.multiple(bridge,STATE_DIR=str(state),STATE_PATH=str(state/'mouse-permission.json'),
                LOG_PATH=str(state/'bridge.log'),CLIENTS={},_last_action=None,_revision=0),
            patch.object(permission,'STATE_PATH',str(state/'mouse-permission.json'))]
        if self.monitoring:
            self.patches += [patch.object(control,'ensure_watcher',return_value=True),
                patch.object(panic,'default',return_value=Mock(triggered=False,ready=True))]
        for item in self.patches:item.start()
        security.provision_token()
        control.STATE.update(owner='idle',last_user=0,last_inject=0)
        if self.authorized:bridge.write_state(True,client='fixture',event='action')
        return self
    def __exit__(self,*args):
        for item in reversed(self.patches):item.stop()
        control.STATE.clear();control.STATE.update(self.old_control);self.temp.cleanup()

def signed_state(payload):
    payload=dict(payload)
    payload['signature']=security.signature(payload,security.load_token())
    return payload

class AuthorityCase:
    """Mixin: authority exists only inside a temporary test directory."""
    fixture_authorized=False
    fixture_monitoring=False
    def setUp(self):
        self.authority=AuthorityFixture(self.fixture_authorized,self.fixture_monitoring)
        self.authority.__enter__();self.addCleanup(self.authority.__exit__,None,None,None)
