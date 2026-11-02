"""Replay a real promoted, isolated case through the public MCP dispatcher."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from authority_fixture import AuthorityCase
from computer_mcp.dataset import promote,writer,schema
from computer_mcp import mcp

class TestPromotedCases(AuthorityCase,unittest.TestCase):
    def test_all_cases_still_behave(self):
        # Typed text is deliberately not retained. Never auto-execute arbitrary
        # historical inputs or treat an unknown verdict as success.
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch.multiple(writer,DATA=root/'raw',ROOT=root,CONFIG=root/'config.json'), \
                 patch.object(promote,'CASES',root/'cases'), \
                 patch.dict(mcp.computer_state.config,observe_screen=False):
                episode=schema.build_episode(tool='control_status',arguments={},zone='Z0',
                    result_text='{}',ok=False,latency_ms=1,error=None)
                writer.append_episode(episode)
                result=promote.promote(episode['id'],note='Isolated replay regression')
                self.assertTrue(result['success'])
                cases=promote.list_cases()
                self.assertEqual(len(cases),1)
                for name in cases:
                    case=json.loads((promote.CASES/name).read_text(encoding='utf-8'))
                    response=asyncio.run(mcp.call_tool(case['tool'],case['args']))
                    text='\\n'.join(item.text for item in response if getattr(item,'text',None))
                    self.assertIs(schema.ok_of(text),True,'Unknown results cannot pass replay')

if __name__=='__main__':unittest.main()
