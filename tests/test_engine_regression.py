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
from cs_board_video.upstream.scripts.stream_render import _load_hand, TipOverlay


class HandAssetTests(unittest.TestCase):
    def test_faint_cutout_residue_does_not_offset_pen_contact(self):
        with tempfile.TemporaryDirectory() as base:
            path = Path(base) / "hand.png"
            rgba = np.zeros((40, 40, 4), dtype=np.uint8)
            rgba[10:30, 12:32] = (40, 60, 80, 255)
            rgba[0, 0] = (40, 60, 80, 1)
            rgba[39, 39] = (40, 60, 80, 1)
            cv2.imencode(".png", rgba)[1].tofile(str(path))
            hand, mask = _load_hand(path, 20)
            canvas = np.full((60, 60, 3), 255, dtype=np.uint8)
            TipOverlay(hand, mask).stamp(canvas, 15, 15)
            self.assertTrue(np.array_equal(canvas[15, 15], [40, 60, 80]))
            self.assertTrue(np.all(canvas[:15] == 255))
            self.assertTrue(np.all(canvas[:, :15] == 255))
            self.assertTrue(np.all(canvas[35:] == 255))
            self.assertTrue(np.all(canvas[:, 35:] == 255))

    def test_crop_preserves_translucent_pixels_inside_hand(self):
        with tempfile.TemporaryDirectory() as base:
            path = Path(base) / "hand.png"
            rgba = np.zeros((12, 12, 4), dtype=np.uint8)
            rgba[2:10, 2:10] = (40, 60, 80, 255)
            rgba[4, 4, 3] = 128
            rgba[5, 5, 3] = 4
            cv2.imencode(".png", rgba)[1].tofile(str(path))
            hand, mask = _load_hand(path, 8)
            canvas = np.full((8, 8, 3), 255, dtype=np.uint8)
            TipOverlay(hand, mask).stamp(canvas, 0, 0)
            for position, alpha in ((2, 128), (3, 4)):
                expected = np.array([40, 60, 80]) * (alpha / 255) + 255 - alpha
                np.testing.assert_allclose(canvas[position, position], expected, atol=1)


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
