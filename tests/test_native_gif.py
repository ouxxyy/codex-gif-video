"""Offline synthetic fixtures; never evidence of generated animation quality."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'codex-gif-video/scripts/native_gif.py'
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location('native_gif', SCRIPT)
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


def gif_bytes(count=16, size=(256, 144), delay=150):
    frames=[]
    for i in range(count):
        f=Image.new('RGB',size,'white')
        ImageDraw.Draw(f).rectangle([i*3,10,i*3+10,25],fill='red')
        frames.append(f)
    out=io.BytesIO()
    frames[0].save(out,format='GIF',save_all=True,append_images=frames[1:],duration=delay,loop=0,optimize=False)
    return out.getvalue()


class NativeGifTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.bundle=self.root/'bundle'; self.budget=self.root/'budget.json'
        self.request=g.read_json(ROOT/'examples/shot.json'); self.request_file=self.root/'request.json'
        self.request['shots'][0]['size']='256x144'

    def prepare(self):
        g.write_json(self.request_file,self.request)
        return g.prepare(self.request_file,self.bundle)

    def native_input(self,raw=None,model=g.MODELS[0]):
        raw=raw if raw is not None else gif_bytes()
        file=self.root/'native-output'; file.write_bytes(raw)
        log=self.root/'tool.txt'; log.write_text('SYNTHETIC UNIT TEST LOG; no actual model was called.')
        evidence=self.root/'evidence.json'
        m=g.read_json(self.bundle/'manifest.json')
        g.write_json(evidence,{'source_kind':'codex_native_gif','asset_sha256':g.digest(raw),'reported_model':model,
                    'spec_sha256':m['assets'][0]['spec_sha256'],'tool_log':log.name})
        return file,evidence

    def import_result(self,raw=None,model=g.MODELS[0]):
        file,evidence=self.native_input(raw,model)
        reservation=g.reserve(self.budget,'gif','burden-up')
        result=g.import_native(self.bundle,'burden-up',file,evidence,self.budget,reservation['id'])
        return g.read_json(self.bundle/'manifest.json'),result,reservation

    def review_file(self,m,**overrides):
        attempt=m['assets'][0]['attempts'][-1]
        evidence=self.root/'test-review.txt'; evidence.write_text('SYNTHETIC TEST ONLY, not real visual review.')
        r={'asset_sha256':attempt['sha256'],'reviewer':'unit-test-fixture','full_playback_observed':True,
           'all_frames_observed':True,'checks':{k:'pass' for k in g.QUALITY_KEYS},'evidence_files':[evidence.name]}
        r.update(overrides); path=self.root/'review.json'; g.write_json(path,r); return path

    def test_single_and_narration_prepare(self):
        m=self.prepare(); a=m['assets'][0]
        self.assertEqual(a['parameters']['frame_duration_ms'],150); self.assertIsNone(a['time_range_s'])
        n,_=g.compile_request(g.read_json(ROOT/'examples/narration.json'),ROOT/'examples')
        for a in n['assets']:
            start,end=a['source_span']; self.assertEqual(n['narration'][start:end],a['source_text'])

    def test_portrait_auto_size_resolves_before_generation(self):
        shot=self.request['shots'][0]
        shot.update(aspect_ratio='9:16',size='auto')
        a=self.prepare()['assets'][0]
        self.assertEqual(a['parameters']['size'],'288x512')
        self.assertEqual(a['size_selection']['basis'],'aspect_ratio_default')
        self.assertNotIn('aspect_ratio',a['parameters'])

    def test_exact_timing_selects_representable_frame_count(self):
        shot=self.request['shots'][0]; shot['target_duration_s']=5
        a=self.prepare()['assets'][0]
        self.assertEqual(a['parameters']['frame_count'],10)
        self.assertEqual(a['parameters']['frame_duration_ms'],500)
        self.assertEqual(a['timing_plan']['duration_error_s'],0)

    def test_explicit_unrepresentable_timing_rejected_before_prepare(self):
        self.request['shots'][0].update(target_duration_s=5,frame_count=16)
        with self.assertRaisesRegex(g.Failure,'frame_count_cannot_represent_exact_duration'):
            self.prepare()
        self.assertFalse((self.bundle/'manifest.json').exists())

    def test_quantization_is_explicit_and_visible(self):
        self.request['shots'][0].update(target_duration_s=5,frame_count=16,duration_policy='quantize')
        timing=self.prepare()['assets'][0]['timing_plan']
        self.assertEqual(timing['planned_duration_s'],4.96)
        self.assertEqual(timing['duration_error_s'],-0.04)

    def test_five_three_second_shots_total_exactly_fifteen(self):
        self.request['shots']=[dict(self.request['shots'][0],id=f'shot-{i}',target_duration_s=3) for i in range(5)]
        assets=self.prepare()['assets']
        self.assertEqual(sum(a['timing_plan']['planned_duration_s'] for a in assets),15)
        self.assertTrue(all(a['parameters']['frame_count']==15 and a['parameters']['frame_duration_ms']==200 for a in assets))

    def test_missing_shots_does_not_fake_semantic_planning(self):
        with self.assertRaisesRegex(g.Failure,'semantic_planning_required'):
            g.compile_request({'schema_version':1,'mode':'narration','narration':'原文'},self.root)

    def test_ambiguous_narration_requires_exact_span(self):
        r=g.read_json(ROOT/'examples/narration.json'); r['narration']*=2
        with self.assertRaisesRegex(g.Failure,'ambiguous'): g.compile_request(r,self.root)
        r['shots'][0]['source_start']=0; r['shots'][1]['source_start']=len(r['shots'][0]['source_text'])
        g.compile_request(r,self.root)
        r['shots'][0]['source_start']=1
        with self.assertRaisesRegex(g.Failure,'span_mismatch'): g.compile_request(r,self.root)

    def test_invalid_parameters(self):
        for field,value in [('frame_count',17),('frame_count',True),('target_duration_s',float('nan')),
                            ('target_duration_s',100),('size','1025x1024'),('size','1024x1024'),
                            ('id','../../evil'),('time_range_s',[5,2]),('aspect_ratio','4:3')]:
            with self.subTest(field=field,value=value):
                r=copy.deepcopy(self.request); r['shots'][0][field]=value
                with self.assertRaises(g.Failure): g.compile_request(r,self.root)
        self.request['model']='gpt-image-2'
        with self.assertRaisesRegex(g.Failure,'only_image_2_6'): g.compile_request(self.request,self.root)

    def test_malformed_inputs_report_json_without_traceback(self):
        bads=[[],{'schema_version':1,'mode':'shot','shots':[None]}]
        r=copy.deepcopy(self.request); r['style']={'id':'a','version':'1','description':'x','references':[None]}; bads.append(r)
        for i,bad in enumerate(bads):
            g.write_json(self.request_file,bad)
            p=subprocess.run([sys.executable,str(SCRIPT),'prepare','--request',str(self.request_file),'--out',str(self.root/f'bad{i}')],capture_output=True,text=True)
            self.assertEqual(p.returncode,2); self.assertEqual(json.loads(p.stderr)['status'],'blocked')
            self.assertNotIn('Traceback',p.stderr)

    def test_prepare_idempotent_and_changed_request_requires_new_bundle(self):
        m=self.prepare(); self.assertEqual(self.prepare()['created_at'],m['created_at'])
        self.request['shots'][0]['action']='不同动作'
        with self.assertRaisesRegex(g.Failure,'request_changed'): self.prepare()

    def test_all_style_rules_enter_prompt(self):
        self.request['style']={'id':'custom','version':'1','description':'style','preset':'custom','allowed_changes':['ALLOW_SENTINEL'],'forbidden_changes':['DENY_SENTINEL']}
        prompt=self.prepare()['assets'][0]['prompt']
        self.assertIn('ALLOW_SENTINEL',prompt); self.assertIn('DENY_SENTINEL',prompt)

    def test_reference_frozen_and_changed_bundle_rejected(self):
        file=self.root/'hero.png'; Image.new('RGB',(64,64),'blue').save(file)
        self.request['character']={'id':'hero','version':'1','description':'blue hero','references':[{'path':'hero.png','source':'test fixture'}]}
        m=self.prepare(); frozen=g.inside(self.bundle,m['references'][0]['path'])
        Image.new('RGB',(64,64),'red').save(file)
        self.assertNotEqual(g.digest(file.read_bytes()),g.digest(frozen.read_bytes()))
        frozen.write_bytes(b'changed')
        with self.assertRaisesRegex(g.Failure,'reference_changed'): g.native_request(self.bundle,'burden-up',self.budget)

    def test_native_request_only_reserves_and_exposes_prompt(self):
        self.prepare(); request=g.native_request(self.bundle,'burden-up',self.budget)
        self.assertEqual(request['entry'],'codex_session_native_tool')
        self.assertEqual(len(g.read_json(self.budget)['attempts']),1)
        self.assertFalse((self.bundle/'assets').exists())

    def test_native_request_uses_actual_codex_gif_argument(self):
        self.prepare()
        request=g.native_request(self.bundle,'burden-up',self.budget)
        self.assertEqual(request['native_tool_arguments']['gif'],{'frame_count':16,'frame_duration_ms':150})
        self.assertNotIn('output_format',request['native_tool_arguments'])
        self.assertNotIn('model',request['native_tool_arguments'])

    def test_native_reference_limit_is_five(self):
        file=self.root/'hero.png'; Image.new('RGB',(64,64),'blue').save(file)
        self.request['character']={'id':'hero','version':'1','description':'hero','references':[{'path':'hero.png','source':'test'} for _ in range(6)]}
        with self.assertRaisesRegex(g.Failure,'too_many_references'):
            self.prepare()

    def test_cli_probe_distinguishes_known_disabled_animation_flag(self):
        replies=[subprocess.CompletedProcess([],0,'codex-cli 0.169.0-alpha.7\n',''),
                 subprocess.CompletedProcess([],0,'image_generation_animation under development false\n','')]
        with patch.object(g.subprocess,'run',side_effect=replies):
            r=g.probe_cli('/tmp/test-only-codex')
        self.assertTrue(r['animation_flag_known'])
        self.assertFalse(r['animation_enabled'])

    def test_pending_native_request_is_idempotent(self):
        self.prepare()
        first=g.native_request(self.bundle,'burden-up',self.budget)
        second=g.native_request(self.bundle,'burden-up',self.budget)
        self.assertEqual(first['reservation']['id'],second['reservation']['id'])
        self.assertEqual(len(g.read_json(self.budget)['attempts']),1)

    def test_no_file_failure_requires_explicit_retry(self):
        self.prepare()
        first=g.native_request(self.bundle,'burden-up',self.budget)
        g.finish_attempt(self.budget,first['reservation']['id'],'failed','native tool failure')
        with self.assertRaisesRegex(g.Failure,'explicit_retry'):
            g.native_request(self.bundle,'burden-up',self.budget)
        second=g.native_request(self.bundle,'burden-up',self.budget,retry=True)
        g.finish_attempt(self.budget,second['reservation']['id'],'outcome_unknown','native tool timeout')
        with self.assertRaisesRegex(g.Failure,'explicit_retry'):
            g.native_request(self.bundle,'burden-up',self.budget)
        self.assertEqual(len(g.read_json(self.budget)['attempts']),2)

    def test_native_import_preserves_bytes_and_not_ready(self):
        self.prepare(); m,result,reservation=self.import_result()
        self.assertEqual(result['status'],'pending_review')
        attempt=m['assets'][0]['attempts'][0]
        self.assertEqual(g.inside(self.bundle,attempt['path']).read_bytes(),gif_bytes())
        file,evidence=self.native_input()
        again=g.import_native(self.bundle,'burden-up',file,evidence,self.budget,reservation['id'])
        self.assertTrue(again['reused']); self.assertEqual(len(g.read_json(self.budget)['attempts']),1)

    def test_import_disk_failure_can_resume_without_new_reservation(self):
        self.prepare(); file,evidence=self.native_input(); r=g.reserve(self.budget,'gif','burden-up')
        with patch.object(g,'save_result',side_effect=OSError('injected disk failure')):
            with self.assertRaises(OSError): g.import_native(self.bundle,'burden-up',file,evidence,self.budget,r['id'])
        result=g.import_native(self.bundle,'burden-up',file,evidence,self.budget,r['id'])
        self.assertEqual(result['status'],'pending_review'); self.assertEqual(len(g.read_json(self.budget)['attempts']),1)

    def test_native_reservation_cannot_import_different_file(self):
        self.prepare(); m,result,r=self.import_result()
        file,evidence=self.native_input(gif_bytes(delay=100))
        with self.assertRaisesRegex(g.Failure,'bound_to_other'): g.import_native(self.bundle,'burden-up',file,evidence,self.budget,r['id'])

    def test_reservation_cannot_cross_bundles_with_same_shot_id(self):
        self.prepare()
        request=g.native_request(self.bundle,'burden-up',self.budget)
        other=self.root/'other-bundle'
        g.prepare(self.request_file,other)
        file,evidence=self.native_input()
        with self.assertRaisesRegex(g.Failure,'request_binding_mismatch'):
            g.import_native(other,'burden-up',file,evidence,self.budget,request['reservation']['id'])
        self.assertEqual(g.read_json(self.budget)['attempts'][0]['status'],'reserved')
        result=g.import_native(self.bundle,'burden-up',file,evidence,self.budget,request['reservation']['id'])
        self.assertEqual(result['status'],'pending_review')

    def test_png_is_retained_as_failure(self):
        self.prepare(); buf=io.BytesIO(); Image.new('RGB',(16,16)).save(buf,format='PNG')
        m,result,_=self.import_result(buf.getvalue(),None)
        self.assertEqual(result['status'],'technical_failed')
        self.assertEqual(m['assets'][0]['attempts'][0]['error'],'not_gif_bytes')

    def test_single_frame_and_corrupt_gif_rejected(self):
        f=self.root/'bad.gif'; Image.new('RGB',(16,16)).save(f,format='GIF')
        with self.assertRaisesRegex(g.Failure,'multiframe'): g.inspect_gif(f)
        f.write_bytes(b'GIF89abroken')
        with self.assertRaises(OSError): g.inspect_gif(f)

    def test_duplicate_frames_gate(self):
        f=self.root/'dup.gif'; f.write_bytes(gif_bytes()); frame=Image.new('RGBA',(160,90),'red')
        class SameFrames:
            format='GIF'; n_frames=16; size=(160,90); info={'duration':150,'loop':0}
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def seek(self,i): pass
            def convert(self,mode): return frame
        with patch.object(g.Image,'open',return_value=SameFrames()):
            with self.assertRaisesRegex(g.Failure,'duplicate_frames_only'): g.inspect_gif(f)

    def test_parameter_mismatch(self):
        self.prepare(); m,result,_=self.import_result(gif_bytes(count=8,size=(90,160),delay=100))
        self.assertEqual(result['status'],'technical_failed')
        self.assertEqual(set(m['assets'][0]['attempts'][0]['technical']['parameter_mismatches']),{'frame_count','aspect_ratio','frame_duration_ms','size'})

    def test_budget_caps_and_failed_attempt_counts(self):
        r=g.reserve(self.budget,'gif','test'); g.finish_attempt(self.budget,r['id'],'failed','tool failure')
        for _ in range(7): g.reserve(self.budget,'gif','test')
        with self.assertRaisesRegex(g.Failure,'budget_exhausted'): g.reserve(self.budget,'gif','ninth')
        for _ in range(3): g.reserve(self.budget,'reference','test')
        with self.assertRaisesRegex(g.Failure,'budget_exhausted'): g.reserve(self.budget,'reference','fourth')

    def test_unknown_model_retained_and_never_ready(self):
        self.prepare(); m,result,_=self.import_result(model=None)
        self.assertEqual(result['status'],'pending_model_evidence')
        self.assertEqual(g.record_review(self.bundle,'burden-up',self.review_file(m))['status'],'not_ready')
        with self.assertRaisesRegex(g.Failure,'no_ready'): g.export_ready(self.bundle,self.root/'out')

    def test_retry_requires_explicit_flag(self):
        self.prepare(); m,_,_=self.import_result(model=None)
        with self.assertRaisesRegex(g.Failure,'explicit_retry'): g.native_request(self.bundle,'burden-up',self.budget)
        g.native_request(self.bundle,'burden-up',self.budget,retry=True)
        self.assertEqual(len(g.read_json(self.budget)['attempts']),2)

    def test_quality_requires_playback_and_all_dimensions(self):
        self.prepare(); m,_,_=self.import_result()
        r=self.review_file(m,full_playback_observed=False)
        self.assertEqual(g.record_review(self.bundle,'burden-up',r)['status'],'not_ready')
        for dimension in g.QUALITY_KEYS:
            r=self.review_file(m,checks={k:'unknown' if k==dimension else 'pass' for k in g.QUALITY_KEYS})
            self.assertEqual(g.record_review(self.bundle,'burden-up',r)['status'],'not_ready')

    def test_export_portable_including_tool_log(self):
        self.prepare(); m,_,_=self.import_result(); g.record_review(self.bundle,'burden-up',self.review_file(m))
        out=self.root/'ready'; g.export_ready(self.bundle,out)
        manifest=g.read_json(out/'manifest.json'); a=manifest['assets'][0]
        self.assertTrue(g.inside(out,a['path']).is_file()); self.assertTrue(g.inside(out,a['receipt']['tool_log']).is_file())
        self.assertEqual(g.inspect_gif(g.inside(out,a['path']))['duration_s'],2.4)
        self.assertEqual(a['intent'],self.request['shots'][0]['intent'])

    def test_removed_tool_log_blocks_export(self):
        self.prepare(); m,_,_=self.import_result(); g.record_review(self.bundle,'burden-up',self.review_file(m))
        g.inside(self.bundle,m['assets'][0]['attempts'][0]['receipt']['tool_log']).unlink()
        with self.assertRaises(OSError): g.export_ready(self.bundle,self.root/'ready')

    def test_tampered_spec_and_stale_review_rejected(self):
        self.prepare(); m,_,_=self.import_result()
        with self.assertRaisesRegex(g.Failure,'stale_review'): g.record_review(self.bundle,'burden-up',self.review_file(m,asset_sha256='bad'))
        m['assets'][0]['intent']='changed after generation'; g.write_json(self.bundle/'manifest.json',m)
        with self.assertRaisesRegex(g.Failure,'spec_changed'): g.record_review(self.bundle,'burden-up',self.review_file(m))

    def test_no_api_or_credential_entrypoint(self):
        p=subprocess.run([sys.executable,str(SCRIPT),'--help'],capture_output=True,text=True)
        self.assertNotIn('generate,',p.stdout); self.assertNotIn('env-file',p.stdout)
        self.assertFalse(hasattr(g,'official_request')); self.assertFalse(hasattr(g,'api_key'))


if __name__=='__main__': unittest.main(verbosity=2)
