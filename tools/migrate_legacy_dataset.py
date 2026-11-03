"""Explicit operator migration of unowned legacy rows into one live Agent."""
import argparse
import json
from pathlib import Path
from computer_mcp import agent_session
from computer_mcp.dataset import writer

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--agent',required=True)
    parser.add_argument('--confirm-migration',action='store_true',required=True)
    args=parser.parse_args()
    if not any(a['id']==args.agent for a in agent_session.active()):
        parser.error('Choose the complete ID of a live Agent from the native settings')
    with args.source.open('rb') as stream:
        data=stream.read(16*1024*1024+1)
    if len(data)>16*1024*1024:
        parser.error('Migration input limit is 16 MiB')
    rows=[json.loads(line) for line in data.decode('utf-8-sig').splitlines() if line.strip()]
    if any(not isinstance(row,dict) or row.get('owner') for row in rows):
        parser.error('Input must contain only unowned legacy rows')
    with agent_session.bind(args.agent):
        for row in rows:
            writer.append_episode(row)
    print(json.dumps({'migrated':len(rows),'agent':args.agent}))
if __name__=='__main__':
    main()
