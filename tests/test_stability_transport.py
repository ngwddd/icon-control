import unittest
from unittest.mock import patch
import httpx
from mcp.server import Server
from computer_mcp import transport as T

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

if __name__=='__main__':unittest.main()
