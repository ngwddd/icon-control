"""Native-only quick grant preferences. A preference never confers authority."""
import json
import os
import tempfile
from pathlib import Path
from computer_mcp import security, capabilities, agent_session

COMMON = ('screen_read', 'input', 'text_entry')


class QuickGrantPolicy:
    def __init__(self):
        self.path = security.data_home() / 'state' / 'quick-target.json'

    def remember(self, identity, app):
        if not any(a['id'] == identity for a in agent_session.active()):
            raise ValueError('请选择当前有效的 Agent')
        if capabilities.process_record(app['pid']) != app:
            raise ValueError('应用进程身份已改变')
        record = dict(agent=identity, app=app)
        record['signature'] = security.signature(record, security.load_token())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile('w', encoding='utf8', dir=self.path.parent, delete=False) as f:
            temp = Path(f.name)
            try:
                json.dump(record, f)
                f.flush()
                os.fsync(f.fileno())
            except BaseException:
                f.close()
                temp.unlink(missing_ok=True)
                raise
        try:
            os.replace(temp, self.path)
        finally:
            temp.unlink(missing_ok=True)

    def resolve(self):
        try:
            pref = json.loads(self.path.read_text(encoding='utf8'))
            if not security.authentic(pref):
                return dict(status='denied')
            # A saved preference only ever applies to the agent it was bound to.
            # Being the sole live session is not an identity: it must be rebound.
            active = list(agent_session.active())
            agents = [a for a in active if a['id'] == pref['agent']]
            if len(agents) != 1:
                return dict(status='ambiguous', reason='saved_agent_inactive')
            app = capabilities.process_record(pref['app']['pid'])
            if app != pref['app']:
                return dict(status='denied')
            return dict(status='ready', agent_session=agents[0]['id'], applications=[app],
                        label=agents[0]['label'], scopes=list(COMMON))
        except FileNotFoundError:
            return dict(status='ambiguous')
        except Exception:
            return dict(status='unavailable')
