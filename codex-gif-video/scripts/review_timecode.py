#!/usr/bin/env python3
"""Map a millisecond in an exported GIF or MP4 to its original shot and frame."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import native_gif as core


def locate(movie, at_ms, note=None):
    core.require(type(at_ms) is int and at_ms >= 0, "timecode_must_be_nonnegative_ms")
    movie = Path(movie).resolve()
    receipt = core.read_json(str(movie) + ".render.json")
    core.require(receipt["status"] == "rendered_pending_review", "completed_render_receipt_required")
    sha = hashlib.sha256()
    with movie.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    core.require(receipt["output"]["sha256"] == sha.hexdigest(), "rendered_file_hash_mismatch")

    sources = receipt["plan"]["sources"]
    core.require(isinstance(sources, list) and sources, "empty_render_timeline")
    position = 0
    match = None
    for shot_number, source in enumerate(sources, start=1):
        start_ms = position
        technical = source["technical"]
        delays = technical["frame_durations_ms"]
        core.require(isinstance(delays, list) and len(delays) == technical["frame_count"]
                     and delays and all(type(ms) is int and ms > 0 for ms in delays),
                     "invalid_source_frame_delays")
        for frame_index, delay in enumerate(delays):
            if position <= at_ms < position + delay:
                # Early single-bundle receipts kept one shared manifest at plan level.
                manifest_path = source.get("manifest") or receipt["plan"].get("manifest")
                core.require(isinstance(manifest_path, str) and manifest_path, "source_manifest_missing")
                match = {
                    "movie_sha256": sha.hexdigest(), "at_ms": at_ms,
                    "shot_number": shot_number, "shot_id": source["id"], "shot_time_ms": at_ms - start_ms,
                    "source_frame_index": frame_index, "frame_start_in_movie_ms": position,
                    "frame_end_in_movie_ms": position + delay, "source_sha256": source["sha256"],
                    "source_manifest": manifest_path, "source_path": source["path"],
                }
            position += delay
    core.require(abs(receipt["plan"]["duration_s"] * 1000 - position) < 0.001,
                 "render_timeline_duration_mismatch")
    core.require(match is not None, f"timecode_outside_movie:duration_ms={position}")
    if note is not None:
        match["note"] = core.nonempty(note, "empty_review_note")
    return match


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--movie", required=True, help="export with its adjacent .render.json receipt")
    parser.add_argument("--at-ms", required=True, type=int, help="milliseconds since playback start")
    parser.add_argument("--note", help="optional observation for the revision")
    args = parser.parse_args()
    try:
        print(json.dumps(locate(args.movie, args.at_ms, args.note), ensure_ascii=False, indent=2))
        return 0
    except (core.Failure, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
