#!/usr/bin/env python3
"""Optional, explicitly selected official Image 2.6 API adapter.

No proxy provider/base-URL override, no OAuth credential reuse, no animation assembly.
"""
import argparse
import base64
import binascii
import copy
import http.client
import json
import os
from pathlib import Path
import re
import stat
import sys
import urllib.error
import urllib.request

import native_gif as core
from PIL import Image
import io

API = "https://api.openai.com/v1"
MAX_RESPONSE_BYTES = 64 * 1024 * 1024


class ApiFailure(core.Failure):
    def __init__(self, details):
        self.details = details
        super().__init__(details.get("code", "api_request_failed"))


def redact(text, key=""):
    text = str(text)
    if key:
        text = text.replace(key, "[REDACTED]")
    return re.sub(r"sk-[^\s\"'<>]+", "[REDACTED]", text)[:2000]


def load_key(env_file=None):
    if env_file is not None:
        path = Path(env_file)
        core.require(path.is_file() and not path.is_symlink(), "private_credential_file_required")
        mode = stat.S_IMODE(path.stat().st_mode)
        core.require(mode & 0o077 == 0, "credential_file_permissions_require_0600")
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.fullmatch(r"\s*(?:export\s+)?OPENAI_API_KEY\s*=\s*(.*?)\s*", line)
            if match:
                key = match.group(1).strip("\"'").strip()
                core.require(bool(key) and "\n" not in key and "\r" not in key, "official_api_key_missing")
                return key
        raise core.Failure("official_api_key_missing")
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    core.require(bool(key) and "\n" not in key and "\r" not in key, "official_api_key_missing")
    return key


def status(env_file=None):
    try:
        key = load_key(env_file)
        return {"configured": bool(key), "source": "private_env_file" if env_file else "environment",
                "file_mode": oct(stat.S_IMODE(Path(env_file).stat().st_mode)) if env_file else None,
                "endpoint": API, "authentication": "untested", "generation_calls": 0}
    except core.Failure as e:
        return {"configured": False, "reason": str(e), "generation_calls": 0}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_image(payload, references, key):
    core.require(payload.get("model") in core.MODELS, "only_image_2_6_allowed")
    core.require(payload.get("output_format") in ("gif", "png"), "native_gif_or_still_reference_required")
    body = copy.deepcopy(payload)
    endpoint = API + ("/images/edits" if references else "/images/generations")
    if references:
        body["images"] = [{"image_url": "data:" + mime + ";base64," + base64.b64encode(raw).decode("ascii")}
                          for mime, raw in references]
    request = urllib.request.Request(endpoint, data=core.encode(body), method="POST", headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=300) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            core.require(len(raw) <= MAX_RESPONSE_BYTES, "api_response_too_large")
            receipt = {"endpoint": endpoint, "request_id": response.headers.get("x-request-id"),
                       "http_status": response.status, "received_at": core.now(),
                       "authentication_type": "api_key", "redirects_allowed": False}
            try:
                result = json.loads(raw)
            except (ValueError, UnicodeError):
                raise ApiFailure({"code": "invalid_json_response", "status": response.status}) from None
            core.require(isinstance(result, dict), "api_response_must_be_object")
            return result, receipt
    except urllib.error.HTTPError as e:
        details = {"status": e.code, "code": "http_error", "request_id": e.headers.get("x-request-id")}
        try:
            error = json.loads(e.read(65536)).get("error", {})
            if isinstance(error, dict):
                for field in ("code", "type", "param", "message"):
                    if error.get(field) is not None:
                        details[field] = redact(error[field], key)
        except (ValueError, TypeError, AttributeError):
            pass
        raise ApiFailure(details) from None
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError):
        raise ApiFailure({"code": "network_error_outcome_unknown", "status": None,
                          "message": "No automatic retry; the service may have received the request."}) from None


def generate(bundle, shot_id, budget_file, env_file=None, retry=False):
    root = Path(bundle).resolve()
    with core.locked(root / ".lock"):
        m = core.read_json(root / "manifest.json")
        core.check_bundle(root, m)
        asset = next((a for a in m["assets"] if a["id"] == shot_id), None)
        core.require(asset is not None, "shot_not_found")
        if asset["status"] in ("ready", "pending_review", "pending_model_evidence"):
            selected = next(a for a in asset["attempts"] if a["id"] == asset["selected_attempt"])
            core.require(core.digest(core.inside(root, selected["path"]).read_bytes()) == selected["sha256"], "asset_changed")
            return m
        core.require(not asset["attempts"] or retry, "explicit_retry_required")
        payload = {**asset["parameters"], "prompt": asset["prompt"]}
        core.require(payload["model"] in core.MODELS and payload["output_format"] == "gif" and payload["n"] == 1,
                     "one_native_image_2_6_gif_required")
        core.require(payload.get("size") not in (None, "auto"), "explicit_frame_size_required_prepare_new_bundle")
        key = load_key(env_file)  # missing credentials must not reserve or call
        references = []
        for ref in m["references"]:
            path = core.inside(root, ref["path"])
            raw = path.read_bytes()
            core.require(core.digest(raw) == ref["sha256"], "reference_changed")
            mime = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}[path.suffix]
            references.append((mime, raw))
        binding = {"bundle": str(root), "asset_id": shot_id, "spec_sha256": asset["spec_sha256"], "entry": "official_api"}
        reservation = core.reserve(budget_file, "gif", shot_id, binding, retry)
        attempt = {"id": reservation["id"], "source_kind": "official_api_native_gif", "status": "in_flight",
                   "started_at": core.now(), "requested_model": payload["model"],
                   "request_payload_sha256": core.digest(core.encode(payload)),
                   "reference_sha256": [ref["sha256"] for ref in m["references"]]}
        asset["attempts"].append(attempt)
        asset["status"] = "in_flight"
        core.write_json(root / "manifest.json", m)
        core.budget_status(budget_file, reservation["id"], "in_flight")
        try:
            response, receipt = request_image(payload, references, key)
            data = response.get("data")
            core.require(isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict)
                         and isinstance(data[0].get("b64_json"), str), "expected_one_base64_asset")
            raw = base64.b64decode(data[0]["b64_json"], validate=True)
            core.require(len(raw) <= 32 * 1024 * 1024, "decoded_asset_too_large")
            receipt.update(entry="official_image_api", requested_model=payload["model"],
                           request_payload_sha256=attempt["request_payload_sha256"])
            core.save_result(root, asset, attempt, raw, response, receipt)
            attempt["official_request_evidence"] = core.official_request_evidence(payload, receipt)
            if attempt["model_evidence"]["reported_model"] is None:
                attempt["model_evidence"]["basis"] = "explicit_official_request_only_no_reported_model"
            if not core.source_evidence_passes(attempt, asset) and asset["status"] == "pending_review":
                asset["status"] = "pending_model_evidence"
            core.write_json(core.inside(root, f"assets/{asset['id']}/{attempt['id']}/receipt.json"), attempt)
        except ApiFailure as e:
            attempt.update(status="failed", error=e.details, completed_at=core.now())
            asset["status"] = "failed"
        except (core.Failure, ValueError, KeyError, TypeError, OSError, binascii.Error) as e:
            attempt.update(status="failed", error={"code": "local_processing_failed", "message": redact(e, key)},
                           completed_at=core.now())
            asset["status"] = "failed"
        core.write_json(root / "manifest.json", m)
        core.budget_status(budget_file, reservation["id"], attempt["status"])
        return m


def reference(prompt_file, out, budget_file, env_file=None, model=core.MODELS[0]):
    core.require(model in core.MODELS, "only_image_2_6_allowed")
    target=Path(out).resolve()
    core.require(target.suffix.lower()==".png", "reference_output_must_be_png")
    core.require(not target.exists() and not Path(str(target)+'.json').exists(), "reference_destination_exists")
    prompt=Path(prompt_file).read_text(encoding='utf-8')
    core.require(0<len(prompt)<=32000, "invalid_reference_prompt")
    key=load_key(env_file)
    payload={"model":model,"prompt":prompt,"output_format":"png","n":1,"size":"1024x1024","quality":"high"}
    entry=core.reserve(budget_file,"reference",target.name)
    record={"id":entry['id'],"kind":"reference","requested_model":model,"prompt":prompt,
            "request_payload_sha256":core.digest(core.encode(payload)),"status":"in_flight"}
    target.parent.mkdir(parents=True,exist_ok=True)
    core.write_json(str(target)+'.json',record)
    core.budget_status(budget_file,entry['id'],'in_flight')
    try:
        response,receipt=request_image(payload,[],key)
        receipt.update(requested_model=model, request_payload_sha256=record['request_payload_sha256'])
        data=response.get('data')
        core.require(isinstance(data,list) and len(data)==1 and isinstance(data[0],dict),"expected_one_reference")
        raw=base64.b64decode(data[0]['b64_json'],validate=True)
        with Image.open(io.BytesIO(raw)) as im:
            core.require(im.format=='PNG' and getattr(im,'n_frames',1)==1,"expected_still_png")
            im.load();dimensions=list(im.size)
        target.write_bytes(raw)
        record.update(status='reference_generated_pending_visual_review',sha256=core.digest(raw),dimensions=dimensions,
                      receipt=receipt,model_evidence=core.model_evidence(response,model),
                      official_request_evidence=core.official_request_evidence(payload,receipt))
        if record['model_evidence']['reported_model'] is None:
            record['model_evidence']['basis']='explicit_official_request_only_no_reported_model'
        elif record['model_evidence']['reported_model'] != model:
            record['status']='reference_model_mismatch'
            record['source_issue']='reported_model_conflicts_with_requested_model'
        if (record['status'] != 'reference_model_mismatch'
                and record['official_request_evidence']['status'] != 'verified'):
            record['status']='reference_pending_source_evidence'
            record['source_issue']='official_request_receipt_incomplete_or_inconsistent'
    except ApiFailure as e:
        record.update(status='failed',error=e.details)
    except (core.Failure,ValueError,KeyError,TypeError,OSError,binascii.Error) as e:
        record.update(status='failed',error={'code':'reference_processing_failed','message':redact(e,key)})
    core.write_json(str(target)+'.json',record)
    core.budget_status(budget_file,entry['id'],record['status'])
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("status"); p.add_argument("--env-file")
    p = sub.add_parser("generate")
    for flag in ("bundle", "shot", "budget-file"):
        p.add_argument("--" + flag, required=True)
    p.add_argument("--env-file"); p.add_argument("--retry", action="store_true")
    p=sub.add_parser('reference')
    for flag in ('prompt-file','out','budget-file'):
        p.add_argument('--'+flag,required=True)
    p.add_argument('--env-file');p.add_argument('--model',choices=core.MODELS,default=core.MODELS[0])
    args = parser.parse_args()
    try:
        if args.command == "status":
            result = status(args.env_file)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["configured"] else 2
        if args.command == 'reference':
            result=reference(args.prompt_file,args.out,args.budget_file,args.env_file,args.model)
            print(json.dumps(result,ensure_ascii=False,indent=2))
            return 0 if result['status']=='reference_generated_pending_visual_review' else 2
        m = generate(args.bundle, args.shot, args.budget_file, args.env_file, args.retry)
        asset = next(a for a in m["assets"] if a["id"] == args.shot)
        attempt = asset["attempts"][-1] if asset["attempts"] else {}
        result = {"id": asset["id"], "status": asset["status"], "path": attempt.get("path"),
                  "technical": attempt.get("technical"), "model_evidence": attempt.get("model_evidence"),
                  "official_request_evidence": attempt.get("official_request_evidence"),
                  "error": attempt.get("error"), "receipt": attempt.get("receipt")}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if asset["status"] in ("ready", "pending_review", "pending_model_evidence") else 2
    except (core.Failure, OSError, ValueError, KeyError, TypeError) as e:
        # Never echo a credential-file line or raw remote response.
        print(json.dumps({"status": "blocked", "error": redact(e)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
