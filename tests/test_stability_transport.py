import unittest
from unittest.mock import patch
import httpx
import hashlib
import json
import os
import tempfile
from pathlib import Path
from mcp.server import Server
from computer_mcp import transport as T
from computer_mcp import agent_session,security
from mcp.types import TextContent

class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def request(self,token=None,origin=None,expected='a'*40):
        app=T.create_app(Server('test'))
        headers={}
        if token:headers['Authorization']='Bearer '+token
        if origin:headers['Origin']=origin
        with patch.object(T,'transport_token',return_value=expected):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8000') as client:
                return await client.post('/mcp',headers=headers,json={})

    async def test_http_without_credentials_is_rejected(self):
        self.assertEqual((await self.request()).status_code,401)

    async def test_http_wrong_credentials_is_rejected(self):
        self.assertEqual((await self.request('wrong')).status_code,401)

    async def test_http_unprovisioned_is_rejected(self):
        self.assertEqual((await self.request('anything',expected='')).status_code,401)

    async def test_http_untrusted_origin_is_rejected(self):
        self.assertEqual((await self.request('a'*40,'http://localhost.evil.test')).status_code,403)

    async def test_external_binding_is_rejected(self):
        with self.assertRaises(ValueError):await T.run_http(Server('test'),'0.0.0.0',8000)

    async def test_real_sdk_requests_preserve_distinct_client_identities(self):
        server=Server('identity-test')
        @server.call_tool(validate_input=False)
        async def identity(name,arguments):
            return [TextContent(type='text',text=agent_session.current())]
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,ICON_CONTROL_HOME=folder), \
             patch.object(T,'transport_token',return_value='a'*40):
            security.provision_token()
            (Path(folder)/'state'/'http-clients.json').write_text(json.dumps([
                dict(label='independent client',sha256=hashlib.sha256(('b'*40).encode()).hexdigest())]))
            app=T.create_app(server)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8000') as client:
                    async def invoke(token):
                        response=await client.post('/mcp',headers={'Authorization':'Bearer '+token,
                            'Accept':'application/json, text/event-stream'},json={'jsonrpc':'2.0','id':1,
                            'method':'tools/call','params':{'name':'identity','arguments':{}}})
                        self.assertEqual(response.status_code,200,response.text)
                        return response.json()['result']['content'][0]['text']
                    first=await invoke('a'*40);second=await invoke('b'*40)
                    self.assertNotEqual(first,second)
                    self.assertEqual(await invoke('a'*40),first)

if __name__=='__main__':unittest.main()
