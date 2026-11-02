"""Installed entry point. Provisioning creates credentials, never user grants."""
from __future__ import annotations
import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import shutil
import sys
from computer_mcp import security

def initialize():
    token=security.provision_token()
    path=security.data_home()/'state'/'mcp-token.txt'
    if not path.exists():
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w') as stream:stream.write(secrets.token_urlsafe(32))
    candidates=[Path(sys.prefix)/'share'/'icon-control'/'plugin'/'client.js',
                Path(__file__).resolve().parents[1]/'plugin'/'client.js']
    template=next((p for p in candidates if p.is_file()),None)
    if template is None:raise RuntimeError('Packaged permission client template missing')
    output=security.data_home()/'plugin'/'client.js';output.parent.mkdir(parents=True,exist_ok=True)
    content=template.read_text(encoding='utf-8').replace('__BRIDGE_TOKEN__',token)
    output.write_text(content,encoding='utf-8')
    for name in ('macros','recipes','templates'):
        bundled=Path(sys.prefix)/'share'/'icon-control'/name
        if bundled.is_dir():
            destination=security.data_home()/name;destination.mkdir(parents=True,exist_ok=True)
            for source in bundled.iterdir():
                target=destination/source.name
                if source.is_file() and not target.exists():shutil.copy2(source,target)
    return dict(initialized=True,home=str(security.data_home()),client=str(output),granted=False)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['stdio','http','bridge','init','check'],nargs='?',default='stdio')
    parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8000)
    args=parser.parse_args()
    if args.command=='init':print(json.dumps(initialize()));return 0
    if args.command=='check':
        from computer_mcp import tool_registry,permission
        print(json.dumps(dict(version='1.3.0rc1',tools=tool_registry.summary(),permission=permission.status())));return 0
    if args.command=='bridge':
        from computer_mcp.permission_bridge import main as bridge_main
        sys.argv=[sys.argv[0],'--port',str(18765 if args.port==8000 else args.port)]
        return bridge_main()
    from computer_mcp import mcp
    if args.command=='http':asyncio.run(mcp.run_http(args.host,args.port))
    else:asyncio.run(mcp.run_stdio())
    return 0

if __name__=='__main__':raise SystemExit(main())
