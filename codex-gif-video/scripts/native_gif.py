#!/usr/bin/env python3
"""Codex-session native GIF asset handoff. No network/API client or animation synthesis.

Python 3.10+, Pillow. The current Codex agent invokes the native image tool.
"""
import argparse
import contextlib
import copy
import datetime as dt
import fcntl
import hashlib
import io
import json
import math
import os
import plistlib
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

from PIL import Image, ImageChops, ImageStat
import style_router

MODELS = ("gpt-image-2.6-sunburst", "gpt-image-2.6-flare")
STYLES = {
    "flat": "Clean flat illustration; solid restrained colors, stable outlines and proportions, uncluttered full background. Motion: clear silhouettes, weight shift, anticipation, natural ease and settle.",
    "papercut": "Layered paper-cut illustration; tactile matte paper, restrained palette, consistent soft shadows and layer thickness. Motion: articulated natural gestures, stable paper shapes, smooth weight shifts; no arbitrary melting or frame jitter.",
    "clay": "Tactile clay miniature; stable sculpted features, soft studio light and simple full background. Motion: coherent joint movement and believable weight, readable anticipation and follow-through; no clay morphing or flickering texture.",
}
QUALITY_KEYS = ("identity", "style", "structure", "motion", "semantics", "loop", "clean_visual")
# Conservative per-frame defaults, not a claim about the service's pixel limits.
DEFAULT_SIZES = {"16:9": "512x288", "9:16": "288x512", "1:1": "512x512"}


class Failure(Exception):
    pass


def require(ok, code):
    if not ok:
        raise Failure(code)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(encode(value) + b"\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextlib.contextmanager
def locked(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def safe_id(value):
    require(isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", value), "invalid_id")
    return value


def inside(root, relative):
    require(isinstance(relative, str) and relative and not Path(relative).is_absolute(), "relative_path_required")
    result = (Path(root) / relative).resolve()
    require(result.is_relative_to(Path(root).resolve()), "path_outside_bundle")
    return result


def nonempty(value, code):
    require(isinstance(value, str) and bool(value.strip()), code)
    return value


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def plan_timing(shot):
    """Resolve native GIF timing before spending a generation request.

    Exact timing uses only the service's uniform 10 ms frame delays. It never
    retimes returned media. Approximation requires an explicit policy.
    """
    duration = shot.get("target_duration_s", 2.4)
    require(number(duration) and duration > 0, "invalid_duration")
    policy = shot.get("duration_policy", "exact")
    require(policy in ("exact", "quantize"), "invalid_duration_policy")
    count = shot.get("frame_count")
    require(count is None or type(count) is int and 2 <= count <= 16, "frame_count_out_of_range")
    ticks = duration * 100  # GIF delays have 10 ms precision.
    if policy == "exact":
        require(abs(ticks - round(ticks)) < 1e-7, "duration_requires_10ms_precision")
        ticks = round(ticks)
        candidates = [n for n in range(16, 1, -1) if ticks % n == 0 and 2 <= ticks // n <= 200]
        require(bool(candidates), "exact_duration_not_representable")
        if count is None:
            count = candidates[0]
        require(count in candidates, "frame_count_cannot_represent_exact_duration_omit_frame_count_or_choose_quantize")
        delay = ticks // count * 10
    else:
        count = count or 16
        delay = int(math.floor(duration * 1000 / count / 10 + 0.5) * 10)
        require(20 <= delay <= 2000, "duration_out_of_range_for_frame_count")
    encoded_duration = count * delay / 1000
    return count, delay, {"policy": policy, "target_duration_s": duration,
                          "planned_duration_s": encoded_duration,
                          "duration_error_s": round(encoded_duration - duration, 9)}


def probe_cli(binary):
    try:
        version = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10)
        features = subprocess.run([binary, "features", "list"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return {"path": binary, "available": False, "animation_flag_known": False, "animation_enabled": False}
    lines = [line for line in features.stdout.splitlines() if line.split() and line.split()[0] == "image_generation_animation"]
    return {"path": binary, "available": version.returncode == 0, "version": version.stdout.strip(),
            "animation_flag_known": features.returncode == 0 and bool(lines),
            "animation_enabled": bool(lines) and lines[0].split()[-1] == "true"}


def doctor(binary=None):
    shell = probe_cli(shutil.which("codex") or "codex")
    clients = {"shell": shell}
    app = Path("/Applications/ChatGPT.app")
    bundled = app / "Contents/Resources/codex-cli/bin/codex"
    if bundled.is_file():
        clients["desktop_bundled"] = probe_cli(str(bundled))
    if binary:
        clients["selected_diagnostic"] = probe_cli(str(Path(binary).resolve()))
    app_info = {}
    info = app / "Contents/Info.plist"
    if info.is_file():
        data = plistlib.loads(info.read_bytes())
        app_info = {k:data.get(k) for k in ("CFBundleShortVersionString", "CFBundleVersion")}
    return {
        "checked_at": now(), "codex_cli": shell.get("version"), "clients": clients, "desktop_app": app_info,
        "cli_animation_feature_listed": shell["animation_flag_known"],
        "host_native_gif": "unknown_requires_current_tool_schema_and_model_evidence",
        "entry": "codex_session_only", "api_client": False, "generation_calls": 0,
        "note": "A known disabled flag can be enabled per invocation on that client. Shell CLI, bundled desktop client, current tool schema and server eligibility are separate layers. No setting was changed.",
    }


def reserve(budget_file, kind, label, request_binding=None, retry=False):
    require(kind in ("gif", "reference"), "invalid_budget_kind")
    with locked(str(budget_file) + ".lock"):
        b = read_json(budget_file) if Path(budget_file).exists() else {
            "schema_version": 1, "limits": {"gif": 8, "reference": 3}, "attempts": []}
        if request_binding is not None:
            previous = [a for a in b["attempts"] if a.get("request_binding") == request_binding]
            if previous and previous[-1]["status"] == "reserved":
                return previous[-1]
            require(not previous or retry, "explicit_retry_required")
        require(sum(a["kind"] == kind for a in b["attempts"]) < b["limits"][kind], "budget_exhausted")
        entry = {"id": uuid.uuid4().hex, "kind": kind, "label": label, "reserved_at": now(), "status": "reserved"}
        if request_binding is not None:
            entry["request_binding"] = request_binding
        b["attempts"].append(entry)
        write_json(budget_file, b)
        return entry


def budget_status(budget_file, attempt_id, status):
    with locked(str(budget_file) + ".lock"):
        b = read_json(budget_file)
        entry = next(a for a in b["attempts"] if a["id"] == attempt_id)
        entry.update(status=status, updated_at=now())
        write_json(budget_file, b)


def profile(value, kind, request_dir):
    if value is None and kind == "character":
        return None, []
    require(isinstance(value, dict), "invalid_" + kind + "_profile")
    p = copy.deepcopy(value)
    safe_id(p.get("id"))
    nonempty(p.get("version"), "profile_version_required")
    nonempty(p.get("description"), "profile_description_required")
    for key in ("invariants", "allowed_changes", "forbidden_changes"):
        require(isinstance(p.get(key, []), list) and all(isinstance(x, str) for x in p.get(key, [])), "invalid_profile_rules")
    require(isinstance(p.get("references", []), list), "references_must_be_array")
    refs = []
    for r in p.get("references", []):
        require(isinstance(r, dict), "reference_must_be_object")
        nonempty(r.get("path"), "reference_path_required")
        nonempty(r.get("source"), "reference_source_required")
        path = (request_dir / r["path"]).resolve()
        raw = path.read_bytes()
        require(len(raw) <= 14 * 1024 * 1024, "reference_too_large")
        with Image.open(io.BytesIO(raw)) as im:
            require(im.format in ("PNG", "JPEG", "WEBP") and getattr(im, "n_frames", 1) == 1, "still_reference_required")
            im.load()
            ext = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}[im.format]
        refs.append({"path": "references/" + digest(raw) + ext, "sha256": digest(raw),
                     "role": r.get("role", kind), "source": r["source"], "_bytes": raw})
    p["references"] = [{k: v for k, v in r.items() if k != "_bytes"} for r in refs]
    return p, refs


def compile_request(request, request_dir):
    require(isinstance(request, dict), "request_must_be_object")
    require(request.get("schema_version") == 1, "schema_version_must_be_1")
    require(request.get("mode") in ("shot", "narration"), "invalid_mode")
    model = request.get("model", MODELS[0])
    require(model in MODELS, "only_image_2_6_allowed")
    shots = request.get("shots")
    require(isinstance(shots, list) and 0 < len(shots) <= 100, "semantic_planning_required_supply_shots")
    narration = request.get("narration")
    if request["mode"] == "narration":
        nonempty(narration, "narration_required")
    style_input, style_selection = style_router.resolve_profile(request)
    style, refs = profile(style_input, "style", request_dir)
    preset = style.get("preset", "custom")
    require(preset in ({e['id'] for e in style_router.catalog()['styles']} | {'custom'}), "unknown_style_preset")
    character, more = profile(request.get("character"), "character", request_dir)
    refs += more
    if request.get('source_materials'):
        _, materials=profile({'id':'source-materials','version':'1','description':'User-provided source material',
                             'references':request['source_materials']},'source_material',request_dir)
        refs += materials
    require(len(refs) <= 5, "too_many_references_codex_native_limit_5")
    assets, ids = [], set()
    for shot in shots:
        require(isinstance(shot, dict), "shot_must_be_object")
        sid = safe_id(shot.get("id"))
        require(sid not in ids, "duplicate_shot_id")
        ids.add(sid)
        intent = nonempty(shot.get("intent"), "intent_required")
        action = nonempty(shot.get("action"), "action_required")
        start = nonempty(shot.get("initial_state"), "initial_state_required")
        end = nonempty(shot.get("end_state"), "end_state_required")
        ratio = shot.get("aspect_ratio", request.get("aspect_ratio", "16:9"))
        require(ratio in ("16:9", "9:16", "1:1"), "unsupported_aspect_ratio")
        count, delay, timing_plan = plan_timing(shot)
        duration = timing_plan["target_duration_s"]
        requested_size = shot.get("size", request.get("size", "auto"))
        size = DEFAULT_SIZES[ratio] if requested_size == "auto" else requested_size
        require(isinstance(size, str), "invalid_size")
        if size != "auto":
            m = re.fullmatch(r"([1-9][0-9]*)x([1-9][0-9]*)", size)
            require(m is not None, "invalid_size")
            w, h = map(int, m.groups())
            require(w % 16 == h % 16 == 0, "size_must_be_multiple_of_16")
            rw, rh = map(int, ratio.split(":"))
            require(abs(w / h / (rw / rh) - 1) <= .02, "size_aspect_mismatch")
        loop = shot.get("loop", "once")
        require(loop in ("once", "seamless"), "invalid_loop")
        source = shot.get("source_text")
        span = None
        if request["mode"] == "narration":
            nonempty(source, "source_text_required")
            at = shot.get("source_start")
            if at is None:
                require(narration.count(source) == 1, "source_text_missing_or_ambiguous")
                at = narration.index(source)
            require(type(at) is int and at >= 0 and narration[at:at + len(source)] == source, "source_span_mismatch")
            span = [at, at + len(source)]
        timing = shot.get("time_range_s")
        if timing is not None:
            require(isinstance(timing, list) and len(timing) == 2 and all(number(x) for x in timing) and 0 <= timing[0] < timing[1], "invalid_time_range")
        prompt = "\n".join([
            "Generate a native animated GIF, not a sprite sheet, storyboard or static image.",
            f"Meaning to communicate: {intent}", f"Initial state: {start}", f"Motion: {action}", f"End state: {end}",
            f"Style: {STYLES.get(preset, '')} {style['description']}",
            "Style invariants: " + json.dumps(style.get("invariants", []), ensure_ascii=False),
            "Style allowed changes: " + json.dumps(style.get("allowed_changes", []), ensure_ascii=False),
            "Style forbidden changes: " + json.dumps(style.get("forbidden_changes", []), ensure_ascii=False),
            "Character: " + (json.dumps({k:v for k,v in character.items() if k not in ('style_lock','preferred_style')}, ensure_ascii=False) if character else "No recurring character specified."),
            "Identity priority: preserve the master reference face geometry, body proportions, eyewear and specified costume colors. When adapting style, change linework/material/background only; never recolor locked clothes or redesign the person to fit the palette." if character else "No recurring character identity constraints.",
            "References in order: " + json.dumps([{k:v for k,v in r.items() if k != "_bytes"} for r in refs], ensure_ascii=False),
            f"Composition: {ratio}, finished frame size {size}; uncluttered complete background; keep all moving parts in frame.",
            f"Timing: {count} frames, {delay} milliseconds each. Loop intent: {loop}.",
            "For once: show a clear start and completed end, do not force a reset. For seamless: match the loop boundary naturally.",
            "Natural coherent motion, stable identity, clothing, anatomy, props, lighting and material. Anticipation, weight transfer and a readable settle; no idle wobble replacing the requested action.",
            "No subtitles, captions, written labels, sound or camera cuts. Do not compensate for limited frames by repeating unrelated poses.",
        ])
        require(len(prompt) <= 32000, "prompt_too_long")
        assets.append({"id": sid, "intent": intent, "action": action, "initial_state": start, "end_state": end,
                       "source_text": source, "source_span": span, "time_range_s": timing,
                       "aspect_ratio": ratio, "target_duration_s": duration, "timing_plan": timing_plan,
                       "size_selection": {"requested": requested_size, "resolved": size,
                                          "basis": "aspect_ratio_default" if requested_size == "auto" else "explicit"},
                       "loop_intent": loop,
                       "parameters": {"model": model, "output_format": "gif", "n": 1, "size": size,
                                      "frame_count": count, "frame_duration_ms": delay},
                       "prompt": prompt, "status": "planned", "attempts": [], "selected_attempt": None})
        assets[-1]["spec_sha256"] = spec_hash(assets[-1])
    manifest = {"schema_version": 1, "mode": request["mode"], "narration": narration,
                "style": style, "style_selection": style_selection, "character": character, "assets": assets,
                "references": [{k:v for k,v in r.items() if k != "_bytes"} for r in refs]}
    manifest["request_fingerprint"] = digest(encode(manifest))
    return manifest, refs


def spec_hash(asset):
    return digest(encode({k:v for k,v in asset.items() if k not in ("status", "attempts", "selected_attempt", "spec_sha256")}))


def check_bundle(root, manifest):
    for a in manifest["assets"]:
        require(a.get("spec_sha256") == spec_hash(a), "asset_spec_changed_prepare_new_bundle")
    for r in manifest["references"]:
        require(digest(inside(root, r["path"]).read_bytes()) == r["sha256"], "reference_changed_prepare_new_bundle")


def prepare(request_file, out):
    request_file, out = Path(request_file).resolve(), Path(out).resolve()
    manifest, refs = compile_request(read_json(request_file), request_file.parent)
    with locked(out / ".lock"):
        target = out / "manifest.json"
        if target.exists():
            require(read_json(target)["request_fingerprint"] == manifest["request_fingerprint"], "request_changed_use_new_bundle")
            return read_json(target)
        for ref in refs:
            p = inside(out, ref["path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(ref["_bytes"])
        manifest["created_at"] = now()
        write_json(target, manifest)
    return manifest


def inspect_gif(path, asset=None):
    raw = Path(path).read_bytes()
    require(raw[:6] in (b"GIF87a", b"GIF89a"), "not_gif_bytes")
    with Image.open(io.BytesIO(raw)) as im:
        require(im.format == "GIF", "not_gif")
        count, size, loop = im.n_frames, im.size, im.info.get("loop")
        require(2 <= count <= 16, "not_supported_multiframe_gif")
        hashes, delays, diffs, prev = [], [], [], None
        for i in range(count):
            im.seek(i)
            frame = im.convert("RGBA")
            hashes.append(digest(frame.tobytes()))
            delay = im.info.get("duration", 0)
            require(type(delay) is int and 20 <= delay <= 2000, "invalid_frame_delay")
            delays.append(delay)
            rgb = frame.convert("RGB")
            if prev is not None:
                diffs.append(sum(ImageStat.Stat(ImageChops.difference(prev, rgb)).mean) / 3)
            prev = rgb.copy()
    require(len(set(hashes)) > 1, "duplicate_frames_only")
    mismatches = []
    if asset:
        p = asset["parameters"]
        if count != p["frame_count"]:
            mismatches.append("frame_count")
        if any(d != p["frame_duration_ms"] for d in delays):
            mismatches.append("frame_duration_ms")
        rw, rh = map(int, asset["aspect_ratio"].split(":"))
        if abs(size[0] / size[1] / (rw / rh) - 1) > .02:
            mismatches.append("aspect_ratio")
        if p["size"] != "auto" and p["size"] != f"{size[0]}x{size[1]}":
            mismatches.append("size")
    return {"sha256": digest(raw), "width": size[0], "height": size[1], "frame_count": count,
            "frame_durations_ms": delays, "duration_s": sum(delays) / 1000,
            "encoded_loop": loop, "distinct_frames": len(set(hashes)),
            "adjacent_mean_pixel_differences": diffs, "parameter_mismatches": mismatches,
            "status": "pass" if not mismatches else "fail",
            "motion_quality": "unverified_not_inferred_from_pixel_difference"}


def model_evidence(response, requested):
    effective = response.get("model")
    return {"requested_model": requested, "reported_model": effective,
            "status": "verified" if effective == requested and effective in MODELS else "unverified",
            "basis": "response_model" if effective else "native_tool_did_not_report_model"}


def official_request_evidence(payload, receipt):
    """Evidence of a completed explicit official request, not a model self-report.

    The API adapter records this only for new responses. Historical unknown
    records are never silently migrated by review/export.
    """
    supported = (
        payload.get("model") in MODELS
        and receipt.get("endpoint") in ("https://api.openai.com/v1/images/generations",
                                        "https://api.openai.com/v1/images/edits")
        and receipt.get("http_status") == 200
        and isinstance(receipt.get("request_id"), str) and bool(receipt["request_id"].strip())
        and receipt.get("redirects_allowed") is False
        and receipt.get("authentication_type") == "api_key"
        and receipt.get("requested_model") == payload["model"]
        and receipt.get("request_payload_sha256") == digest(encode(payload)))
    return {"schema_version": 1, "status": "verified" if supported else "unverified",
            "basis": "explicit_model_request_to_fixed_official_https_endpoint",
            "requested_model": payload.get("model"), "request_id": receipt.get("request_id"),
            "request_payload_sha256": digest(encode(payload)),
            "scope": "official_request_provenance_not_server_reported_model"}


def source_evidence_passes(attempt, asset):
    evidence = attempt.get("model_evidence", {})
    requested = asset["parameters"]["model"]
    reported = evidence.get("reported_model")
    # A contradictory model report is never overridden by request provenance.
    if reported is not None:
        return (requested in MODELS and reported == requested
                and evidence.get("requested_model") == requested and evidence.get("status") == "verified")
    if attempt.get("source_kind") != "official_api_native_gif":
        return False
    stored = attempt.get("official_request_evidence")
    payload = {**asset["parameters"], "prompt": asset["prompt"]}
    expected = official_request_evidence(payload, attempt.get("receipt", {}))
    return (stored == expected and expected["status"] == "verified"
            and attempt.get("request_payload_sha256") == expected["request_payload_sha256"]
            and evidence.get("requested_model") == requested)


def save_result(root, asset, attempt, raw, response, receipt):
    folder = inside(root, f"assets/{asset['id']}/{attempt['id']}")
    folder.mkdir(parents=True, exist_ok=True)
    # Preserve actual bytes even if the server violates the requested format.
    file = folder / ("original.gif" if raw[:6] in (b"GIF87a", b"GIF89a") else "unexpected-output.bin")
    file.write_bytes(raw)
    attempt.update(path=str(file.relative_to(root)), sha256=digest(raw), receipt=receipt,
                   model_evidence=model_evidence(response, asset["parameters"]["model"]),
                   response_metadata={k:response[k] for k in ("created", "model", "usage", "size", "output_format") if k in response})
    try:
        attempt["technical"] = inspect_gif(file, asset)
        attempt["status"] = "generated" if attempt["technical"]["status"] == "pass" else "technical_failed"
    except (Failure, OSError, EOFError, ValueError) as e:
        attempt.update(status="technical_failed", error=str(e))
    asset["selected_attempt"] = attempt["id"]
    asset["status"] = "pending_review" if attempt["status"] == "generated" else "technical_failed"
    write_json(folder / "receipt.json", attempt)


def record_review(bundle, shot_id, review_file):
    root = Path(bundle).resolve()
    with locked(root / ".lock"):
        manifest = read_json(root / "manifest.json")
        check_bundle(root, manifest)
        asset = next((a for a in manifest["assets"] if a["id"] == shot_id), None)
        require(asset is not None and asset["selected_attempt"], "no_selected_asset")
        attempt = next(a for a in asset["attempts"] if a["id"] == asset["selected_attempt"])
        review = read_json(review_file)
        require(isinstance(review, dict), "review_must_be_object")
        require(review.get("asset_sha256") == attempt["sha256"] == digest(inside(root, attempt["path"]).read_bytes()), "stale_review")
        nonempty(review.get("reviewer"), "reviewer_required")
        evidence = review.get("evidence_files")
        require(isinstance(evidence, list) and evidence, "review_evidence_required")
        copied = []
        for p in evidence:
            file = (Path(review_file).resolve().parent / p).resolve()
            raw = file.read_bytes()
            dest = f"reviews/{digest(raw)}{file.suffix}"
            target = inside(root, dest)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            copied.append({"path": dest, "sha256": digest(raw)})
        checks = review.get("checks", {})
        require(all(checks.get(k) in ("pass", "fail", "unknown") for k in QUALITY_KEYS), "all_quality_checks_required")
        review["evidence_files"] = copied
        review["recorded_at"] = now()
        attempt["review"] = review
        passed = (all(checks[k] == "pass" for k in QUALITY_KEYS)
                  and review.get("full_playback_observed") is True
                  and review.get("all_frames_observed") is True
                  and attempt.get("technical", {}).get("status") == "pass"
                  and source_evidence_passes(attempt, asset))
        asset["status"] = "ready" if passed else "not_ready"
        write_json(root / "manifest.json", manifest)
        return {"id": shot_id, "status": asset["status"], "note": "Review records are operator attestations; scripts do not certify perception."}


def export_ready(bundle, out):
    root, out = Path(bundle).resolve(), Path(out).resolve()
    require(not out.exists(), "export_destination_exists")
    with locked(root / ".lock"):
        m = read_json(root / "manifest.json")
        check_bundle(root, m)
        ready = [a for a in m["assets"] if a["status"] == "ready"]
        require(bool(ready), "no_ready_assets")
        files, exported = {}, []
        for a in ready:
            attempt = next(x for x in a["attempts"] if x["id"] == a["selected_attempt"])
            path = inside(root, attempt["path"])
            require(digest(path.read_bytes()) == attempt["sha256"], "asset_changed_after_review")
            require(inspect_gif(path, a)["status"] == "pass", "technical_check_failed")
            r = attempt["review"]
            require(r["asset_sha256"] == attempt["sha256"] and r.get("full_playback_observed") is True
                    and r.get("all_frames_observed") is True and all(r["checks"][k] == "pass" for k in QUALITY_KEYS)
                    and source_evidence_passes(attempt, a), "quality_gate_failed")
            for e in r["evidence_files"]:
                file = inside(root, e["path"])
                require(digest(file.read_bytes()) == e["sha256"], "review_evidence_changed")
                files[e["path"]] = file
            files[attempt["path"]] = path
            receipt = attempt["receipt"]
            if receipt.get("tool_log"):
                log = inside(root, receipt["tool_log"])
                require(digest(log.read_bytes()) == receipt["tool_log_sha256"], "native_tool_log_changed")
                files[receipt["tool_log"]] = log
            exported.append({k: a[k] for k in ("id", "intent", "action", "source_text", "source_span", "time_range_s", "loop_intent", "aspect_ratio")} | {
                "path": attempt["path"], "sha256": attempt["sha256"], "technical": attempt["technical"],
                "source_kind": attempt["source_kind"], "request_payload_sha256": attempt.get("request_payload_sha256"),
                "model_evidence": attempt["model_evidence"], "receipt": attempt["receipt"],
                "official_request_evidence": attempt.get("official_request_evidence"),
                "review": r, "status": "ready", "prompt": a["prompt"], "parameters": a["parameters"]})
        for ref in m["references"]:
            path = inside(root, ref["path"])
            require(digest(path.read_bytes()) == ref["sha256"], "reference_changed")
            files[ref["path"]] = path
        out.mkdir(parents=True)
        try:
            for relative, source in files.items():
                dest = inside(out, relative)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, dest)
            write_json(out / "manifest.json", {"schema_version": 1, "created_at": now(), "kind": "ready_gif_assets",
                       "request_fingerprint": m["request_fingerprint"], "style": m["style"], "character": m["character"],
                       "style_selection": m.get('style_selection'),
                       "references": m["references"], "assets": exported,
                       "excluded_ids": [a["id"] for a in m["assets"] if a["status"] != "ready"]})
        except Exception:
            shutil.rmtree(out)
            raise
    return {"out": str(out), "ready_count": len(exported)}


def native_request(bundle, shot_id, budget_file, retry=False):
    """Reserve once and expose a frozen prompt; this does NOT invoke a model."""
    root = Path(bundle).resolve()
    with locked(root / ".lock"):
        m = read_json(root / "manifest.json")
        check_bundle(root, m)
        a = next((x for x in m["assets"] if x["id"] == shot_id), None)
        require(a is not None, "shot_not_found")
        require(a["status"] not in ("ready", "pending_review"), "reuse_existing_asset")
        require(not a["attempts"] or retry, "explicit_retry_required")
        reservation = reserve(budget_file, "gif", shot_id,
                              {"bundle": str(root), "asset_id": shot_id, "spec_sha256": a["spec_sha256"]}, retry)
        native_args = {"prompt": a["prompt"], "transparent_background": False,
                       "gif": {"frame_count": a["parameters"]["frame_count"],
                               "frame_duration_ms": a["parameters"]["frame_duration_ms"]}}
        if m["references"]:
            native_args["referenced_image_paths"] = [str(inside(root, r["path"])) for r in m["references"]]
        return {"reservation": reservation, "entry": "codex_session_native_tool",
                "requested_model": a["parameters"]["model"], "prompt": a["prompt"],
                "native_tool_arguments": native_args,
                "parameters_if_supported_by_current_tool": a["parameters"],
                "reference_paths": [str(inside(root, r["path"])) for r in m["references"]],
                "spec_sha256": a["spec_sha256"], "request_fingerprint": m["request_fingerprint"],
                "note": "No generation was performed. Use native_tool_arguments only when the current tool schema exposes gif. model/size/output_format are requirements, not Codex imagegen parameters. A prompt mentioning GIF does not enable GIF output."}


def finish_attempt(budget_file, reservation_id, status, reason):
    require(status in ("failed", "outcome_unknown", "reference_received"), "invalid_finish_status")
    nonempty(reason, "reason_required")
    with locked(str(budget_file) + ".lock"):
        b = read_json(budget_file)
        r = next((x for x in b["attempts"] if x["id"] == reservation_id), None)
        require(r is not None and r["status"] == "reserved", "invalid_reservation")
        require(status != "reference_received" or r["kind"] == "reference", "not_reference_reservation")
        r.update(status=status, reason=reason, updated_at=now())
        write_json(budget_file, b)
        return r


def import_native(bundle, shot_id, file, evidence_file, budget_file, reservation_id):
    root = Path(bundle).resolve()
    evidence = read_json(evidence_file)
    require(isinstance(evidence, dict), "native_evidence_must_be_object")
    raw = Path(file).read_bytes()
    require(evidence.get("source_kind") == "codex_native_gif" and evidence.get("asset_sha256") == digest(raw), "native_evidence_mismatch")
    # Unknown model is retained as unknown, not replaced by the requested model.
    require(evidence.get("reported_model") is None or isinstance(evidence.get("reported_model"), str), "invalid_reported_model")
    log = (Path(evidence_file).resolve().parent / nonempty(evidence.get("tool_log"), "tool_log_required")).resolve()
    logbytes = log.read_bytes()
    require(bool(logbytes), "native_tool_log_empty")
    with locked(root / ".lock"):
        m = read_json(root / "manifest.json")
        check_bundle(root, m)
        a = next((x for x in m["assets"] if x["id"] == shot_id), None)
        require(a is not None, "shot_not_found")
        require(evidence.get("spec_sha256") == a["spec_sha256"], "native_spec_evidence_mismatch")
        binding = {"bundle": str(root), "asset_id": shot_id, "sha256": digest(raw), "spec_sha256": a["spec_sha256"], "tool_log_sha256": digest(logbytes)}
        with locked(str(budget_file) + ".lock"):
            b = read_json(budget_file)
            r = next((x for x in b["attempts"] if x["id"] == reservation_id), None)
            require(r is not None and r["kind"] == "gif" and r["label"] == shot_id, "invalid_native_reservation")
            if r.get("request_binding") is not None:
                require(r["request_binding"] == {"bundle": str(root), "asset_id": shot_id, "spec_sha256": a["spec_sha256"]},
                        "reservation_request_binding_mismatch")
            if "binding" in r:
                require(r["binding"] == binding, "native_reservation_bound_to_other_result")
            else:
                require(r["status"] == "reserved", "invalid_native_reservation")
            previous = next((x for x in a["attempts"] if x["id"] == reservation_id), None)
            if previous and previous.get("sha256") == digest(raw) and previous.get("status") in ("generated", "technical_failed"):
                require(digest(inside(root, previous["path"]).read_bytes()) == digest(raw), "imported_asset_changed")
                r.update(status=previous["status"], binding=binding, updated_at=now())
                write_json(budget_file, b)
                return {"id": shot_id, "status": a["status"], "reused": True}
            require(a["status"] not in ("ready", "pending_review"), "reuse_existing_asset")
            r.update(status="importing", binding=binding)
            write_json(budget_file, b)
        attempt = {"id": reservation_id, "source_kind": "codex_native_gif", "started_at": r["reserved_at"]}
        a["attempts"].append(attempt)
        try:
            dest = f"evidence/{digest(logbytes)}.txt"
            inside(root, dest).parent.mkdir(parents=True, exist_ok=True)
            inside(root, dest).write_bytes(logbytes)
            save_result(root, a, attempt, raw, {"model": evidence.get("reported_model")},
                        {"entry": "codex_native_tool", "tool_log": dest, "tool_log_sha256": digest(logbytes),
                         "spec_sha256": a["spec_sha256"],
                         "evidence_trust": "operator_supplied_requires_independent_review"})
            if attempt["model_evidence"]["status"] != "verified" and a["status"] == "pending_review":
                a["status"] = "pending_model_evidence"
            write_json(root / "manifest.json", m)
            budget_status(budget_file, reservation_id, attempt["status"])
            return {"id": shot_id, "status": a["status"]}
        except Exception:
            budget_status(budget_file, reservation_id, "import_failed")
            raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    d = sub.add_parser("doctor"); d.add_argument("--binary")
    d = sub.add_parser("prepare"); d.add_argument("--request", required=True); d.add_argument("--out", required=True)
    d = sub.add_parser("inspect"); d.add_argument("file")
    d = sub.add_parser("review"); d.add_argument("--bundle", required=True); d.add_argument("--shot", required=True); d.add_argument("--in", dest="input", required=True)
    d = sub.add_parser("export"); d.add_argument("--bundle", required=True); d.add_argument("--out", required=True)
    d = sub.add_parser("reserve"); d.add_argument("--budget-file", required=True); d.add_argument("--kind", choices=("gif", "reference"), required=True); d.add_argument("--label", required=True)
    d = sub.add_parser("native-request")
    for flag in ("bundle", "shot", "budget-file"):
        d.add_argument("--" + flag, required=True)
    d.add_argument("--retry", action="store_true")
    d = sub.add_parser("finish-attempt")
    for flag in ("budget-file", "reservation-id", "status", "reason"):
        d.add_argument("--" + flag, required=True)
    d = sub.add_parser("import-native")
    for flag in ("bundle", "shot", "file", "evidence", "budget-file", "reservation-id"):
        d.add_argument("--" + flag, required=True)
    args = p.parse_args()
    try:
        c = args.command
        if c == "doctor": result = doctor(args.binary)
        elif c == "prepare":
            m = prepare(args.request, args.out)
            result = {"manifest": str(Path(args.out).resolve() / "manifest.json"), "assets": len(m["assets"]), "request_fingerprint": m["request_fingerprint"]}
        elif c == "inspect": result = inspect_gif(args.file)
        elif c == "review": result = record_review(args.bundle, args.shot, args.input)
        elif c == "export": result = export_ready(args.bundle, args.out)
        elif c == "reserve": result = reserve(args.budget_file, args.kind, args.label)
        elif c == "native-request": result = native_request(args.bundle, args.shot, args.budget_file, args.retry)
        elif c == "finish-attempt": result = finish_attempt(args.budget_file, args.reservation_id, args.status, args.reason)
        elif c == "import-native": result = import_native(args.bundle, args.shot, args.file, args.evidence, args.budget_file, args.reservation_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if c == "import-native" and result["status"] in ("technical_failed", "pending_model_evidence", "not_ready"):
            return 2
        return 0
    except (Failure, OSError, ValueError, KeyError, TypeError, StopIteration, AttributeError) as e:
        print(json.dumps({"status": "blocked", "error": str(e)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
