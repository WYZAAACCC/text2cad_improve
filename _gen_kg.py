"""Generate UA-compatible knowledge-graph.json."""
import json, re, shutil
from pathlib import Path
from datetime import datetime

root = Path(r'E:/auto_detection_process')

SKIP_DIRS = {'node_modules','__pycache__','.git','.conda','.pytest_cache',
    '.mypy_cache','.ruff_cache','dist','build','output','demo_output',
    '_archive','demo_output_v2','.understand-anything','.claude'}
SKIP_SUFFIX = {'.pyc','.pyo','.pyd','.so','.dll','.exe','.db',
    '.rst','.esav','.full','.mode','.DSP','.mntr','.stat','.ldhi','.r001','.rdb'}

# UA-compatible node type enum
TYPE_MAP = {'.py': 'file', '.md': 'document', '.json': 'config', '.yaml': 'config',
    '.yml': 'config', '.toml': 'config', '.txt': 'document', '.inp': 'config'}

def summary_for(fpath, ntype):
    name = fpath.name
    if ntype == 'document': return f'Documentation: {name}'
    if ntype == 'config': return f'Configuration: {name}'
    if 'test' in str(fpath).lower(): return f'Test module: {name}'
    return f'Python module: {name}'

def tags_for(fpath, ntype):
    tags = [ntype]
    p = str(fpath)
    for kw in ['seekflow','engineering','solidworks','ansys','nx','cadquery',
                'gear','turbine','generative','agent','tools','mcp','deepseek']:
        if kw in p.lower(): tags.append(kw)
    if '/test' in p.lower(): tags.append('test')
    if any(p.startswith(d) for d in ['docs/','README']): tags.append('documentation')
    return list(set(tags))

# Scan
nodes, edges, nid_map = [], [], {}
for fpath in sorted(root.rglob('*')):
    parts = fpath.relative_to(root).parts
    if any(p in SKIP_DIRS for p in parts): continue
    if fpath.suffix in SKIP_SUFFIX: continue
    if not fpath.is_file(): continue
    if fpath.suffix in ('.step','.sldprt','.prt') and fpath.stat().st_size > 50000: continue

    rel = str(fpath.relative_to(root)).replace('\\', '/')
    ntype = TYPE_MAP.get(fpath.suffix, 'document')
    ua_id = f'{ntype}:{rel}'
    nodes.append({
        'id': ua_id, 'type': ntype, 'name': fpath.name,
        'filePath': rel, 'summary': summary_for(fpath, ntype),
        'tags': tags_for(fpath, ntype), 'complexity': 'simple',
        'size': fpath.stat().st_size,
    })
    nid_map[rel] = ua_id

# Import edges
for n in nodes:
    if n['type'] != 'file': continue
    try:
        content = (root / n['filePath']).read_text(encoding='utf-8', errors='ignore')[:8000]
        for m in re.finditer(r'(?:from|import)\s+(seekflow(?:[\w._]*)?)', content):
            mod = m.group(1)
            mp = mod.replace('.', '/') + '.py'
            for orel, oid in nid_map.items():
                if mp in orel:
                    edges.append({'source': n['id'], 'target': oid,
                        'type': 'imports', 'direction': 'forward', 'weight': 0.7})
                    break
    except: pass

# Layers
def fltr(patterns):
    return [n['id'] for n in nodes if any(p in n.get('filePath','') for p in patterns)]

layers = [
    {'id': 'layer_core_runtime', 'name': 'Core Runtime', 'description':
     'ToolRuntime, DeepSeekClient, retry, cache, policy, security, sandbox',
     'nodeIds': fltr(['seekflow/runtime.py','seekflow/client.py','seekflow/retry',
     'seekflow/cache.py','seekflow/types.py','seekflow/errors.py','seekflow/policy.py',
     'seekflow/security.py','seekflow/sandbox.py','seekflow/async_runtime.py'])},
    {'id': 'layer_agent', 'name': 'Agent Layer', 'description':
     'DeepSeekAgent, Crew, StateGraph, Memory, Checkpoint, Events',
     'nodeIds': [n['id'] for n in nodes if 'agent/' in n.get('filePath','')]},
    {'id': 'layer_tools', 'name': 'Tools & Executors', 'description':
     'Tool decorator, registry, runners, builtins, manifests, policies',
     'nodeIds': [n['id'] for n in nodes if 'tools/' in n.get('filePath','')]},
    {'id': 'layer_mcp', 'name': 'MCP Integration', 'description':
     'MCP protocol adapter, config, executor, gateway',
     'nodeIds': [n['id'] for n in nodes if 'mcp/' in n.get('filePath','')]},
    {'id': 'layer_deepseek', 'name': 'DeepSeek Adapter', 'description':
     'API params, protocol validation, strict schema, cache metrics',
     'nodeIds': [n['id'] for n in nodes if 'deepseek/' in n.get('filePath','')]},
    {'id': 'layer_engineering', 'name': 'Engineering Tools', 'description':
     'SolidWorks/NX/ANSYS/CadQuery, generative CAD, geometry primitives',
     'nodeIds': [n['id'] for n in nodes if 'integrations/engineering_tools/src' in n.get('filePath','')]},
    {'id': 'layer_tests', 'name': 'Tests', 'description': 'Unit and integration tests',
     'nodeIds': [n['id'] for n in nodes if 'tests/' in n.get('filePath','')]},
    {'id': 'layer_docs', 'name': 'Documentation', 'description': 'All documentation files',
     'nodeIds': [n['id'] for n in nodes if n['type'] == 'document']},
    {'id': 'layer_config', 'name': 'Configuration', 'description': 'Project config files',
     'nodeIds': [n['id'] for n in nodes if n['type'] == 'config']},
]
layers = [l for l in layers if l['nodeIds']]

# Tour
def first_by(pattern):
    return [n['id'] for n in nodes if pattern in n.get('filePath','')][:1]
def top_by(patterns, max_n=4):
    return [n['id'] for n in nodes if any(p in n.get('filePath','') for p in patterns)][:max_n]

tour = [
    {'order':1,'title':'Project Overview','description':'Start with the README.',
     'nodeIds':first_by('README.md')},
    {'order':2,'title':'Core Runtime','description':'Tool loop, client, retry.',
     'nodeIds':top_by(['seekflow/runtime.py','seekflow/client.py','seekflow/retry_executor.py'],3)},
    {'order':3,'title':'Agent System','description':'Agent, Crew, StateGraph.',
     'nodeIds':top_by(['agent/agent.py','agent/crew.py','agent/stategraph.py'],3)},
    {'order':4,'title':'Tool System','description':'Decorator, registry, executor.',
     'nodeIds':top_by(['tools/decorator.py','tools/registry.py','tools/executor.py'],3)},
    {'order':5,'title':'Engineering Tools','description':'SW, NX, ANSYS, CadQuery.',
     'nodeIds':top_by(['solidworks/com_client','nx/nx_bridge','ansys/apdl_runner','cadquery_backend/builder'],4)},
    {'order':6,'title':'Generative CAD','description':'Dialects, IR, validation.',
     'nodeIds':top_by(['generative_cad'],4)},
    {'order':7,'title':'Geometry Primitives','description':'Gears, turbomachinery.',
     'nodeIds':top_by(['geometry_primitives'],4)},
]
tour = [t for t in tour if t['nodeIds']]

types = {}
for n in nodes: types[n['type']] = types.get(n['type'], 0) + 1

graph = {
    'version': '1.0.0',
    'project': {
        'name': 'seekflow-engineering',
        'languages': ['python', 'markdown', 'json', 'yaml', 'toml', 'apdl'],
        'frameworks': ['DeepSeek', 'Pydantic', 'CadQuery', 'SolidWorks API', 'NXOpen', 'ANSYS APDL'],
        'description': 'DeepSeek-native zero-trust tool gateway with SolidWorks 2025, NX 12.0, ANSYS 18.1 and CadQuery engineering tools',
        'analyzedAt': datetime.now().isoformat(),
        'gitCommitHash': '7523164',
    },
    'nodes': nodes, 'edges': edges, 'layers': layers, 'tour': tour,
}

kg_path = root / '.understand-anything' / 'knowledge-graph.json'
kg_path.write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding='utf-8')
shutil.copy(kg_path, r'C:/understand-anything-plugin/packages/dashboard/dist/knowledge-graph.json')
print(f'OK: {len(nodes)} nodes, {len(edges)} edges, {len(layers)} layers, {len(tour)} tour steps')
