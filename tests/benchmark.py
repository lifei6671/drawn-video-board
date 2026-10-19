"""Reproducible engineering fixture, never a production authorization source.

Run: python tests/benchmark.py [--name benchmark-six-scenes] [--width 640 --height 360]
All approvals below are explicitly synthetic; audio is a sine tone, not narration.
"""
import argparse
from pathlib import Path
import tempfile

from helpers import fixture, prepare_images, prepare_audio, prepare_plans, approve
from cs_board_video import workflow as w


def main():
    cli = argparse.ArgumentParser(description="生成工程验收夹具，不代表用户视频批准")
    cli.add_argument("--name", default="benchmark-six-scenes")
    cli.add_argument("--width", type=int, default=640)
    cli.add_argument("--height", type=int, default=360)
    cli.add_argument("--fps", type=int, default=15)
    cli.add_argument("--count", type=int, default=6)
    cli.add_argument("--hand", action="store_true")
    args = cli.parse_args()
    with tempfile.TemporaryDirectory() as temporary:
        p = fixture(temporary, count=args.count, width=args.width, height=args.height, fps=args.fps,
                    content=Path.cwd() / "content", name=args.name)
    if args.hand:
        p.data["config"]["bare_tip"] = False
        p.persist()
    prepare_plans(prepare_audio(prepare_images(p)))
    w.render(p, True, size=[320, 180])
    w.compose(p, True)
    approve(p, "preview")
    w.render(p, False)
    w.compose(p, False)
    report = w.validate_final(p)
    p.save("reports/benchmark.json", {"fixture_only": True, "synthetic_approvals": True,
           "audio": "sine-tone, not speech", "image_source": "deterministic test geometry",
           "human_acceptance": "NOT_RUN", "technical": report})
    print(p.path("output/final.mp4"))


if __name__ == "__main__":
    main()
