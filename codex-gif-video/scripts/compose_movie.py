#!/usr/bin/env python3
"""Compose verified native GIF cycles into one long GIF or a silent, subtitle-free MP4.

Rendering is not perceptual acceptance. --review-copy is an explicit preview gate,
never a promotion of unknown motion checks to ready.
"""
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from PIL import Image

import native_gif as core


def probe(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format',
                             '-of', 'json', str(path)], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def checked_file(root, item):
    path = core.inside(root, item['path'])
    core.require(path.is_file(), 'artifact_missing')
    core.require(core.digest(path.read_bytes()) == item['sha256'], 'artifact_hash_mismatch')
    return path


def review_passes(root, attempt):
    review = attempt.get('review', {})
    if not (review.get('asset_sha256') == attempt['sha256']
            and review.get('full_playback_observed') is True
            and review.get('all_frames_observed') is True
            and all(review.get('checks', {}).get(k) == 'pass' for k in core.QUALITY_KEYS)
            and review.get('evidence_files')):
        return False
    for item in review['evidence_files']:
        checked_file(root, item)
    return True


def _validate_manifest_sources(manifest_path, width, height, review_copy=False, shot_id=None):
    manifest_path = Path(manifest_path).resolve()
    root = manifest_path.parent
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    core.require(type(width) is int and type(height) is int and width > 0 and height > 0
                 and width % 2 == height % 2 == 0, 'output_size_must_be_positive_even')
    assets = manifest.get('assets')
    core.require(isinstance(assets, list) and assets, 'no_assets')
    if shot_id is not None:
        assets = [a for a in assets if a.get('id') == shot_id]
        core.require(len(assets) == 1, 'timeline_shot_missing_or_ambiguous:' + shot_id)
    exported = manifest.get('kind') == 'ready_gif_assets'
    if not exported:
        # Only the explicitly selected assets are consumed. Unselected failed
        # attempts remain in their immutable bundle and are not read or upgraded.
        core.check_bundle(root, {**manifest, 'assets': assets})
    for ref in manifest.get('references', []):
        checked_file(root, ref)
    sources = []
    for asset in assets:
        if exported:
            attempt = asset
        else:
            attempt = next((x for x in asset.get('attempts', [])
                            if x.get('id') == asset.get('selected_attempt')), None)
            core.require(attempt is not None, 'shot_not_generated:' + asset['id'])
        path = checked_file(root, attempt)
        technical = core.inspect_gif(path, asset)
        core.require(technical['status'] == 'pass'
                     and attempt.get('technical', {}).get('status') == 'pass', 'source_technical_failed')
        core.require(technical['width'] * height == technical['height'] * width,
                     'source_output_aspect_ratio_mismatch')
        core.require(core.source_evidence_passes(attempt, asset), 'source_provenance_unverified')
        native_log = attempt.get('receipt', {})
        if native_log.get('tool_log'):
            checked_file(root, {'path': native_log['tool_log'], 'sha256': native_log['tool_log_sha256']})
        checks = attempt.get('review', {}).get('checks', {})
        core.require('fail' not in checks.values(), 'source_review_has_failure')
        ready = asset.get('status') == 'ready' and review_passes(root, attempt)
        if not ready:
            core.require(review_copy, 'source_not_ready_use_explicit_review_copy')
            core.require(attempt.get('source_kind') == 'official_api_native_gif',
                         'review_copy_requires_official_source')
            core.require(asset.get('status') in ('pending_review', 'pending_model_evidence', 'not_ready'),
                         'source_status_not_reviewable')
        sources.append({'id': asset['id'], 'path': str(path), 'sha256': attempt['sha256'],
                        'technical': technical, 'source_status': asset.get('status'),
                        'source_quality_ready': ready, 'source_kind': attempt.get('source_kind'),
                        'manifest': str(manifest_path)})
    return {'manifest': str(manifest_path), 'manifest_sha256': core.digest(manifest_bytes),
            'sources': sources}


def _timing_plan(sources, duration):
    core.require(math.isfinite(duration) and duration > 0, 'invalid_movie_duration')
    total_ms = sum(sum(s['technical']['frame_durations_ms']) for s in sources)
    core.require(abs(total_ms - duration * 1000) < 0.001, 'source_total_duration_mismatch')
    # Every source frame boundary must land on an output sample. No interpolation
    # or speed change: the GIF's held frames remain held for the same duration.
    durations = [d for s in sources for d in s['technical']['frame_durations_ms']]
    fps = next((f for f in (25, 50, 100) if all((d * f) % 1000 == 0 for d in durations)), None)
    core.require(fps is not None, 'source_timing_not_exactly_representable')
    return {'duration_s': total_ms / 1000, 'fps': fps}


def validate_manifest(manifest_path, width, height, duration, review_copy=False):
    plan = _validate_manifest_sources(manifest_path, width, height, review_copy)
    plan.update(_timing_plan(plan['sources'], duration))
    plan['bound_inputs'] = [{'path': plan['manifest'], 'sha256': plan['manifest_sha256']}]
    return plan


def validate_timeline(timeline_path, width, height, duration, review_copy=False):
    timeline_path = Path(timeline_path).resolve()
    timeline_bytes = timeline_path.read_bytes()
    timeline = json.loads(timeline_bytes)
    core.require(timeline.get('kind') == 'native_gif_movie_timeline', 'invalid_timeline_kind')
    items = timeline.get('sources')
    core.require(isinstance(items, list) and 0 < len(items) <= 100, 'timeline_sources_required')
    sources, bindings, seen = [], {}, set()
    for item in items:
        core.require(isinstance(item, dict), 'invalid_timeline_source')
        relative, shot_id = item.get('manifest'), item.get('shot_id')
        core.require(isinstance(relative, str) and relative and not Path(relative).is_absolute(),
                     'timeline_manifest_must_be_relative')
        core.safe_id(shot_id)
        path = (timeline_path.parent / relative).resolve()
        identity = (str(path), shot_id)
        core.require(identity not in seen, 'duplicate_timeline_source')
        seen.add(identity)
        item_plan = _validate_manifest_sources(path, width, height, review_copy, shot_id)
        sources.extend(item_plan['sources'])
        previous = bindings.get(str(path))
        core.require(previous is None or previous == item_plan['manifest_sha256'], 'manifest_changed_during_plan')
        bindings[str(path)] = item_plan['manifest_sha256']
    timeline_hash = core.digest(timeline_bytes)
    plan = {'timeline': str(timeline_path), 'timeline_sha256': timeline_hash, 'sources': sources,
            'bound_inputs': [{'path': str(timeline_path), 'sha256': timeline_hash}]
                + [{'path': path, 'sha256': sha} for path, sha in bindings.items()]}
    plan.update(_timing_plan(sources, duration))
    return plan


def render_long_gif(plan, draft, width, height):
    """Join decoded original cycles; never invent motion or loop to fill time.

    This is a derived export, not the original native GIF returned by a model.
    Pillow may merge adjacent identical frames; the full delay is preserved.
    """
    frame_total = sum(s['technical']['frame_count'] for s in plan['sources'])
    core.require(frame_total * width * height <= 100_000_000,
                 'gif_export_too_large_reduce_dimensions_or_choose_mp4')
    frames, delays = [], []
    for source in plan['sources']:
        with Image.open(source['path']) as image:
            for index, delay in enumerate(source['technical']['frame_durations_ms']):
                image.seek(index)
                frame = image.convert('RGBA')
                if frame.size != (width, height):
                    frame = frame.resize((width, height), Image.Resampling.LANCZOS)
                frame.info.clear()  # No inherited loop count, comment or metadata.
                frames.append(frame)
                delays.append(delay)
    frames[0].save(draft, format='GIF', save_all=True, append_images=frames[1:],
                   duration=delays, disposal=2, optimize=False)
    actual_delays = []
    with Image.open(draft) as result:
        core.require(result.format == 'GIF' and result.size == (width, height), 'render_format_mismatch')
        core.require('loop' not in result.info, 'export_must_not_add_loop')
        for index in range(result.n_frames):
            result.seek(index)
            result.load()
            actual_delays.append(result.info.get('duration', 0))
    core.require(sum(actual_delays) == sum(delays), 'render_duration_mismatch')
    return {'format': 'gif', 'width': width, 'height': height,
            'frame_count': len(actual_delays), 'frame_durations_ms': actual_delays,
            'duration_s': sum(actual_delays) / 1000, 'loop': 'once', 'audio': False}


def compose(manifest, out, width=1080, height=1920, duration=15.0,
            review_copy=False, timeline=None):
    out = Path(out).resolve()
    output_format = out.suffix.lower().lstrip('.')
    core.require(output_format in ('gif', 'mp4'), 'output_must_be_gif_or_mp4')
    if output_format == 'mp4':
        for name in ('ffmpeg', 'ffprobe'):
            core.require(shutil.which(name), name + '_not_found')
    core.require(bool(manifest) != bool(timeline), 'supply_manifest_or_timeline_exclusively')
    plan = (validate_timeline(timeline, width, height, duration, review_copy) if timeline
            else validate_manifest(manifest, width, height, duration, review_copy))
    out = Path(out).resolve()
    receipt_path = Path(str(out) + '.render.json')
    core.require(not out.exists() and not receipt_path.exists(), 'render_destination_exists')
    out.parent.mkdir(parents=True, exist_ok=True)
    work = out.parent / ('.' + out.stem + '.render-work-' + uuid.uuid4().hex[:12])
    work.mkdir()
    commands = []
    receipt = {'schema_version': 1, 'status': 'rendering', 'created_at': core.now(),
               'review_copy': review_copy, 'plan': plan, 'additional_inputs': {},
               'content_policy': 'silent_visual_assets_only; no_subtitles; no_music; no_voiceover',
               'width': width, 'height': height, 'format': output_format, 'work_directory': str(work),
               'source_policy': 'one_original_cycle_each; no_crop; no_time_stretch; no_interpolation',
               'sampling_policy': ('original_frame_delays' if output_format == 'gif' else
                                   'same_speed_CFR_sampling_at_exact_GIF_frame_boundaries'),
               'commands': commands,
               'review': {'full_playback_observed': False, 'all_frames_observed': False,
                          'audio': 'not_applicable_no_audio_stream', 'status': 'unknown'}}

    def run(args):
        commands.append({'argv': args, 'cwd': str(work)})
        result = subprocess.run(args, cwd=work, capture_output=True, text=True)
        log = work / ('command-%02d.log' % len(commands))
        log.write_text(result.stdout + result.stderr, encoding='utf-8')
        commands[-1].update(exit_code=result.returncode, log=str(log))
        core.require(result.returncode == 0, 'ffmpeg_failed_see:' + str(log))

    try:
        if output_format == 'gif':
            draft = work / 'render.gif'
            actual = render_long_gif(plan, draft, width, height)
        else:
            parts = []
            for i, src in enumerate(plan['sources']):
                part = work / ('part-%03d.mp4' % i)
                run(['ffmpeg', '-nostdin', '-v', 'warning', '-n', '-ignore_loop', '1', '-i', src['path'],
                     '-an', '-vf', f'scale={width}:{height}:flags=lanczos,setsar=1,fps={plan["fps"]}',
                     '-t', f'{src["technical"]["duration_s"]:.6f}', '-c:v', 'libx264', '-preset', 'veryfast',
                     '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(part)])
                parts.append(part)
            concat = work / 'concat.txt'
            concat.write_text(''.join("file '" + p.name + "'\n" for p in parts), encoding='utf-8')
            draft = work / 'render.mp4'
            cmd = ['ffmpeg', '-nostdin', '-v', 'warning', '-n', '-f', 'concat', '-safe', '1', '-i', concat.name]
            cmd += ['-map', '0:v:0', '-c:v', 'copy', '-an', '-sn', '-dn']
            cmd += ['-t', f'{duration:.6f}', '-movflags', '+faststart', str(draft)]
            run(cmd)
            actual = probe(draft)
            video = next(s for s in actual['streams'] if s.get('codec_type') == 'video')
            core.require(video['width'] == width and video['height'] == height
                         and video['codec_name'] == 'h264' and video['pix_fmt'] == 'yuv420p', 'render_format_mismatch')
            core.require(abs(float(video['duration']) - duration) < .001
                         and abs(float(actual['format']['duration']) - duration) < .001, 'render_duration_mismatch')
            core.require(len(actual['streams']) == 1 and actual['streams'][0].get('codec_type') == 'video',
                         'render_must_contain_only_video')
        # Recheck inputs to detect mutation while rendering; never overwrite.
        for bound in plan['bound_inputs']:
            core.require(core.digest(Path(bound['path']).read_bytes()) == bound['sha256'], 'bound_input_changed_during_render')
        for src in plan['sources']:
            core.require(core.digest(Path(src['path']).read_bytes()) == src['sha256'], 'source_changed_during_render')
        os.link(draft, out)
        receipt.update(status='rendered_pending_review', completed_at=core.now(),
                       output={'path': str(out), 'sha256': core.digest(out.read_bytes()), 'probe': actual},
                       source_quality_status='ready' if all(s['source_quality_ready'] for s in plan['sources'])
                       else 'pending_perceptual_review')
        core.write_json(receipt_path, receipt)
        return receipt
    except Exception as exc:
        receipt.update(status='render_failed', error=str(exc), completed_at=core.now())
        core.write_json(work / 'failed-render.json', receipt)
        raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    entry = p.add_mutually_exclusive_group(required=True)
    entry.add_argument('--manifest'); entry.add_argument('--timeline')
    p.add_argument('--out', required=True)
    p.add_argument('--width', type=int, default=1080); p.add_argument('--height', type=int, default=1920)
    p.add_argument('--duration', type=float, default=15.0)
    p.add_argument('--review-copy', action='store_true')
    a = p.parse_args()
    try:
        result = compose(a.manifest, a.out, a.width, a.height, a.duration,
                         review_copy=a.review_copy, timeline=a.timeline)
        print(json.dumps({'status': result['status'], 'output': result['output']['path'],
                          'receipt': str(Path(a.out).resolve()) + '.render.json',
                          'duration_s': result['plan']['duration_s'], 'format': result['format']}, indent=2))
        return 0
    except (core.Failure, OSError, ValueError, KeyError, StopIteration, subprocess.CalledProcessError) as e:
        print(json.dumps({'status': 'blocked', 'error': str(e)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
