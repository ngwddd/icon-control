"""Versioned installed tool-name contract, shared by deployment and protocol."""
import json
from pathlib import Path


def validate_registry():
    from computer_mcp import tool_registry
    manifest = json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))
    names = manifest['names']
    if manifest.get('format') != 1 or not names or len(names) != len(set(names)):
        raise RuntimeError('Invalid packaged tool manifest')
    actual = set(tool_registry.TOOLS)
    expected = set(names)
    if actual != expected:
        raise RuntimeError('Packaged tool manifest does not match registry: missing=' +
                           repr(sorted(expected - actual)) + ', extra=' + repr(sorted(actual - expected)))
    return tuple(names)
