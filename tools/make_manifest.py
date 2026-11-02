"""Generate review artifacts from the actual registry and source files."""
import hashlib
import json
from pathlib import Path
from computer_mcp import tool_registry

root=Path(__file__).resolve().parents[1];out=root/'docs'/'v1.3';out.mkdir(parents=True,exist_ok=True)
tools=[dict(name=s.name,zone=s.zone,effects=list(s.effects),requires_authority=s.requires_authority,
            read_actions=list(s.read_actions),action_default=s.action_default,read_when_absent=list(s.read_when_absent),
            parameter_effects=[dict(parameter=key,effects=list(effects)) for key,effects in s.parameter_effects])
       for s in tool_registry.iter_specs()]
(out/'tool-permissions.json').write_text(json.dumps(tools,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
table=['# 工具权限矩阵','','89 个现有工具；效果声明参与执行检查，旧 read_only 标记仅用于兼容。',
       '每项 effects 显式声明；read_actions/read_when_absent 的参数规则见 tool-permissions.json。',
       'ALLOW/DENY 对旧名、别名、内部子动作同样生效；未知工具拒绝。','',
       '| 工具 | 分区 | 声明副作用 | 需要用户授权 |','|---|---|---|---|']
for item in tools:table.append('| %s | %s | %s | %s |'%(item['name'],item['zone'],', '.join(item['effects']),'是' if item['requires_authority'] else '否'))
(out/'PERMISSIONS.md').write_text('\n'.join(table)+'\n',encoding='utf-8')
paths=[]
for folder in ('_patched','plugin','tools','tests'):
    paths += [p for p in (root/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.js','.ps1','.cjs','.json','.yml')]
paths += [root/'pyproject.toml',root/'VERSION',root/'constraints-windows-py312.txt',root/'MANIFEST.in']
manifest={str(p.relative_to(root)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
          for p in sorted(paths) if '__pycache__' not in p.parts}
(out/'source-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
print(json.dumps(dict(tools=len(tools),source_files=len(manifest))))
