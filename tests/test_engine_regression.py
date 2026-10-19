import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import cv2
import numpy as np

from cs_board_video import media
from helpers import fixture, prepare_images, prepare_audio, prepare_plans


class UpstreamParityTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("CS_BOARD_SOURCE"), "设置 CS_BOARD_SOURCE 才能比较上游实际输出")
    def test_native_frames_match_upstream(self):
        with tempfile.TemporaryDirectory() as base:
            p = prepare_plans(prepare_audio(prepare_images(fixture(base))))
            # Upstream's CLI has a fixed default canvas; compare like for like.
            p.data["config"]["canvas_hex"] = "#F6F1E3"
            source = Path(os.environ["CS_BOARD_SOURCE"])
            image = p.path("scenes/scene-001/image.png")
            annotation_path = p.path("scenes/scene-001/annotation.json")
            upstream = p.path("render/cache/upstream.mp4")
            subprocess.run([sys.executable, str(source / "scripts/render_stream_whiteboard.py"),
                            str(image), str(annotation_path), str(upstream), "--bare-tip", "--keep-raw",
                            "--ink-path", "skeleton", "--color-fill", "contour-wipe", "--cap-long-edge", "320",
                            "--fps", "10", "--stroke-detail", "light"], check=True, capture_output=True)
            renderer = media.native_renderer(p, "scene-001", p.load("scenes/scene-001/annotation.json"))
            migrated = p.path("render/cache/migrated.mp4")
            renderer.render_to(migrated, 2000)
            a, b = cv2.VideoCapture(str(upstream)), cv2.VideoCapture(str(migrated))
            compared = 0
            try:
                while True:
                    ar, af = a.read()
                    br, bf = b.read()
                    self.assertEqual(ar, br)
                    if not ar:
                        break
                    self.assertTrue(np.array_equal(af, bf))
                    compared += 1
            finally:
                a.release()
                b.release()
            self.assertEqual(compared, 20)
