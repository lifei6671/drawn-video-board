"""Gray warm comic style and optional boy identity stay separate through prompt generation."""
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from PIL import Image

from cs_board_video import bridge, styles, workflow as w
from cs_board_video.cli import dispatch, parser
from cs_board_video.project import WorkflowError, file_hash
from helpers import approve, fixture


STYLE_ID = "builtin-gray-warm-comic"
STYLE_NAME = "灰调暖光漫画风"
STYLE_HASH = "2805b8af7369db9152fe04737f4c56b3de648129f0ef45d8aa15ec1a234b131d"
BOY_HASH = "c509464a1e93468949e3e73dcb824b6f5964aef8dde2e5af467d4d8e9ba2029a"
BOY_ROOT = bridge.ROOT / "assets/character-references/gray-warm-boy"
REPO = Path(__file__).parents[1]


class GrayWarmComicStyleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch.object(styles, "LIBRARY_DIR", Path(self.temp.name) / "styles")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.p = fixture(self.temp.name)
        approve(self.p, "storyboard")

    def invoke(self, *args):
        return dispatch(self.p, parser().parse_args([*args, "--project", str(self.p.root)]))

    def prompts(self):
        approve(self.p, "style")
        self.p.data["image_mode"] = "manual"
        approve(self.p, "image_mode")
        bridge.prompts(self.p)
        return self.p.load("scenes/scene-001/prompt-context.json")

    def test_separate_assets_are_packaged_and_recorded(self):
        selected = styles.select(STYLE_ID)
        self.assertEqual(selected, styles.select(STYLE_NAME))
        self.assertEqual(selected["source"], "builtin")
        self.assertTrue(selected["use_as_reference"])
        config = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
        packaged = config["tool"]["setuptools"]["package-data"]["cs_board_video"]
        manifest = json.loads((REPO / "references/upstream-manifest.json").read_text(encoding="utf-8"))
        additions = {entry["path"]: entry for entry in manifest["additions"]}
        for path in (Path(selected["image_path"]), BOY_ROOT / "turnaround.png", BOY_ROOT / "character.json"):
            self.assertIn(path.relative_to(REPO / "cs_board_video").as_posix(), packaged)
            self.assertEqual(file_hash(path), additions[path.relative_to(bridge.ROOT).as_posix()]["sha256"])
        for path, expected in ((Path(selected["image_path"]), STYLE_HASH), (BOY_ROOT / "turnaround.png", BOY_HASH)):
            self.assertEqual(file_hash(path), expected)
            with Image.open(path) as sample:
                self.assertEqual(sample.size, (1536, 1024))
                sample.verify()

    def test_style_selection_does_not_add_boy_identity(self):
        result = self.invoke("style", "set", "--preset", STYLE_ID)
        self.assertTrue(result["approval_required"])
        self.assertEqual(self.p.data["config"]["canvas_hex"], "#F7F5EF")
        self.assertFalse(self.p.data["visual_references"].get("characters"))
        with self.assertRaises(WorkflowError):
            w.style_ready(self.p)
        context = self.prompts()
        self.assertEqual(context["style"], STYLE_NAME)
        self.assertEqual([self.p.hash(path) for path in context["references"]], [STYLE_HASH])
        prompt = self.p.path("scenes/scene-001/prompt.md").read_text(encoding="utf-8")
        self.assertIn(styles.select(STYLE_ID)["recipe"], prompt)
        self.assertNotIn("短发男生", prompt)

    def test_opt_in_boy_is_independent_and_survives_style_switch(self):
        self.invoke("style", "set", "--preset", STYLE_ID)
        self.prompts()
        previous = w.style_target(self.p)
        character = json.loads((BOY_ROOT / "character.json").read_text(encoding="utf-8"))
        self.assertLessEqual(len(character["description"]), 80)
        self.invoke("asset", "--source", str(BOY_ROOT / "turnaround.png"), "--dest", character["images"][0])
        self.p.data["visual_references"]["characters"] = [character]
        self.p.persist()
        self.assertNotEqual(w.style_target(self.p), previous)
        with self.assertRaises(WorkflowError):
            w.style_ready(self.p)
        context = self.prompts()
        self.assertEqual([self.p.hash(path) for path in context["references"]], [STYLE_HASH, BOY_HASH])
        prompt = self.p.path("scenes/scene-001/prompt.md").read_text(encoding="utf-8")
        self.assertIn("输入图1是唯一的画面风格参考", prompt)
        self.assertIn("输入图2共同定义人物“短发男生”", prompt)
        self.assertIn(character["description"], prompt)
        self.invoke("style", "set", "--preset", "builtin-warm-chibi-story")
        self.assertEqual(self.p.data["visual_references"]["characters"], [character])
        context = self.prompts()
        self.assertEqual(self.p.hash(context["references"][1]), BOY_HASH)
        self.assertNotEqual(self.p.hash(context["references"][0]), STYLE_HASH)

    def test_web_renaming_keeps_only_style_reference(self):
        with bridge.project_context(self.p) as module:
            snapshot = module.update_style(STYLE_ID, {"name": "灰调暖光测试"})
            self.assertEqual(snapshot["image_url"], "/styles/gray-warm-comic.png")
            for name in (STYLE_NAME, "灰调暖光测试"):
                paths, instruction = module.builtin_style_reference_context(name)
                self.assertEqual([file_hash(path) for path in paths], [STYLE_HASH])
                scene = {"elements": ["园丁", "盆栽"], "text": "园丁给盆栽浇水。"}
                prompt = module.build_board_prompt([scene], name, instruction)
                self.assertIn(module.STYLE_PRESETS[STYLE_NAME], prompt)
                self.assertIn("园丁给盆栽浇水", prompt)
                self.assertNotIn("短发男生", prompt)
