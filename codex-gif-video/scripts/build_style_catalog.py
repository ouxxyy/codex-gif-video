#!/usr/bin/env python3
"""Build portable GIF style cards from pinned, verified Lemo style documentation."""
import hashlib,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'references/lemo-source'


def build():
    provenance=json.loads((SOURCE/'provenance.json').read_text())
    for e in provenance['entries']:
        raw=(SOURCE/e['path']).read_bytes()
        actual=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        if actual!=e['sha']:raise ValueError('source_blob_mismatch:'+e['path'])
    adaptations={}
    for line in (ROOT/'references/style-adaptations.tsv').read_text().splitlines():
        slug,keywords,look,motion,identity=line.split('\t')
        if slug in adaptations:raise ValueError('duplicate_style:'+slug)
        adaptations[slug]=(keywords.split(','),look,motion,identity)
    source_ids={p.parent.name for p in (SOURCE/'styles').glob('*/STYLE.md')}
    if set(adaptations)!=source_ids:raise ValueError('adaptation_coverage_mismatch')
    entries=[]
    text_heavy={'ascii-crt','caption-news','countdown','news-package','swiss-motion','chalkboard','whiteboard'}
    mono={'ascii-crt','blueprint','ink-wash','engraving','woodcut','rubber-hose','silent-film','printed-long-take','papercut-red'}
    for slug in sorted(source_ids):
        folder=SOURCE/'styles'/slug
        meta=json.loads((folder/'style.json').read_text())
        doc=(folder/'STYLE.md').read_text()
        keywords,look,motion,identity=adaptations[slug]
        source_required=meta['category_en'] in ('Edit & Documentary','Evidence Films') or slug in ('dataviz','living-screencast')
        limits=['Only a short native GIF shot; original film editing, audio, fonts and code renderer are excluded.',
                'Keep material texture stable; adapt timing to the requested 2–16 frames without claiming the source film frame rate.']
        if source_required:limits.append('Requires user source material, or an explicit illustrative_only declaration; generated imagery is not documentary evidence.')
        if slug in text_heavy:limits.append('Visual/layout grammar only; exact text and subtitles belong to downstream tools.')
        entry={'id':slug,'name_zh':meta['cn'],'name_en':meta['en'],'family_zh':meta['category_cn'],'family_en':meta['category_en'],
               'aliases':[meta['cn'],meta['en'],slug.replace('-',' ')], 'keywords':keywords,'use_cases':meta.get('uses',[]),
               'appearance':look,'motion':motion,'camera':'单个短镜头，默认固定构图；只有讲解需要时才做幅度很小的镜头运动。',
               'character_support':identity,'palette_policy':'restricted' if slug in mono else 'color',
               'requires_source_material':source_required,'adaptation':'visual_grammar_only' if source_required or slug in text_heavy else 'native_gif_visual',
               'limitations':limits,'validation':{'state':'adapted_not_render_tested','evidence':[]},
               'source':{'repository':'lemomo-ai/lemo-opuscar','commit':provenance['commit'],'path':f'styles/{slug}/STYLE.md',
                         'url':f"https://github.com/lemomo-ai/lemo-opuscar/blob/{provenance['commit']}/styles/{slug}/STYLE.md",
                         'local_path':f'references/lemo-source/styles/{slug}/STYLE.md','sha256':hashlib.sha256((folder/'STYLE.md').read_bytes()).hexdigest()},
               'source_essence':next((line[2:] for line in doc.splitlines() if line.startswith('> ') and not line.startswith('> References')), '')}
        entries.append(entry)
    for slug,zh,en,kw,look,motion in [
        ('flat','通用扁平插画','Flat Illustration',['扁平插画','清爽插画','flat illustration'],'简洁实色、稳定墨线、克制配色和完整背景。','清楚剪影、自然重心转移、动作有预备和收势。'),
        ('papercut','通用纸艺','Paper-cut Illustration',['纸艺','纸片','paper cut'],'哑光纸层、固定厚度和柔和层间阴影，颜色稳定。','关节姿态连贯，纸形稳定，不融化或随机抖动。'),
        ('clay','黏土微缩','Clay Miniature',['黏土','粘土','clay'],'柔光下的黏土微缩人物，雕塑特征和体积稳定。','有重量的关节动作与收势，不以变形代替动作。')]:
        entries.append({'id':slug,'name_zh':zh,'name_en':en,'family_zh':'原生基础','family_en':'Native Basics','aliases':[zh,en],
                        'keywords':kw,'use_cases':['General explainers'],'appearance':look,'motion':motion,
                        'camera':'固定构图，确保主体完整。','character_support':'full','palette_policy':'color',
                        'requires_source_material':False,'adaptation':'native_gif_visual',
                        'limitations':['A visual preset, not a guarantee of identity or motion quality.'],
                        'validation':{'state':'adapted_not_render_tested','evidence':[]},'source':None})
    catalog={'schema_version':1,'catalog_version':'1.0.0','lemo_commit':provenance['commit'],'lemo_style_count':len(source_ids),
             'native_baseline_count':3,'style_count':len(entries),'styles':entries}
    target=ROOT/'assets/style-catalog.json'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n')
    lines=['# 风格全集','',f"Lemo {len(source_ids)} 种正式风格 + 3 种原生基础预设。模板不计数。固定提交 `{provenance['commit']}`。",
           '', '所有条目均完成原生 GIF 提示适配；实际生成/人物验证范围单独记录，不把目录覆盖当成质量通过。', '',
           '| ID | 风格 | 分类 | 人物细节 | 来源要求 | 适配范围 |', '|---|---|---|---|---|---|']
    for e in entries:
        support={'full':'可保留细节','reduced':'简化/远景','none':'非人物主导'}[e['character_support']]
        lines.append(f"| `{e['id']}` | {e['name_zh']} | {e['family_zh']} | {support} | {'真实素材或明确示意' if e['requires_source_material'] else '可直接视觉生成'} | {'仅视觉语法' if e['adaptation']=='visual_grammar_only' else '原生GIF视觉风格'} |")
    (ROOT/'references/style-index.md').write_text('\n'.join(lines)+'\n')
    return catalog

if __name__=='__main__':
    c=build();print(json.dumps({k:c[k] for k in ('lemo_style_count','native_baseline_count','style_count','lemo_commit')}))
