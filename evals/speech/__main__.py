"""CLI: ``python -m evals.speech <command>``.

Commands:

- ``speechocean [--dev N] [--test N]`` — transcribe speechocean762 samples
  (external, expert-labelled; download first, see ``docs/multimodal-assessment.md``);
- ``synthetic-build`` — generate the synthetic Spanish set (Edge TTS, network);
- ``synthetic`` — transcribe the synthetic set;
- ``formats`` — offline format and edge-case checks (Windows TTS + ffmpeg);
- ``report`` — score every stored run and write ``results/speech-benchmark.{json,md}``.

The real recogniser (local Whisper) is used throughout; nothing here mocks it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from evals.speech.run import RESULTS, load, run_clips


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.speech")
    sub = parser.add_subparsers(dest="command", required=True)
    so = sub.add_parser("speechocean")
    so.add_argument("--dev", type=int, default=300)
    so.add_argument("--test", type=int, default=600)
    sub.add_parser("synthetic-build")
    sub.add_parser("synthetic")
    sub.add_parser("formats")
    sub.add_parser("report")
    args = parser.parse_args(argv)

    if args.command == "speechocean":
        from evals.speech import speechocean

        if not speechocean.available():
            print("speechocean762 not found under evals/speech/external/ (see the docs)")
            return 2
        run_clips(speechocean.sample("train", args.dev), RESULTS / "speechocean-dev.jsonl")
        run_clips(speechocean.sample("test", args.test), RESULTS / "speechocean-test.jsonl")
        return 0
    if args.command == "synthetic-build":
        from evals.speech.synthetic import build

        print(asyncio.run(build()))
        return 0
    if args.command == "synthetic":
        from evals.speech.synthetic import manifest

        run_clips(manifest(), RESULTS / "synthetic.jsonl")
        return 0
    if args.command == "formats":
        from evals.speech.formats import run_formats

        print(json.dumps(run_formats(), indent=1))
        return 0
    if args.command == "report":
        from evals.speech.analysis import analyse_speechocean, analyse_synthetic
        from evals.speech.report import render

        data: dict[str, object] = {}
        dev, test = (
            load(RESULTS / "speechocean-dev.jsonl"),
            load(RESULTS / "speechocean-test.jsonl"),
        )
        if dev and test:
            data["speechocean762"] = analyse_speechocean(dev, test)
        syn = load(RESULTS / "synthetic.jsonl")
        if syn:
            data["synthetic"] = analyse_synthetic(syn)
        fmt = RESULTS / "formats.json"
        if fmt.exists():
            data["formats"] = json.loads(fmt.read_text(encoding="utf-8"))
        (RESULTS / "speech-benchmark.json").write_text(
            json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8"
        )
        (RESULTS / "speech-benchmark.md").write_text(render(data), encoding="utf-8")
        print(f"wrote {RESULTS / 'speech-benchmark.md'}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
