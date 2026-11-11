import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'codex-gif-video/scripts'))
import native_gif as g
import style_router as router


class StyleTests(unittest.TestCase):
    def test_complete_lemo_coverage_excludes_template(self):
        c=router.catalog()
        source={p.parent.name for p in (ROOT/'codex-gif-video/references/lemo-source/styles').glob('*/STYLE.md')}
        ids={s['id'] for s in c['styles'] if s['source']}
        self.assertEqual(ids,source);self.assertEqual(len(ids),66)
        self.assertEqual(len(c['styles']),69);self.assertNotIn('_template',ids)

    def test_every_named_style_resolves_and_compiles(self):
        request=g.read_json(ROOT/'examples/shot.json')
        for item in router.catalog()['styles']:
            with self.subTest(style=item['id']):
                r=copy.deepcopy(request);r['style']=item['name_zh'];r['illustrative_only']=True
                m,_=g.compile_request(r,ROOT/'examples')
                self.assertEqual(m['style']['preset'],item['id'])
                self.assertIn(item['appearance'],m['assets'][0]['prompt'])
                self.assertEqual(m['style_selection']['basis'],'explicit')

    def test_auto_routing_examples(self):
        for text,want in [('用白板讲解为什么下雨','whiteboard'),('用蓝图讲解机械结构','blueprint'),
                          ('透明玻璃美妆产品','glass-product'),('儿童蜡笔绘本睡前故事','crayon-book'),
                          ('供应链的流程解释','iso-infographic')]:
            with self.subTest(text=text):
                self.assertEqual(router.recommend(text)['selected'],want)

    def test_explicit_style_beats_auto_and_lock(self):
        req=g.read_json(ROOT/'examples/shot.json');req.update(style='水彩笔刷',style_lock='paper-popup')
        m,_=g.compile_request(req,ROOT/'examples')
        self.assertEqual(m['style']['preset'],'watercolor')

    def test_continuity_lock_beats_new_topic_keywords(self):
        req=g.read_json(ROOT/'examples/shot.json');req.update(style='auto',style_lock='paper-popup',topic='玻璃产品')
        m,_=g.compile_request(req,ROOT/'examples')
        self.assertEqual(m['style']['preset'],'paper-popup');self.assertEqual(m['style_selection']['basis'],'continuity_lock')

    def test_character_profile_keeps_style_across_batches(self):
        req=g.read_json(ROOT/'examples/shot.json')
        req['character']={'id':'hero','version':'1','description':'same recurring person','style_lock':'paper-popup'}
        req['topic']='玻璃产品'
        m,_=g.compile_request(req,ROOT/'examples')
        self.assertEqual(m['style']['preset'],'paper-popup')
        req['style']='midcentury-toon'
        m,_=g.compile_request(req,ROOT/'examples')
        self.assertEqual(m['style']['preset'],'midcentury-toon')

    def test_source_style_does_not_invent_evidence(self):
        self.assertEqual(router.recommend('卫星遥感地理变化')['status'],'needs_source')
        req=g.read_json(ROOT/'examples/shot.json');req['style']='satellite-briefing'
        with self.assertRaisesRegex(ValueError,'source_material'):
            g.compile_request(req,ROOT/'examples')
        req['illustrative_only']=True;m,_=g.compile_request(req,ROOT/'examples')
        self.assertTrue(m['style_selection']['illustrative_only'])
        self.assertIn('synthetic illustration',m['assets'][0]['prompt'])

    def test_character_auto_does_not_choose_faceless_style_without_reason(self):
        r=router.recommend('人物讲解，保持同一张脸',has_character=True)
        self.assertEqual(router.get_style(r['selected'])['character_support'],'full')

    def test_avoid_style_and_unknown_explicit_style(self):
        r=router.recommend('温柔的自然水彩',avoid_styles=['watercolor'])
        self.assertNotEqual(r['selected'],'watercolor')
        with self.assertRaisesRegex(ValueError,'unknown_style'):
            router.get_style('not-a-real-style')

    def test_negated_styles_are_not_positive_preferences(self):
        for text,forbidden in [('不要水彩，用适合儿童的风格','watercolor'),('不要用水彩，改用纸艺','watercolor'),('我不要纸艺，要自然人物','papercut'),('avoid watercolor, use a simple illustration','watercolor')]:
            with self.subTest(text=text):
                r=router.recommend(text,has_character=True)
                self.assertNotEqual(r['selected'],forbidden)
                self.assertNotIn(forbidden,[c['id'] for c in r['candidates']])

    def test_explicit_style_does_not_send_old_lock_to_model(self):
        req=g.read_json(ROOT/'examples/shot.json');req['style']='midcentury-toon'
        req['character']={'id':'hero','version':'1','description':'same person','style_lock':'paper-popup'}
        m,_=g.compile_request(req,ROOT/'examples')
        self.assertEqual(m['character']['style_lock'],'paper-popup')
        self.assertNotIn('style_lock',m['assets'][0]['prompt'])

    def test_full_source_exclusions_reach_animation_prompt(self):
        req=g.read_json(ROOT/'examples/shot.json');req['style']='watercolor'
        m,_=g.compile_request(req,ROOT/'examples')
        prompt=m['assets'][0]['prompt']
        self.assertIn("not a children's picture book",prompt)
        self.assertIn('Paper is the white',prompt)
        review=m['style']['source_review']
        self.assertIn('## 1. Essence, and what it is not',review['included_sections'])
        self.assertIn('## 7. Sound palette',review['omitted_sections'])
        self.assertNotIn('## 7. Sound palette',prompt)
        self.assertNotIn('## 10. Engine',prompt)

    def test_complete_guide_is_available_but_not_blindly_injected(self):
        guide=router.source_guide(router.get_style('crayon-book'))
        self.assertIn('## 7. Sound palette',guide['full_source'])
        self.assertNotIn('## 7. Sound palette',guide['visual_excerpt'])
        self.assertNotIn('12 fps',guide['visual_excerpt'])
        self.assertIn('current GIF request timing',guide['visual_excerpt'])
        self.assertIn('never black',guide['visual_excerpt'])

    def test_reference_and_animation_share_verified_visual_source(self):
        ref=router.reference_prompt('crayon-book','A blond prince and a russet fox.')
        profile,_=router.resolve_profile({'style':'crayon-book'})
        self.assertEqual(ref['source_review']['sha256'],profile['source_review']['sha256'])
        for rule in ('never black','At most one watercolour','wax'):
            self.assertIn(rule,ref['prompt']);self.assertIn(rule,profile['description'])
        self.assertIn('one static character master',ref['prompt'])
        self.assertNotIn('## 5. Motion quality',ref['prompt'])
        self.assertNotIn('## 6. Camera grammar',ref['prompt'])
        self.assertNotIn('## 7. Sound palette',ref['prompt'])

    def test_visual_pitfalls_reach_reference_and_animation(self):
        ref=router.reference_prompt('crayon-book','A blond prince and a russet fox.')
        profile,_=router.resolve_profile({'style':'crayon-book'})
        for prompt in (ref['prompt'],profile['description']):
            self.assertIn('Characters vanish under a wash',prompt)
            self.assertIn('Outlines over hair read as a headband',prompt)
            self.assertNotIn('Reverb IR from unit-variance noise',prompt)
        self.assertIn('## 9. Pitfalls of the medium',ref['source_review']['included_sections'])

    def test_changed_source_does_not_keep_old_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'source.md').write_text('changed source')
            entry=copy.deepcopy(router.get_style('watercolor'))
            entry['source']['local_path']='source.md'
            with patch.object(router,'SKILL_ROOT',root):
                with self.assertRaisesRegex(ValueError,'style_source_hash_mismatch'):
                    router.source_guide(entry)


if __name__=='__main__':unittest.main(verbosity=2)
