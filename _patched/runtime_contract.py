"""Describe the running process, not an unrelated Python interpreter."""
import hashlib
import json
from pathlib import Path
from computer_mcp import __version__, tool_registry


def describe(include_schema=True):
    specs = [s for s in tool_registry.iter_specs() if tool_registry.allowed(s.name)]
    contract = [dict(name=s.name, description=s.description, inputSchema=s.schema) for s in specs]
    digest = hashlib.sha256(json.dumps(contract, ensure_ascii=False, sort_keys=True,
                                       separators=(',', ':')).encode('utf-8')).hexdigest()
    try:
        build = json.loads(Path(__file__).with_name('_build_info.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        build = {}
    result = dict(server_version=__version__, tools_sha256=digest, tool_count=len(specs),
                  source_commit=build.get('source_commit'), source_dirty=build.get('source_dirty'),
                  refresh_required_if_mismatched=True,
                  refresh_action='Restart the MCP connection and refresh tools/list if the client schema/version differs; a running server cannot force a host to discard its cached tools.')
    if include_schema:
        click = tool_registry.get('click')
        result['click_input_schema'] = click.schema
        result['provenance'] = 'packaged_build_metadata' if build else 'unavailable_in_this_installation'
    return result
