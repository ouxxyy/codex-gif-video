"""Synthetic offline fixtures test rendering mechanics, never generated art quality."""
import io
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import subprocess
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'codex-gif-video/scripts'))
import compose_movie as movie
import native_gif as core


class ComposeMovieTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manifest_path = self.root / 'manifest.json'
        self.evidence = self.root / 'synthetic-review.txt'
        self.evidence.write_text('UNIT TEST ONLY: synthetic fixture review, not actual generated art.')
        self.manifest = {'schema_version': 1, 'kind': 'ready_gif_assets', 'references': [], 'assets': []}
        for i in range(5):
            frames = []
            for f in range(15):
                frame = Image.new('RGB', (144, 256), (245, 240, 220))
                ImageDraw.Draw(frame).rectangle((f * 7, 20 + i * 20, f * 7 + 20, 50 + i * 20), fill=(130, 40 + i * 20, 80))
                frames.append(frame)
            data = io.BytesIO()
            frames[0].save(data, format='GIF', save_all=True, append_images=frames[1:], duration=200, loop=0, optimize=False)
            path = self.root / f'shot-{i}.gif'; path.write_bytes(data.getvalue())
            asset = {'id': f'shot-{i}', 'aspect_ratio': '9:16', 'prompt': 'SYNTHETIC TEST; no generation.',
                     'parameters': {'model': core.MODELS[0], 'output_format': 'gif', 'n': 1,
                                    'size': '144x256', 'frame_count': 15, 'frame_duration_ms': 200},
                     'path': path.name, 'sha256': core.digest(data.getvalue()), 'source_kind': 'official_api_native_gif',
                     'status': 'ready'}
            payload = {**asset['parameters'], 'prompt': asset['prompt']}
            digest = core.digest(core.encode(payload))
            receipt = {'endpoint': 'https://api.openai.com/v1/images/edits', 'http_status': 200,
                       'request_id': 'test-only', 'redirects_allowed': False, 'authentication_type': 'api_key',
                       'requested_model': core.MODELS[0], 'request_payload_sha256': digest}
            asset.update(receipt=receipt, request_payload_sha256=digest,
                         model_evidence={'requested_model': core.MODELS[0], 'reported_model': None, 'status': 'unverified'},
                         official_request_evidence=core.official_request_evidence(payload, receipt))
            asset['technical'] = core.inspect_gif(path, asset)
            asset['review'] = {'asset_sha256': asset['sha256'], 'full_playback_observed': True,
                               'all_frames_observed': True, 'checks': {k: 'pass' for k in core.QUALITY_KEYS},
                               'evidence_files': [{'path': self.evidence.name, 'sha256': core.digest(self.evidence.read_bytes())}]}
            self.manifest['assets'].append(asset)
        self.save()

    def save(self):
        self.manifest_path.write_text(json.dumps(self.manifest))

    def validate(self, **extra):
        return movie.validate_manifest(self.manifest_path, 144, 256, 15, **extra)

    def test_ready_source_cycle_and_exact_duration(self):
        plan = self.validate()
        self.assertEqual(plan['duration_s'], 15)
        self.assertEqual(plan['fps'], 25)
        self.assertEqual(len(plan['sources']), 5)
        self.assertTrue(all(s['source_quality_ready'] for s in plan['sources']))

    def test_ratio_duration_and_hash_are_rejected(self):
        with self.assertRaisesRegex(core.Failure, 'aspect_ratio_mismatch'):
            movie.validate_manifest(self.manifest_path, 256, 256, 15)
        with self.assertRaisesRegex(core.Failure, 'total_duration_mismatch'):
            movie.validate_manifest(self.manifest_path, 144, 256, 14.88)
        (self.root / self.manifest['assets'][0]['path']).write_bytes(b'changed')
        with self.assertRaisesRegex(core.Failure, 'hash_mismatch'):
            self.validate()

    def test_source_provenance_must_remain_verifiable(self):
        self.manifest['assets'][0]['receipt']['request_id'] = ''
        self.save()
        with self.assertRaisesRegex(core.Failure, 'provenance_unverified'):
            self.validate()

    def test_preview_requires_explicit_flag_and_cannot_hide_failure(self):
        for a in self.manifest['assets']:
            a['status'] = 'pending_review'; a.pop('review')
        self.save()
        with self.assertRaisesRegex(core.Failure, 'not_ready'):
            self.validate()
        plan = self.validate(review_copy=True)
        self.assertFalse(any(s['source_quality_ready'] for s in plan['sources']))
        self.manifest['assets'][0]['review'] = {'checks': {'motion': 'fail'}}
        self.save()
        with self.assertRaisesRegex(core.Failure, 'review_has_failure'):
            self.validate(review_copy=True)

    def test_ready_review_evidence_hash_is_checked(self):
        self.evidence.write_text('changed')
        with self.assertRaisesRegex(core.Failure, 'hash_mismatch'):
            self.validate()

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg/ffprobe required')
    def test_real_ffmpeg_five_cycles_15s_without_source_changes(self):
        for a in self.manifest['assets']:
            a['status'] = 'pending_review'; a.pop('review')
        self.save()
        out = self.root / 'review.mp4'
        result = movie.compose(self.manifest_path, out, width=144, height=256, duration=15, review_copy=True)
        self.assertEqual(result['status'], 'rendered_pending_review')
        self.assertEqual(result['source_quality_status'], 'pending_perceptual_review')
        self.assertFalse(result['review']['full_playback_observed'])
        video = next(s for s in result['output']['probe']['streams'] if s['codec_type'] == 'video')
        self.assertEqual((video['width'], video['height']), (144, 256))
        self.assertEqual(float(video['duration']), 15.0)
        self.assertEqual(video['codec_name'], 'h264')
        self.assertEqual([s['codec_type'] for s in result['output']['probe']['streams']], ['video'])
        self.assertEqual(result['additional_inputs'], {})
        self.assertFalse(any('subtitles=' in str(c['argv']) for c in result['commands']))
        self.assertEqual(int(video['nb_frames']), 375)
        for a in self.manifest['assets']:
            self.assertEqual(core.digest((self.root / a['path']).read_bytes()), a['sha256'])
        self.assertTrue(Path(str(out) + '.render.json').exists())
        with self.assertRaisesRegex(core.Failure, 'destination_exists'):
            movie.compose(self.manifest_path, out, width=144, height=256, duration=15, review_copy=True)


    def test_audio_and_subtitle_inputs_are_not_supported(self):
        for name in ('audio', 'subtitles'):
            with self.subTest(name=name):
                with self.assertRaises(TypeError):
                    movie.compose(self.manifest_path, self.root / 'forbidden.mp4',
                                  **{name: 'extra-file'})
                result = subprocess.run([sys.executable, str(Path(movie.__file__)),
                                         '--manifest', str(self.manifest_path),
                                         '--out', str(self.root / 'forbidden.mp4'),
                                         '--' + name, 'extra-file'], capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertIn('unrecognized arguments', result.stderr)
                self.assertFalse((self.root / 'forbidden.mp4').exists())


    def test_long_gif_keeps_all_cycles_timing_and_order(self):
        out = self.root / 'long.gif'
        result = movie.compose(self.manifest_path, out, width=144, height=256, duration=15)
        self.assertEqual(result['format'], 'gif')
        self.assertEqual(result['status'], 'rendered_pending_review')
        self.assertEqual(result['output']['probe']['duration_s'], 15)
        self.assertEqual(result['output']['probe']['frame_count'], 75)
        with Image.open(out) as image:
            self.assertNotIn('loop', image.info)
            for index, source in enumerate(self.manifest['assets']):
                with Image.open(self.root / source['path']) as original:
                    for frame_index in range(original.n_frames):
                        original.seek(frame_index)
                        image.seek(index * 15 + frame_index)
                        self.assertEqual(image.info['duration'], original.info['duration'])
                        self.assertEqual(image.convert('RGB').tobytes(), original.convert('RGB').tobytes())
                self.assertEqual(core.digest((self.root / source['path']).read_bytes()), source['sha256'])
        with self.assertRaisesRegex(core.Failure, 'destination_exists'):
            movie.compose(self.manifest_path, out, width=144, height=256, duration=15)

    def test_long_gif_accepts_timeline_and_enforces_quality_gate(self):
        timeline = self.make_replacement_timeline()
        result = movie.compose(None, self.root / 'selected.gif', width=144, height=256,
                               duration=15, timeline=timeline)
        self.assertEqual([s['id'] for s in result['plan']['sources']], [f'shot-{i}' for i in range(5)])
        self.assertEqual(result['output']['probe']['duration_s'], 15)
        self.manifest['assets'][0]['review']['checks']['clean_visual'] = 'unknown'
        self.save()
        with self.assertRaisesRegex(core.Failure, 'source_not_ready'):
            movie.compose(self.manifest_path, self.root / 'unreviewed.gif', width=144, height=256, duration=15)

    def test_long_gif_rejects_unreasonable_memory_size(self):
        with self.assertRaisesRegex(core.Failure, 'gif_export_too_large'):
            movie.compose(self.manifest_path, self.root / 'huge.gif', width=2880, height=5120, duration=15)
        self.assertFalse((self.root / 'huge.gif').exists())

    def make_replacement_timeline(self):
        old, new = self.root / 'old', self.root / 'new'
        old.mkdir(); new.mkdir()
        old_assets, new_assets = [], []
        for directory in (old, new):
            shutil.copyfile(self.evidence, directory / self.evidence.name)
        for original in self.manifest['assets']:
            attempt = copy.deepcopy(original)
            attempt['id'] = 'selected-attempt'
            asset = {k: copy.deepcopy(original[k]) for k in ('id', 'aspect_ratio', 'parameters', 'prompt', 'status')}
            asset.update(attempts=[attempt], selected_attempt='selected-attempt')
            asset['spec_sha256'] = core.spec_hash(asset)
            old_assets.append(asset)
            shutil.copyfile(self.root / original['path'], old / original['path'])
            if original['id'] == 'shot-4':
                new_assets.append(copy.deepcopy(asset))
                shutil.copyfile(self.root / original['path'], new / original['path'])
        old_assets[-1]['status'] = 'not_ready'
        old_assets[-1]['attempts'][0]['review']['checks']['semantics'] = 'fail'
        # Stronger than a semantic failure: a non-selected bad file must not even
        # be decoded or hashed as a prerequisite for choosing its replacement.
        (old / old_assets[-1]['attempts'][0]['path']).write_bytes(b'bad unselected fifth shot')
        for directory, assets in ((old, old_assets), (new, new_assets)):
            (directory / 'manifest.json').write_text(json.dumps({'schema_version': 1, 'references': [], 'assets': assets}))
        timeline = {'kind': 'native_gif_movie_timeline', 'sources':
                    [{'manifest': 'old/manifest.json', 'shot_id': f'shot-{i}'} for i in range(4)]
                    + [{'manifest': 'new/manifest.json', 'shot_id': 'shot-4'}]}
        timeline_path = self.root / 'timeline.json'
        timeline_path.write_text(json.dumps(timeline))
        return timeline_path

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg/ffprobe required')
    def test_timeline_renders_old_first_four_and_replacement_fifth(self):
        timeline = self.make_replacement_timeline()
        with self.assertRaisesRegex(core.Failure, 'hash_mismatch'):
            movie.validate_manifest(self.root / 'old/manifest.json', 144, 256, 15)
        result = movie.compose(None, self.root / 'replacement.mp4', width=144, height=256,
                               duration=15, timeline=timeline)
        self.assertEqual(float(result['output']['probe']['format']['duration']), 15)
        self.assertEqual([s['id'] for s in result['plan']['sources']], [f'shot-{i}' for i in range(5)])
        self.assertEqual(Path(result['plan']['sources'][-1]['path']).parent, (self.root / 'new').resolve())
        self.assertEqual(len(result['plan']['bound_inputs']), 3)
        for bound in result['plan']['bound_inputs']:
            self.assertEqual(core.digest(Path(bound['path']).read_bytes()), bound['sha256'])
        self.assertEqual((self.root / 'old/shot-4.gif').read_bytes(), b'bad unselected fifth shot')
        self.assertEqual(result['status'], 'rendered_pending_review')

    def test_timeline_selected_spec_and_exclusive_input_checks(self):
        timeline = self.make_replacement_timeline()
        with self.assertRaisesRegex(core.Failure, 'exclusively'):
            movie.compose(self.manifest_path, self.root / 'both.mp4', timeline=timeline)
        path = self.root / 'new/manifest.json'
        edited = json.loads(path.read_text()); edited['assets'][0]['prompt'] += ' changed'
        path.write_text(json.dumps(edited))
        with self.assertRaisesRegex(core.Failure, 'asset_spec_changed'):
            movie.validate_timeline(timeline, 144, 256, 15)


if __name__ == '__main__':
    unittest.main(verbosity=2)
