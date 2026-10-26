"""Pen selection must change both the visible hand and actual stroke footprint."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from cs_board_video import bridge, media, pens, styles, workflow as w
from cs_board_video.cli import main
from cs_board_video.project import Project, WorkflowError, file_hash, validate_config
from helpers import approve, fixture, prepare_images, prepare_audio, prepare_plans
from scripts import stream_render as stream


class PenTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def call(self, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(list(args))
        data = json.loads(output.getvalue())
        self.assertEqual(code, 0, data)
        return data["result"]

    def test_list_is_read_only_and_bundled_assets_have_transparency(self):
        listing = self.call("pen", "list")["pens"]
        self.assertEqual([p["id"] for p in listing], ["marker", "fountain"])
        self.assertEqual([p["reveal_radius"] for p in listing], [4, 2])
        for item in listing:
            with Image.open(item["image"]) as image:
                self.assertEqual(image.mode, "RGBA")
                self.assertEqual(image.getextrema()[3], (0, 255))
            hand, mask = stream._load_hand(Path(item["image"]), 180)
            self.assertEqual(hand.shape[0], 180)
            # The upper-left nib must contact the drawing point after cropping.
            self.assertTrue((mask[:5, :5] > .1).any())

    def test_selection_updates_native_renderer_and_invalidates_old_preview_inputs(self):
        p = prepare_plans(prepare_audio(prepare_images(fixture(self.base))))
        before = w.scene_inputs(p, "scene-001")
        old_style = w.style_target(p)
        result = self.call("pen", "set", "--project", str(p.root), "--type", "fountain")
        p = Project(p.root)
        self.assertTrue(result["approval_required"])
        self.assertNotEqual(old_style, w.style_target(p))
        self.assertNotEqual(before, w.scene_inputs(p, "scene-001"))
        self.assertEqual(p.hash("style/drawing-hand.png"), file_hash(pens.hand_path("fountain")))
        p.data["config"]["bare_tip"] = False
        renderer = media.native_renderer(p, "scene-001", p.load("scenes/scene-001/annotation.json"))
        self.assertEqual(renderer.cfg.pen_type, "fountain")
        self.assertEqual(renderer.cfg.pen_reveal_radius, 2)
        expected, _ = stream._load_hand(pens.hand_path("fountain"), renderer.tip.h)
        np.testing.assert_array_equal(renderer.tip.hand, expected)
        self.call("pen", "set", "--project", str(p.root), "--type", "marker")
        p = Project(p.root)
        self.assertEqual(p.data["config"]["pen_type"], "marker")
        self.assertEqual(p.hash("style/drawing-hand.png"), file_hash(pens.hand_path("marker")))

    def test_legacy_projects_keep_marker_and_unknown_type_is_rejected(self):
        p = fixture(self.base)
        p.data["config"].pop("pen_type")
        p.persist()
        self.assertNotIn("pen_type", Project(p.root).data["config"])
        self.assertEqual(bridge.Config().pen_reveal_radius, 4)
        with self.assertRaises(ValueError):
            bridge.Config(pen_type="invalid")
        with self.assertRaises(WorkflowError):
            validate_config({**p.data["config"], "pen_type": "invalid"})
        with self.assertRaises(WorkflowError):
            validate_config({**p.data["config"], "render_engine": "remotion", "fps": 30, "pen_type": "fountain"})

    def test_fountain_strokes_are_finer_and_still_finish_the_full_mask(self):
        source = np.full((100, 100, 3), 255, np.uint8)
        source[15:85, 15:85] = [60, 90, 150]
        annotation = {"canvas": {"width": 100, "height": 100}, "elements": []}
        allowed = np.zeros((100, 100), bool)
        allowed[15:85, 15:85] = True
        allowed[42:58, 42:58] = False
        areas = []
        class Writer:
            count = 0
            def write(self, frame):
                self.count += 1
        for kind in ("marker", "fountain"):
            renderer = bridge.RegionStreamRenderer(source, annotation, bridge.Config(
                cap_long_edge=100, canvas_hex="#FFFFFF", pen_type=kind), None, True)
            renderer._reveal_color_segment((25, 30), (65, 30), allowed)
            areas.append(np.any(renderer.drawn != 255, axis=2).sum())
            writer = Writer()
            renderer._wash_subject(writer, 60, allowed)
            self.assertEqual(writer.count, 60)
            np.testing.assert_array_equal(renderer.drawn[allowed], renderer.color_img_float[allowed])
            self.assertTrue(np.all(renderer.drawn[~allowed] == 255))
        self.assertGreater(areas[0], areas[1])

    def test_custom_preset_restores_pen_type_and_builtin_style_preserves_selection(self):
        with patch.object(styles, "LIBRARY_DIR", self.base / "library"):
            source = prepare_images(fixture(self.base / "source"))
            self.call("pen", "set", "--project", str(source.root), "--type", "fountain")
            source = Project(source.root)
            approve(source, "style")
            saved = self.call("style", "save", "--project", str(source.root), "--name", "钢笔测试")
            target = fixture(self.base / "target")
            approve(target, "storyboard")
            self.call("style", "set", "--project", str(target.root), "--preset", saved["id"])
            target = Project(target.root)
            self.assertEqual(target.data["config"]["pen_type"], "fountain")
            self.assertEqual(target.hash("style/drawing-hand.png"), file_hash(pens.hand_path("fountain")))
            # Marker-only branding must not replace the selected fountain hand.
            target.data["config"]["pen_text"] = "测试"
            target.persist()
            self.call("style", "set", "--project", str(target.root), "--preset", bridge.presets()[0]["id"])
            target = Project(target.root)
            self.assertEqual(target.data["config"]["pen_type"], "fountain")
            self.assertEqual(target.hash("style/drawing-hand.png"), file_hash(pens.hand_path("fountain")))

    def test_both_standalone_clis_accept_fountain_and_custom_hand_override(self):
        from scripts import stream_render as stream
        from scripts import render_stream_whiteboard as region
        stream_args = stream._parse_args(["image.png", "--pen-type", "fountain", "--pen-image", "custom.png"])
        region_args = region._parse_args(["image.png", "ann.json", "out.mp4", "custom.png", "--pen-type", "fountain"])
        self.assertEqual(stream._build_cfg(stream_args).pen_reveal_radius, 2)
        self.assertEqual(region._build_cfg(region_args).pen_reveal_radius, 2)
        self.assertEqual(stream_args.pen_image, "custom.png")
        self.assertEqual(region_args.hand, "custom.png")


if __name__ == "__main__":
    unittest.main()
