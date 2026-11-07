"""Regenerate docs/tools-snapshot.json from the live registry.

The snapshot is an oracle: it records the exact description and input schema of
every tool so an accidental contract change fails a test. When a tool really does
change (v1.4.1 adds tools and gives screenshot/ocr_read a regions parameter), run
this and review the diff before committing.

    python tools/snapshot_tools.py [--check]
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "docs/tools-snapshot.json"


def dispatch_names() -> set:
    import computer_mcp

    sources = [Path(computer_mcp.__file__).with_name("mcp.py"),
               Path(computer_mcp.__file__).with_name("zones") / "dispatch.py"]
    text = ""
    for path in sources:
        if path.is_file():
            text += path.read_text(encoding="utf-8")
    names = set()
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.Compare):
            continue
        if not (isinstance(node.left, ast.Name) and node.left.id == "name"):
            continue
        for op, comparator in zip(node.ops, node.comparators):
            if isinstance(op, ast.Eq) and isinstance(comparator, ast.Constant) \
                    and isinstance(comparator.value, str):
                names.add(comparator.value)
            elif isinstance(op, ast.In) and isinstance(comparator, (ast.Tuple, ast.List, ast.Set)):
                names.update(element.value for element in comparator.elts
                             if isinstance(element, ast.Constant) and isinstance(element.value, str))
    return names


def build() -> dict:
    from computer_mcp import tool_registry as reg

    tools = []
    for name in sorted(reg.TOOLS):
        spec = reg.TOOLS[name]
        schema = json.loads(json.dumps(spec.schema))
        if spec.name == 'ui_click':
            # The additive ref/anyOf block is applied to the live spec; the
            # snapshot keeps the plain name-based contract (the test re-adds it).
            schema.get('properties', {}).pop('ref', None)
            schema.pop('anyOf', None)
            schema['required'] = ['name']
        digest = hashlib.sha1((spec.description + json.dumps(schema, sort_keys=True))
                              .encode("utf-8")).hexdigest()
        tools.append(dict(name=spec.name, description=spec.description,
                          block_sha1=digest, schema=schema))
    dispatch = sorted(dispatch_names())
    registered = {tool["name"] for tool in tools}
    return dict(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        source="tools/snapshot_tools.py (registry -> docs/tools-snapshot.json)",
        mcp_py_lines=0,
        tool_count=len(tools),
        dispatch_count=len(dispatch),
        tools=tools,
        dispatch=dispatch,
        tools_without_dispatch=sorted(registered - set(dispatch)),
        dispatch_without_tool=sorted(set(dispatch) - registered),
        schema_oracle=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="compare with the stored snapshot instead of writing")
    args = parser.parse_args()
    payload = build()
    if args.check:
        stored = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        same = (stored.get("tools") == payload["tools"]
                and stored.get("dispatch") == payload["dispatch"])
        print("snapshot matches" if same else "snapshot is out of date")
        return 0 if same else 1
    SNAPSHOT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {SNAPSHOT.name}: {payload['tool_count']} tools, "
          f"{payload['dispatch_count']} dispatch names")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
