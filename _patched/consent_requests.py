"""Broker-owned, signed consent requests. The pipe peer supplies ownership."""
from __future__ import annotations
import copy
import secrets
import time
from computer_mcp import agent_session, capabilities, security

TTL = 120
MAX_REQUESTS = 128
TERMINAL = {'denied', 'expired', 'consumed'}

class RequestQueue:
    """Access is serialized by permission_bridge._lock."""
    def __init__(self):
        self.records = {}

    def _sign(self, record):
        record.pop('signature', None)
        record['signature'] = security.signature(record, security.load_token())
        return copy.deepcopy(record)

    def _active(self, record):
        if not security.authentic(record):
            raise PermissionError('Consent request integrity failure')
        peer = agent_session.lookup(record['agent_session'], record['peer']['pid'])
        alive = bool(peer and peer['created'] == record['peer']['created'])
        app = record['application']
        if app is not None:
            try:
                alive = alive and capabilities.process_record(app['pid']) == app
            except Exception:
                alive = False
        if not alive or (record['status'] != 'approved' and time.time() >= record['expires_at']):
            if record['status'] not in TERMINAL:
                record['status'] = 'expired'
                self._sign(record)
        return record['status'] not in TERMINAL

    def create(self, pid, session, app, scopes):
        peer = agent_session.lookup(session, pid)
        if peer is None:
            raise PermissionError('Requested Agent does not belong to this pipe peer')
        if not isinstance(scopes, list) or not scopes or not set(scopes) <= capabilities.SCOPES:
            raise ValueError('Explicit known request capabilities required')
        if app is not None and capabilities.process_record(app['pid']) != app:
            raise PermissionError('Requested application identity changed')
        now = time.time()
        for request_id, record in list(self.records.items()):
            self._active(record)
            if now - record['created_at'] > TTL * 2:
                del self.records[request_id]
        if len(self.records) >= MAX_REQUESTS:
            raise ValueError('Consent request queue is full')
        record = dict(request_id=secrets.token_hex(24), agent_session=session,
                      agent_id=agent_session.identity(pid, session),
                      workspace_id=agent_session.workspace_identity(pid),
                      peer={'pid': pid, 'created': peer['created'], 'label': peer['label'], 'exe': peer.get('exe')},
                      application=copy.deepcopy(app), scopes=sorted(set(scopes)),
                      created_at=now, expires_at=now+TTL, status='pending')
        self.records[record['request_id']] = record
        return self._sign(record)

    def get(self, request_id, display=False):
        record = self.records.get(request_id)
        if record is None or not self._active(record):
            raise PermissionError('Consent request expired, consumed or unavailable')
        if display and record['status'] == 'pending':
            record['status'] = 'displayed'
            self._sign(record)
        return copy.deepcopy(record)

    def pending(self):
        return [copy.deepcopy(r) for r in self.records.values()
                if self._active(r) and r['status'] in ('pending', 'displayed')]

    def bind_target(self, request_id, app):
        record = self.get(request_id)
        if record['status'] != 'displayed' or record['application'] is not None:
            raise PermissionError('Cannot replace a requested application')
        if capabilities.process_record(app['pid']) != app:
            raise PermissionError('Selected application changed')
        self.records[request_id]['application'] = copy.deepcopy(app)
        return self._sign(self.records[request_id])

    def finish(self, request_id, status):
        if status not in {'approved', 'denied', 'consumed'}:
            raise ValueError('Invalid consent transition')
        record = self.get(request_id)
        allowed = {'displayed': {'approved', 'denied', 'consumed'},
                   'approved': {'consumed', 'denied'}}
        if status not in allowed.get(record['status'], set()):
            raise PermissionError('Invalid consent request state')
        self.records[request_id]['status'] = status
        return self._sign(self.records[request_id])

    def satisfies(self, request_id, state):
        record = self.get(request_id)
        auth = state.get('authorization') or {}
        if not state.get('granted'):
            return False, '当前请求方尚未授权'
        if auth.get('agent_session') != record['agent_session']:
            return False, '授权属于其他会话，将为当前请求方替换授权'
        if not record['application'] or record['application'] not in auth.get('applications', []):
            return False, '当前请求的目标应用尚未授权'
        missing = set(record['scopes']) - set(auth.get('scopes', []))
        if missing:
            return False, '缺少权限：' + ', '.join(sorted(missing))
        return True, '当前请求的会话、应用和权限均已批准'
