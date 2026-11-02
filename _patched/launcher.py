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
from computer_mcp import security, __version__

def add_http_client(name):
    from computer_mcp.workspace import component
    import hashlib
    component(name)
    root = security.data_home()/'state'
    folder = root/'http-client-credentials';folder.mkdir(parents=True,exist_ok=True)
    path = folder/(name+'.token')
    credential = secrets.token_urlsafe(32)
    with path.open('x',encoding='utf-8') as stream: stream.write(credential)
    index = root/'http-clients.json'
    entries = json.loads(index.read_text(encoding='utf-8')) if index.exists() else []
    entries.append(dict(label=name,sha256=hashlib.sha256(credential.encode()).hexdigest()))
    temporary=index.with_suffix('.tmp')
    temporary.write_text(json.dumps(entries),encoding='utf-8');os.replace(temporary,index)
    return dict(client=name,credential_file=str(path),granted=False)

def initialize(bridge_port=None, register_ui=False):
    token=security.provision_token()
    if bridge_port is not None:
        if not 1024 <= bridge_port <= 65535:raise ValueError('Invalid bridge port')
        config = security.data_home()/'state'/'bridge-config.json'
        previous = json.loads(config.read_text(encoding='utf-8')) if config.exists() else {}
        previous.update(port=bridge_port)
        if previous.get('origins') in (None,['dsh-app://','dsh-app://localhost']):
            previous['origins']=['dsh-app://app']
        config.write_text(json.dumps(previous),encoding='utf-8')
    path=security.data_home()/'state'/'mcp-token.txt'
    if not path.exists():
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w') as stream:stream.write(secrets.token_urlsafe(32))
    candidates=[Path(sys.prefix)/'share'/'icon-control'/'plugin'/'client.js',
                Path(__file__).resolve().parents[1]/'plugin'/'client.js']
    template=next((p for p in candidates if p.is_file()),None)
    if template is None:raise RuntimeError('Packaged permission client template missing')
    output=security.data_home()/'plugin'/'client.js';output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists() and token in output.read_text(encoding='utf-8'):
        # Revoke the renderer's previously embedded credential during migration.
        security.token_path().unlink()
        token = security.provision_token()
        security.latch_stop()
    content=template.read_text(encoding='utf-8').replace('__BRIDGE_PORT__',str(security.bridge_port()))
    output.write_text(content,encoding='utf-8')
    if os.name == 'nt' and register_ui:
        import winreg
        native_python = Path(sys.executable).with_name('pythonw.exe')
        if not native_python.exists(): native_python = Path(sys.executable)
        bootstrap = security.data_home()/'plugin'/'open-permissions.py'
        bootstrap.write_text('import os, runpy\nos.environ["ICON_CONTROL_HOME"] = '+
            repr(str(security.data_home()))+'\nrunpy.run_module("computer_mcp.consent", run_name="__main__")\n',encoding='utf-8')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Classes\icon-control') as key:
            winreg.SetValueEx(key, '', 0, winreg.REG_SZ, 'URL:Icon Control permissions')
            winreg.SetValueEx(key, 'URL Protocol', 0, winreg.REG_SZ, '')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Classes\icon-control\shell\open\command') as key:
            winreg.SetValueEx(key, '', 0, winreg.REG_SZ, '"'+str(native_python)+'" "'+str(bootstrap)+'"')
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
    parser.add_argument('command',choices=['stdio','http','bridge','init','check','client-add'],nargs='?',default='stdio')
    parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8000)
    parser.add_argument('--bridge-port',type=int)
    parser.add_argument('--register-ui',action='store_true')
    parser.add_argument('--client-name')
    args=parser.parse_args()
    if args.command=='init':print(json.dumps(initialize(args.bridge_port,args.register_ui)));return 0
    if args.command=='client-add':
        print(json.dumps(add_http_client(args.client_name)));return 0
    if args.command=='check':
        from computer_mcp import tool_registry,permission
        print(json.dumps(dict(version=__version__,tools=tool_registry.summary(),permission=permission.status())));return 0
    if args.command=='bridge':
        from computer_mcp.permission_bridge import main as bridge_main
        sys.argv=[sys.argv[0],'--port',str(args.bridge_port or (security.bridge_port() if args.port==8000 else args.port))]
        return bridge_main()
    from computer_mcp import mcp
    from computer_mcp import process_registry
    process_registry.register_current()
    if args.command=='http':asyncio.run(mcp.run_http(args.host,args.port))
    else:asyncio.run(mcp.run_stdio())
    return 0

if __name__=='__main__':raise SystemExit(main())
