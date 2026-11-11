"""API compatibility tests use fake credentials and synthetic media only."""
import base64
import io
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'codex-gif-video/scripts'))
import native_gif as g
import official_api as api
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def fixture_gif(size=(256,144)):
    images = [Image.new('RGB', size, (i * 12, 60, 90)) for i in range(16)]
    out = io.BytesIO()
    images[0].save(out, format='GIF', save_all=True, append_images=images[1:], duration=150, loop=0)
    return out.getvalue()


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.bundle = self.root / 'bundle'; self.budget = self.root / 'budget.json'
        self.env = self.root / '.env.local'
        self.env.write_text('OPENAI_API_KEY=test-credential-not-real\n'); self.env.chmod(0o600)
        self.request = self.root / 'request.json'
        request=g.read_json(ROOT / 'examples/shot.json')
        request['shots'][0]['size']='256x144'
        g.write_json(self.request, request)
        g.prepare(self.request, self.bundle)

    def response(self, raw=None, model=g.MODELS[0]):
        result = {'data': [{'b64_json': base64.b64encode(raw or fixture_gif()).decode()}]}
        if model is not None: result['model'] = model
        return result, {'endpoint': api.API + '/images/generations', 'request_id': 'test-only', 'http_status': 200,
                        'authentication_type':'api_key','redirects_allowed':False}

    def run_generate(self, response=None, retry=False):
        with patch.object(api, 'request_image', return_value=response or self.response()) as call:
            m = api.generate(self.bundle, 'burden-up', self.budget, self.env, retry=retry)
            return m, call.call_count

    def test_key_loader_private_file_and_no_evaluation(self):
        self.assertEqual(api.load_key(self.env), 'test-credential-not-real')
        self.env.chmod(0o644)
        with self.assertRaisesRegex(g.Failure, 'credential_file_permissions'): api.load_key(self.env)

    def test_missing_key_never_spends_budget(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            with self.assertRaises(g.Failure): api.generate(self.bundle, 'burden-up', self.budget, self.root/'missing')
        self.assertFalse(self.budget.exists())

    def test_reference_generation_has_separate_budget_and_preserves_png(self):
        buf=io.BytesIO();Image.new('RGB',(64,64),'blue').save(buf,format='PNG')
        prompt=self.root/'reference.txt';prompt.write_text('One consistent character reference.')
        out=self.root/'reference.png'
        body={'model':g.MODELS[0],'data':[{'b64_json':base64.b64encode(buf.getvalue()).decode()}]}
        receipt={'endpoint':api.API+'/images/generations','http_status':200,'request_id':'test-reference',
                 'authentication_type':'api_key','redirects_allowed':False}
        with patch.object(api,'request_image',return_value=(body,receipt)) as call:
            r=api.reference(prompt,out,self.budget,self.env)
        self.assertEqual(out.read_bytes(),buf.getvalue())
        self.assertEqual(call.call_args.args[0]['output_format'],'png')
        self.assertEqual(g.read_json(self.budget)['attempts'][0]['kind'],'reference')
        self.assertEqual(r['status'],'reference_generated_pending_visual_review')

    def test_reference_source_status_distinguishes_missing_and_contradictory_model(self):
        buf=io.BytesIO();Image.new('RGB',(64,64),'blue').save(buf,format='PNG')
        prompt=self.root/'reference.txt';prompt.write_text('One consistent character reference.')
        cases=[(None,'test-id','reference_generated_pending_visual_review'),
               (g.MODELS[1],'test-id','reference_model_mismatch'),
               (None,None,'reference_pending_source_evidence'),
               (g.MODELS[0],None,'reference_pending_source_evidence')]
        for i,(reported,request_id,want) in enumerate(cases):
            with self.subTest(reported=reported,request_id=request_id):
                body={'data':[{'b64_json':base64.b64encode(buf.getvalue()).decode()}]}
                if reported is not None:body['model']=reported
                receipt={'endpoint':api.API+'/images/generations','http_status':200,'request_id':request_id,
                         'authentication_type':'api_key','redirects_allowed':False}
                out=self.root/f'reference-{i}.png'
                with patch.object(api,'request_image',return_value=(body,receipt)):
                    r=api.reference(prompt,out,self.root/f'reference-budget-{i}.json',self.env)
                self.assertEqual(r['status'],want)
                self.assertEqual(r['model_evidence']['reported_model'],reported)
                self.assertEqual(out.read_bytes(),buf.getvalue())

    def test_generate_preserves_native_bytes_and_source(self):
        m, count = self.run_generate()
        a = m['assets'][0]; at = a['attempts'][0]
        self.assertEqual(count, 1); self.assertEqual(at['source_kind'], 'official_api_native_gif')
        self.assertEqual(g.inside(self.bundle, at['path']).read_bytes(), fixture_gif())
        self.assertEqual(a['status'], 'pending_review')
        _, count = self.run_generate(); self.assertEqual(count, 0)

    def test_unreported_model_retained_but_official_request_is_supported(self):
        m, _ = self.run_generate(self.response(model=None))
        self.assertEqual(m['assets'][0]['status'], 'pending_review')
        at = m['assets'][0]['attempts'][0]
        self.assertIsNone(at['model_evidence']['reported_model'])
        self.assertEqual(at['model_evidence']['status'],'unverified')
        self.assertEqual(at['official_request_evidence']['status'],'verified')
        self.assertEqual(at['receipt']['requested_model'], g.MODELS[0])

    def test_portrait_dimension_is_sent_as_concrete_api_size(self):
        request=g.read_json(self.request)
        request['shots'][0].update(aspect_ratio='9:16',size='auto')
        bundle=self.root/'portrait'
        g.write_json(self.request,request);g.prepare(self.request,bundle)
        with patch.object(api,'request_image',return_value=self.response(fixture_gif((288,512)),model=None)) as call:
            m=api.generate(bundle,'burden-up',self.budget,self.env)
        self.assertEqual(call.call_args.args[0]['size'],'288x512')
        self.assertEqual(m['assets'][0]['status'],'pending_review')

    def test_official_request_without_id_or_wrong_endpoint_does_not_pass(self):
        for changes in ({'request_id':None},{'endpoint':'https://proxy.example/v1/images/generations'},
                        {'redirects_allowed':True}):
            with self.subTest(changes=changes):
                response,receipt=self.response(model=None);receipt.update(changes)
                m,_=self.run_generate((response,receipt),retry=True)
                self.assertEqual(m['assets'][0]['status'],'pending_model_evidence')
                # Next subtest must make a new response rather than reuse pending state.
                asset=m['assets'][0];asset['status']='failed';g.write_json(self.bundle/'manifest.json',m)

    def test_contradictory_model_report_cannot_use_request_provenance(self):
        m,_=self.run_generate(self.response(model='gpt-image-2.6-flare'))
        self.assertEqual(m['assets'][0]['status'],'pending_model_evidence')

    def test_official_provenance_survives_review_and_export_without_claiming_reported_model(self):
        m,_=self.run_generate(self.response(model=None));asset=m['assets'][0];at=asset['attempts'][0]
        evidence=self.root/'review-evidence.txt';evidence.write_text('SYNTHETIC TEST ONLY; no real visual review.')
        review=self.root/'review.json'
        g.write_json(review,{'asset_sha256':at['sha256'],'reviewer':'unit-test-fixture','full_playback_observed':True,
                            'all_frames_observed':True,'checks':{k:'pass' for k in g.QUALITY_KEYS},'evidence_files':[evidence.name]})
        self.assertEqual(g.record_review(self.bundle,'burden-up',review)['status'],'ready')
        out=self.root/'ready';g.export_ready(self.bundle,out)
        exported=g.read_json(out/'manifest.json')['assets'][0]
        self.assertIsNone(exported['model_evidence']['reported_model'])
        self.assertEqual(exported['official_request_evidence']['status'],'verified')
        self.assertTrue(g.source_evidence_passes(exported,exported))
        self.assertEqual(g.inspect_gif(g.inside(out,exported['path']),exported)['status'],'pass')
        # Tampering with provenance after review cannot be exported as ready.
        m=g.read_json(self.bundle/'manifest.json');m['assets'][0]['attempts'][0]['receipt']['request_id']='changed'
        g.write_json(self.bundle/'manifest.json',m)
        with self.assertRaisesRegex(g.Failure,'quality_gate_failed'):g.export_ready(self.bundle,self.root/'tampered')

    def test_historical_unknown_record_is_not_silently_upgraded(self):
        m,_=self.run_generate(self.response(model=None));at=m['assets'][0]['attempts'][0]
        del at['official_request_evidence']
        self.assertFalse(g.source_evidence_passes(at,m['assets'][0]))

    def test_png_is_not_renamed_to_gif(self):
        buf = io.BytesIO(); Image.new('RGB', (16,16)).save(buf, format='PNG')
        m, _ = self.run_generate(self.response(buf.getvalue()))
        self.assertEqual(m['assets'][0]['status'], 'technical_failed')

    def test_failure_counts_once_and_requires_retry(self):
        with patch.object(api, 'request_image', side_effect=api.ApiFailure({'status':401,'code':'invalid_api_key','message':'redacted'})) as call:
            m = api.generate(self.bundle, 'burden-up', self.budget, self.env)
            self.assertEqual(call.call_count,1)
        self.assertEqual(m['assets'][0]['status'],'failed')
        self.assertEqual(len(g.read_json(self.budget)['attempts']),1)
        with self.assertRaisesRegex(g.Failure, 'explicit_retry'): self.run_generate()
        m, count = self.run_generate(retry=True)
        self.assertEqual(count,1); self.assertEqual(len(m['assets'][0]['attempts']),2)

    def test_error_redacts_full_and_masked_credentials(self):
        key='sk-test-private-value'
        text=api.redact('Bad key '+key+' also sk-proj-abc***xyz', key)
        self.assertNotIn(key,text); self.assertNotIn('sk-proj',text)

    def test_transport_is_pinned_and_blocks_redirect(self):
        class Result(io.BytesIO):
            headers={'x-request-id':'test-only'}
            status=200
        with patch.object(api.urllib.request, 'build_opener') as opener:
            opener.return_value.open.return_value=Result(b'{"data":[]}')
            api.request_image({'model':g.MODELS[0], 'output_format':'gif'}, [('image/png',b'test')], 'fake')
            req=opener.return_value.open.call_args.args[0]
            self.assertEqual(req.full_url,'https://api.openai.com/v1/images/edits')
            payload=json.loads(req.data)
            self.assertEqual(payload['images'][0]['image_url'],'data:image/png;base64,dGVzdA==')
        self.assertIsNone(api.NoRedirect().redirect_request(None,None,302,'redirect',{},'https://example.com'))

    def test_http_error_does_not_log_credentials(self):
        key='sk-test-private-value'
        error=urllib.error.HTTPError(api.API+'/images/generations',401,'bad',{},io.BytesIO(json.dumps({'error':{'message':'Invalid '+key,'code':'invalid_api_key'}}).encode()))
        with patch.object(api.urllib.request,'build_opener') as opener:
            opener.return_value.open.side_effect=error
            with self.assertRaises(api.ApiFailure) as caught: api.request_image({'model':g.MODELS[0],'output_format':'gif'},[],key)
        self.assertNotIn(key,json.dumps(caught.exception.details))
        self.assertEqual(caught.exception.details['status'],401)

    def test_interrupted_response_is_unknown_not_traceback(self):
        class BrokenResponse:
            headers={}
            status=200
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,*args): raise http.client.IncompleteRead(b'partial-body',10)
        with patch.object(api.urllib.request,'build_opener') as opener:
            opener.return_value.open.return_value=BrokenResponse()
            with self.assertRaises(api.ApiFailure) as caught:
                api.request_image({'model':g.MODELS[0],'output_format':'gif'},[],'fake-key')
        self.assertEqual(caught.exception.details['code'],'network_error_outcome_unknown')
        self.assertNotIn('partial-body',str(caught.exception.details))


if __name__ == '__main__': unittest.main(verbosity=2)
