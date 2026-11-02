"""Authenticated loopback Streamable HTTP using the MCP SDK, not custom JSON-RPC."""
from __future__ import annotations
from contextlib import asynccontextmanager
import hmac
from computer_mcp import security

def transport_token():
    try:
        value=(security.data_home()/'state'/'mcp-token.txt').read_text().strip()
        return value if len(value)>=32 else ''
    except OSError:return ''

def create_app(server):
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.responses import JSONResponse
    manager=StreamableHTTPSessionManager(server,stateless=True,json_response=True,
        security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=True,
            allowed_hosts=['127.0.0.1:*','localhost:*','[::1]:*'],
            allowed_origins=['http://127.0.0.1:*','http://localhost:*']))

    async def endpoint(request):
        expected=transport_token()
        supplied=request.headers.get('authorization','')
        if not expected or not hmac.compare_digest(supplied,'Bearer '+expected):
            return JSONResponse({'error':'Authentication required'},status_code=401)
        origin=request.headers.get('origin')
        if origin:
            from urllib.parse import urlparse
            parsed=urlparse(origin)
            if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost') or parsed.username:
                return JSONResponse({'error':'Origin rejected'},status_code=403)
        await manager.handle_request(request.scope,request.receive,request._send)

    # ASGI transport is mounted directly so streaming responses retain their
    # framing and session handling from the official implementation.
    class AuthenticatedMCP:
        async def __call__(self,scope,receive,send):
            from starlette.requests import Request
            request=Request(scope,receive,send)
            response=await endpoint(request)
            if response is not None:await response(scope,receive,send)

    @asynccontextmanager
    async def lifespan(app):
        async with manager.run():yield
    return Starlette(routes=[Route('/mcp',AuthenticatedMCP(),methods=['GET','POST','DELETE'])],lifespan=lifespan)

async def run_http(server,host='127.0.0.1',port=8000):
    import uvicorn
    if host not in ('127.0.0.1','localhost','::1'):
        raise ValueError('Only loopback HTTP binding is supported')
    if not transport_token():raise RuntimeError('Run icon-control init before HTTP startup')
    await uvicorn.Server(uvicorn.Config(create_app(server),host=host,port=port,log_level='warning')).serve()
