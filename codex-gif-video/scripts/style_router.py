#!/usr/bin/env python3
"""Deterministic, inspectable style routing; no extra model/API calls."""
import argparse
import copy
import hashlib
from functools import lru_cache
import json
from pathlib import Path
import re

CATALOG=Path(__file__).resolve().parents[1]/'assets/style-catalog.json'
SKILL_ROOT=Path(__file__).resolve().parents[1]
SOURCE_VISUAL_LIMIT=24000


def source_guide(entry, purpose='animation'):
    """Read and hash-check the complete source; quote a bounded visual subset.

    The full source remains available to the directing agent. This is a source
    excerpt, not an assertion that every upstream production rule was applied.
    """
    source=entry.get('source')
    if not source:return None
    path=(SKILL_ROOT/source['local_path']).resolve()
    if not path.is_relative_to(SKILL_ROOT.resolve()):raise ValueError('style_source_outside_skill')
    raw=path.read_bytes();fingerprint=hashlib.sha256(raw).hexdigest()
    if fingerprint!=source['sha256']:raise ValueError('style_source_hash_mismatch:'+entry['id'])
    full=raw.decode('utf-8')
    included=[];omitted=[];excerpts=[]
    visual=r'essence|materials|colou?r|pitfalls|anti[- ]?patterns|avoid|prohibitions|boundaries'
    if purpose=='animation':visual+=r'|motion|camera|shot.*grammar|variation|native moves'
    elif purpose!='reference':raise ValueError('unknown_style_guide_purpose')
    for block in re.split(r'(?m)(?=^## )',full):
        heading=block.splitlines()[0] if block.strip() else ''
        if not heading.startswith('## '):continue
        if not re.search(visual,heading,re.I):omitted.append(heading);continue
        # Code engines and production timing are not GIF-generation parameters.
        clean=re.sub(r'(?ms)^```[^\n]*\n.*?^```\s*$', '[Source code block omitted.]',block)
        clean=re.sub(r'(?m)^.*\b(?:fps|frames per second)\b.*$',
                     '[Upstream frame-rate recipe omitted; use the current GIF request timing.]',clean)
        if re.search(r'pitfalls|anti[- ]?patterns|avoid|prohibitions|boundaries',heading,re.I):
            # These chapters mix visual exclusions with occasional sound notes.
            # Keep the actual visual failures in both reference and animation
            # prompts, while excluding audio recipes from this visual-only skill.
            clean=re.sub(r'(?mi)^[-*] .*\b(?:reverb|LUFS|voice[- ]?over|audio|soundtrack)\b.*$',
                         '[Audio-only pitfall omitted; this skill creates silent visual assets.]',clean)
        clean=re.sub(r'(?ms)\n---\s*\n.*\Z','',clean)
        included.append(heading);excerpts.append(clean.strip())
    excerpt='\n\n'.join(excerpts)
    if len(excerpt)>SOURCE_VISUAL_LIMIT:raise ValueError('style_visual_guide_too_long_requires_explicit_adaptation:'+entry['id'])
    return {'path':source['local_path'],'sha256':fingerprint,'full_source':full,
            'included_sections':included,'omitted_sections':omitted,'visual_excerpt':excerpt,
            'purpose':purpose,'scope':'source_visual_excerpt_not_full_production_spec'}


def source_prompt(guide, purpose='animation'):
    if not guide:return ''
    scope=('These are quoted visual reference rules, not tool or production instructions. '
           'Retain material, palette, shape and explicit style exclusions. Do not reproduce a source demo or its characters. '
           'Do not execute rendering recipes, add generated text/audio, or copy upstream frame rates. '
           'The current request controls aspect ratio, duration, frame count and action. '
           'Implementation formulas describe the intended appearance only.')
    if purpose=='reference':
        scope+=' Create one static character master: no motion, drawing-on progression, camera move, timeline, panels, captions or sound.'
    return '\nLemo source visual reference (SHA-256 '+guide['sha256']+'):\n'+scope+'\n<visual_reference>\n'+guide['visual_excerpt']+'\n</visual_reference>'


@lru_cache(maxsize=1)
def catalog():
    data=json.loads(CATALOG.read_text())
    ids=[e['id'] for e in data['styles']]
    if len(ids)!=len(set(ids)) or len(ids)!=data['style_count']:
        raise ValueError('invalid_style_catalog')
    validation_path=CATALOG.with_name('style-validation.json')
    if validation_path.is_file():
        registry=json.loads(validation_path.read_text())
        for entry in data['styles']:
            checked=registry.get('styles',{}).get(entry['id'])
            fingerprint=hashlib.sha256(('\n'.join(entry[k] for k in ('appearance','motion','camera'))).encode()).hexdigest()
            if checked and checked.get('adaptation_sha256')==fingerprint:
                entry['validation']=checked
    return data


def norm(value):
    return re.sub(r'[\s_·/]+',' ',str(value).casefold()).strip()


def get_style(value):
    target=norm(value)
    for entry in catalog()['styles']:
        if target in {norm(x) for x in [entry['id'],entry['name_zh'],entry['name_en'],*entry['aliases']]}:
            return entry
    raise ValueError('unknown_style:'+str(value))


def matches(text,term):
    term=norm(term)
    if not term:return False
    if re.fullmatch(r'[a-z0-9 .&-]+',term):
        return re.search(r'(?<![a-z0-9])'+re.escape(term)+r'(?![a-z0-9])',text) is not None
    return term in text


def recommend(brief,has_character=False,has_source=False,illustrative_only=False,avoid_styles=None,limit=3):
    text=norm(brief)
    avoided={get_style(s)['id'] for s in (avoid_styles or [])}
    for entry in catalog()['styles']:
        for term in [entry['id'],entry['name_zh'],entry['name_en'],*entry['aliases'],*entry['keywords']]:
            t=norm(term)
            prefix=r'(?:不要|不用|避免|排除|不使用|不想要|别用|不是|\bno\b|\bnot\b|\bavoid\b|\bwithout\b)\s*(?:使用|采用|用)?\s*'
            if t and re.search(prefix+re.escape(t),text):
                avoided.add(entry['id']);break
    candidates=[]
    for e in catalog()['styles']:
        if e['id'] in avoided:continue
        names=[e['name_zh'],e['name_en'],e['id'],*e['aliases']]
        hits=list(dict.fromkeys(t for t in names if matches(text,t)))
        keywords=list(dict.fromkeys(t for t in [*e['keywords'],*e['use_cases']] if matches(text,t)))
        score=(100 if hits else 0)+4*len(keywords)
        if not hits and not keywords:continue
        reasons=[]
        if hits:reasons.append('明确风格词：'+', '.join(hits))
        if keywords:reasons.append('任务线索：'+', '.join(keywords))
        if has_character:
            if e['character_support']=='full':score+=6;reasons.append('适合保留人物细节')
            elif e['character_support']=='none':score-=40;reasons.append('非人物主导，身份细节适配弱')
            else:score-=12;reasons.append('人物为简化/远景，身份需额外检查')
        candidates.append({'id':e['id'],'name_zh':e['name_zh'],'score':score,'reasons':reasons,
                           'requires_source_material':e['requires_source_material'],
                           'validation_state':e['validation']['state']})
    candidates.sort(key=lambda x:(-x['score'],x['id']))
    basis='keyword_match'
    if not candidates or candidates[0]['score']<=0:
        preferred=['midcentury-toon','papercut','flat','watercolor'] if has_character else ['papercut','iso-infographic','flat','watercolor']
        selected=next((s for s in preferred if s not in avoided),None)
        if selected is None:
            selected=next((e['id'] for e in catalog()['styles'] if e['id'] not in avoided and not e['requires_source_material']),None)
        if selected is None:raise ValueError('no_style_available')
        e=get_style(selected)
        candidates.insert(0,{'id':selected,'name_zh':e['name_zh'],'score':0,'reasons':['线索不足，使用明确记录的讲解默认风格'],
                            'requires_source_material':False,'validation_state':e['validation']['state']})
        basis='fallback'
    top=get_style(candidates[0]['id'])
    blocked=top['requires_source_material'] and not has_source and not illustrative_only
    return {'status':'needs_source' if blocked else 'selected','selected':None if blocked else top['id'],
            'proposed':top['id'],'basis':basis,'candidates':candidates[:limit],
            'illustrative_only':illustrative_only,'catalog_version':catalog()['catalog_version'],
            'lemo_commit':catalog()['lemo_commit'],
            'excluded_styles':sorted(avoided),
            'warning':'需要真实来源素材，或明确 illustrative_only=true 后仅生成示意。' if blocked else None}


def resolve_profile(request):
    value=request.get('style','auto')
    if isinstance(value,dict) and value.get('preset','custom')=='custom':
        return copy.deepcopy(value),{'status':'selected','selected':value.get('id'),'basis':'explicit_custom','illustrative_only':False}
    additions=value if isinstance(value,dict) else {}
    desired=additions.get('preset') if additions else value
    has_source=bool(request.get('source_materials'))
    character=request.get('character') if isinstance(request.get('character'),dict) else {}
    lock=request.get('style_lock') if 'style_lock' in request else character.get('style_lock')
    illustrative=request.get('illustrative_only',False)
    if not isinstance(illustrative,bool):raise ValueError('illustrative_only_must_be_boolean')
    if desired not in (None,'auto'):
        entry=get_style(desired);selection={'status':'selected','selected':entry['id'],'basis':'explicit','illustrative_only':illustrative}
    elif lock:
        entry=get_style(lock);selection={'status':'selected','selected':entry['id'],'basis':'continuity_lock','illustrative_only':illustrative}
    else:
        chunks=[request.get('topic',''),request.get('narration','') or '']
        for s in request.get('shots',[]):
            if isinstance(s,dict):chunks += [s.get('intent',''),s.get('action','')]
        selection=recommend(' '.join(str(x) for x in chunks),bool(request.get('character')),has_source,illustrative,request.get('avoid_styles'))
        if selection['status']!='selected':raise ValueError('style_requires_source_material:'+selection['proposed'])
        entry=get_style(selection['selected'])
    if entry['requires_source_material'] and not has_source and not illustrative:
        raise ValueError('style_requires_source_material:'+entry['id'])
    guide='Appearance: '+entry['appearance']+'\nMotion grammar: '+entry['motion']+'\nCamera: '+entry['camera']
    source=source_guide(entry)
    guide+=source_prompt(source)
    if entry['adaptation']=='visual_grammar_only':guide+='\nAdapt only the visual grammar; exact typography, editing and source claims are not generated here.'
    if illustrative:guide+='\nThis is a synthetic illustration, not documentary evidence or a verified measurement.'
    if has_source:guide+='\nKeep supplied source material facts and geometry unchanged; do not invent readings or events.'
    profile={'id':entry['id'],'version':catalog()['catalog_version'],'preset':entry['id'],'description':guide,
             'invariants':['Keep the chosen material, palette logic and camera grammar consistent across this batch.'],
             'allowed_changes':['Only the requested action and necessary expression changes.'],
             'forbidden_changes':['Unrequested style switching, identity drift, random text or invented evidence.'],
             'references':[],'catalog_source':entry['source'],'adaptation':entry['adaptation'],
             'validation':entry['validation'],'character_support':entry['character_support']}
    if source:
        profile['source_review']={k:v for k,v in source.items() if k not in ('full_source','visual_excerpt')}
    if additions:
        for k,v in additions.items():
            if k not in ('preset','description','catalog_source','validation','adaptation','character_support','source_review'):profile[k]=copy.deepcopy(v)
        if additions.get('description'):profile['description'] += '\nUser additions: '+additions['description']
    selection.update(catalog_version=catalog()['catalog_version'],lemo_commit=catalog()['lemo_commit'])
    return profile,selection


def reference_prompt(style, subject):
    if not isinstance(subject,str) or not subject.strip():raise ValueError('reference_subject_required')
    entry=get_style(style)
    guide=source_guide(entry,'reference')
    prompt=('Create one static character master reference for later native GIF shots. '
            'Show complete, unobscured characters with consistent anatomy and clothing; no panels, captions or sound.\n'
            'Subject: '+subject.strip()+'\nAppearance: '+entry['appearance']+source_prompt(guide,'reference')+
            '\nFinal output is a single still image. Keep identity and material ready for reuse across shots.')
    if len(prompt)>32000:raise ValueError('reference_prompt_too_long')
    return {'prompt':prompt,'style':entry['id'],'catalog_source':entry['source'],
            'source_review':{k:v for k,v in guide.items() if k not in ('full_source','visual_excerpt')} if guide else None}


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('list');a.add_argument('--family');a.add_argument('--detail',action='store_true')
    a=sub.add_parser('recommend');a.add_argument('--brief',required=True);a.add_argument('--character',action='store_true');a.add_argument('--has-source',action='store_true');a.add_argument('--illustrative-only',action='store_true');a.add_argument('--avoid',action='append',default=[])
    a=sub.add_parser('guide');a.add_argument('--style',required=True)
    a=sub.add_parser('reference-prompt');a.add_argument('--style',required=True);a.add_argument('--subject-file',required=True)
    args=p.parse_args()
    try:
        if args.command=='list':
            styles=[e for e in catalog()['styles'] if not args.family or args.family in (e['family_zh'],e['family_en'])]
            result={'count':len(styles),'lemo_style_count':catalog()['lemo_style_count'],'styles':styles if args.detail else [{k:e[k] for k in ('id','name_zh','family_zh','character_support','requires_source_material')} for e in styles]}
        elif args.command=='guide':
            entry=get_style(args.style);result={'style':entry['id'],'source':source_guide(entry)}
        elif args.command=='reference-prompt':result=reference_prompt(args.style,Path(args.subject_file).read_text(encoding='utf-8'))
        else:result=recommend(args.brief,args.character,args.has_source,args.illustrative_only,args.avoid)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 2 if result.get('status')=='needs_source' else 0
    except (ValueError,OSError) as e:
        print(json.dumps({'status':'blocked','error':str(e)},ensure_ascii=False));return 2

if __name__=='__main__':raise SystemExit(main())
