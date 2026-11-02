"""Real SDK client/server round trips. Only list_tools; no desktop input."""
from __future__ import annotations
import argparse
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import httpx
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

async def verify(read,write):
    async with ClientSession(read,write) as session:
        initialized=await session.initialize()
        tools=await session.list_tools()
        if len(tools.tools)!=89:raise RuntimeError('Tool manifest mismatch')
        return dict(protocol=initialized.protocolVersion,tools=len(tools.tools))

async def main(args):
    env=dict(os.environ,ICON_CONTROL_HOME=str(args.home),DSH_MOUSE_BRIDGE='off',PYTHONIOENCODING='utf-8')
    report={}
    params=StdioServerParameters(command=sys.executable,args=['-m','computer_mcp.launcher','stdio'],env=env)
    async with stdio_client(params) as (read,write):report['stdio']=await verify(read,write)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    log=args.home/'protocol-server.log'
    with log.open('w',encoding='utf-8') as stream:
        process=subprocess.Popen([sys.executable,'-m','computer_mcp.launcher','http','--port',str(port)],
                                  env=env,stdout=subprocess.DEVNULL,stderr=stream)
        try:
            url=f'http://127.0.0.1:{port}/mcp'
            async with httpx.AsyncClient() as probe:
                for _ in range(100):
                    if process.poll() is not None:raise RuntimeError('HTTP server exited; inspect '+str(log))
                    try:
                        denied=await probe.post(url,json={})
                        if denied.status_code==401:break
                    except httpx.ConnectError:pass
                    await asyncio.sleep(.1)
                else:raise RuntimeError('HTTP startup timeout')
            token=(args.home/'state'/'mcp-token.txt').read_text().strip()
            async with httpx.AsyncClient(headers={'Authorization':'Bearer '+token}) as client:
                async with streamable_http_client(url,http_client=client) as (read,write,_):
                    report['http']=await verify(read,write)
            report['http_unauthenticated_status']=denied.status_code
        finally:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
    report['elapsed_s']=round(time.monotonic()-args.started,3)
    (args.home/'protocol-smoke.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--home',type=Path,required=True);args=parser.parse_args()
    args.started=time.monotonic()
    asyncio.run(asyncio.wait_for(main(args),timeout=45))
