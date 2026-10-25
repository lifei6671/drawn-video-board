"""User-approved builtin style, actual reference routing and packaging contracts."""
from contextlib import ExitStack
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


STYLE_ID = "builtin-warm-chibi-story"
STYLE_NAME = "暖色Q版叙事漫画风"
IMAGE_SHA256 = "d8b61b0b36cdf00817d3ad8b63f300744c9cb0b36a554f1948ea5742262ab8c3"
REPO = Path(__file__).parents[1]


def invoke(p, *args):
    return dispatch(p, parser().parse_args([*args, "--project", str(p.root)]))


class GenerationCaptured(BaseException):
    """Stop at the provider boundary before any real generation or API call."""


class WarmChibiStyleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch.object(styles, "LIBRARY_DIR", Path(self.temp.name) / "styles")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.p = fixture(self.temp.name)
        approve(self.p, "storyboard")

    def select(self, name=STYLE_NAME):
        result = invoke(self.p, "style", "set", "--preset", name)
        self.assertTrue(result["approval_required"])
        return self.p

    def test_builtin_listing_original_image_and_package_manifest(self):
        selected = styles.select(STYLE_ID)
        self.assertEqual(selected["name"], STYLE_NAME)
        self.assertEqual(selected["source"], "builtin")
        self.assertTrue(selected["use_as_reference"])
        self.assertIn("分区上色", selected["recipe"])
        self.assertIn("封闭色块", selected["recipe"])
        image = Path(selected["image_path"])
        self.assertEqual(file_hash(image), IMAGE_SHA256)
        with Image.open(image) as supplied:
            self.assertGreater(supplied.width, 1000)
            self.assertGreater(supplied.height, 500)
            supplied.verify()
        config = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
        relative = image.relative_to(REPO / "cs_board_video").as_posix()
        self.assertIn(relative, config["tool"]["setuptools"]["package-data"]["cs_board_video"])
        manifest = json.loads((REPO / "references/upstream-manifest.json").read_text(encoding="utf-8"))
        added = next(item for item in manifest["additions"] if item["path"] == "web/public/styles/warm-chibi-story.png")
        self.assertEqual(added["sha256"], IMAGE_SHA256)

    def test_selected_preview_is_reference_and_requires_approval(self):
        p = self.select(STYLE_ID)
        self.assertEqual(p.load("style/style.json")["preset"], STYLE_ID)
        self.assertEqual(p.load("style/style.json")["recipe"], styles.select(STYLE_ID)["recipe"])
        self.assertEqual(p.data["config"]["canvas_hex"], "#FFF7D6")
        self.assertEqual(styles.reference_path(p), p.path("style/preset-preview.png"))
        self.assertEqual(p.hash("style/preset-preview.png"), IMAGE_SHA256)
        with self.assertRaises(WorkflowError):
            w.style_ready(p)
        approve(p, "style")
        w.style_ready(p)

    def test_every_scene_gets_project_local_reference_and_full_recipe(self):
        p = self.select()
        approve(p, "style")
        p.data["image_mode"] = "manual"
        approve(p, "image_mode")
        bridge.prompts(p)
        context = p.load("scenes/scene-001/prompt-context.json")
        self.assertEqual(context["style"], STYLE_NAME)
        self.assertEqual(len(context["references"]), 1)
        self.assertEqual(p.hash(context["references"][0]), IMAGE_SHA256)
        prompt = p.path("scenes/scene-001/prompt.md").read_text(encoding="utf-8")
        self.assertIn(p.load("style/style.json")["recipe"], prompt)
        self.assertIn("不得被替换", prompt)
        self.assertNotIn("同一主角固定为：中国青年男性", prompt)
        before = w.style_target(p)
        p.path("style/preset-preview.png").write_bytes(b"invalid replacement")
        self.assertNotEqual(w.style_target(p), before)
        with self.assertRaises(WorkflowError):
            w.style_ready(p)

    def test_story_identities_and_character_references_take_priority(self):
        module = bridge.server()
        scene = {"title": "修理机器人", "concept": "女孩学习修理", "elements": ["女孩", "机器人"], "text": "女孩学会修理机器人。"}
        _, instruction = module.builtin_style_reference_context(STYLE_NAME)
        for prompt in (module.build_board_prompt([scene], STYLE_NAME, instruction),
                       module.build_board_prompt([scene], STYLE_NAME, instruction, infographic=True),
                       module.build_image_prompt(scene, STYLE_NAME)):
            self.assertIn("女孩", prompt)
            self.assertIn(module.STYLE_PRESETS[STYLE_NAME], prompt)
            self.assertNotIn("同一主角固定为：中国青年男性", prompt)
        prompt = module.build_board_prompt([scene], STYLE_NAME, instruction + "输入图2定义女孩。", True)
        self.assertIn("只使用人物参考组中定义的角色", prompt)
        self.assertIn("输入图2定义女孩", prompt)

    def test_existing_project_keeps_recipe_and_reference_until_reselected(self):
        module = bridge.server()
        current_recipe = module.STYLE_PRESETS[STYLE_NAME]
        old_recipe = "旧版暖色漫画配方，保留丰富背景细节和层次光影。"
        old_image = Path(self.temp.name) / "old-reference.png"
        Image.new("RGB", (128, 72), "wheat").save(old_image, compress_level=0)
        with patch.dict(module.STYLE_PRESETS, {STYLE_NAME: old_recipe}), \
                patch.object(module, "builtin_style_image_path", return_value=old_image):
            p = self.select(STYLE_ID)
        approve(p, "style")
        p.data["image_mode"] = "manual"
        approve(p, "image_mode")
        approved_style = w.style_target(p)

        bridge.prompts(p)
        prompt = p.path("scenes/scene-001/prompt.md").read_text(encoding="utf-8")
        self.assertIn(old_recipe, prompt)
        self.assertNotIn(current_recipe, prompt)
        context = p.load("scenes/scene-001/prompt-context.json")
        self.assertEqual(p.hash(context["references"][0]), file_hash(old_image))
        self.assertEqual(w.style_target(p), approved_style)
        w.style_ready(p)
        self.assertEqual(styles.select(STYLE_ID)["recipe"], current_recipe)

        self.select(STYLE_ID)
        self.assertEqual(p.load("style/style.json")["recipe"], current_recipe)
        self.assertEqual(p.hash("style/preset-preview.png"), IMAGE_SHA256)
        with self.assertRaises(WorkflowError):
            w.style_ready(p)
        approve(p, "style")
        approve(p, "image_mode")
        bridge.prompts(p)
        prompt = p.path("scenes/scene-001/prompt.md").read_text(encoding="utf-8")
        self.assertIn(current_recipe, prompt)
        self.assertNotIn(old_recipe, prompt)

    def test_reference_fallback_is_opt_in_and_missing_asset_fails(self):
        module = bridge.server()
        self.assertEqual(module.builtin_style_reference_context(module.DEFAULT_STYLE), ([], ""))
        paths, _ = module.builtin_style_reference_context(STYLE_NAME)
        self.assertEqual(file_hash(paths[0]), IMAGE_SHA256)
        with patch.object(module, "builtin_style_image_path", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "参考图缺失"):
                module.builtin_style_reference_context(STYLE_NAME)

    def test_web_initial_and_regeneration_send_builtin_image_to_provider(self):
        p = self.p
        p.save("plan.json", bridge.native_scenes(p))
        with bridge.project_context(p) as module, ExitStack() as stack:
            module.JOBS[p.root.name]["style"] = STYLE_NAME
            stack.enter_context(patch.object(module, "load_config", return_value={}))
            stack.enter_context(patch.object(module, "probe_duration", return_value=2))
            stack.enter_context(patch.object(module, "begin_phase"))
            stack.enter_context(patch.object(module, "update_job"))
            generator = stack.enter_context(patch.object(module, "generate_image", side_effect=GenerationCaptured))
            # The editor submits the saved full prompt, with any user edits.
            edited_prompt = module.build_board_prompt(bridge.native_scenes(p), STYLE_NAME) + "\n突出人物动作。"
            for operation in (lambda: module.model_stage(p.root.name, "人物递出物品。", STYLE_NAME, p.path("unused.wav"), 1, "", False, False, "detailed"),
                              lambda: module.regenerate_board_image(p.root.name, 1, edited_prompt)):
                with self.assertRaises(GenerationCaptured):
                    operation()
                references = generator.call_args.args[3]
                self.assertEqual(len(references), 1)
                self.assertEqual(file_hash(references[0]), IMAGE_SHA256)
                self.assertIn(module.STYLE_PRESETS[STYLE_NAME], generator.call_args.args[1])
            self.assertEqual(generator.call_args.args[1], edited_prompt)

    def test_renamed_builtin_keeps_reference_recipe_and_story_characters(self):
        p = self.p
        with bridge.project_context(p) as module:
            module.update_style(STYLE_ID, {"name": "暖色故事新名称"})
            for name in (STYLE_NAME, "暖色故事新名称"):
                paths, instruction = module.builtin_style_reference_context(name)
                self.assertEqual(file_hash(paths[0]), IMAGE_SHA256)
                self.assertEqual(module.builtin_style_definition(name)["id"], STYLE_ID)
                scene = {"elements": ["女孩"], "text": "女孩修理机器人。"}
                for prompt in (module.build_board_prompt([scene], name, instruction),
                               module.build_image_prompt(scene, name)):
                    self.assertIn(module.STYLE_PRESETS[STYLE_NAME], prompt)
                    self.assertIn("不得被替换", prompt)
                    self.assertNotIn("同一主角固定为：中国青年男性", prompt)

    def test_standalone_original_and_renamed_style_send_reference_and_recipe(self):
        with bridge.project_context(self.p) as module, ExitStack() as stack:
            module.update_style(STYLE_ID, {"name": "独立生图新名称"})
            stack.enter_context(patch.object(module, "load_config", return_value={}))
            stack.enter_context(patch.object(module, "image_provider_config", return_value={"api_key": "test-fixture"}))
            generator = stack.enter_context(patch.object(module, "generate_image", side_effect=GenerationCaptured))
            for name in (STYLE_NAME, "独立生图新名称"):
                with self.assertRaises(GenerationCaptured):
                    module.generate_standalone_image({"prompt": "女孩修理机器人。", "style_name": name})
                references = generator.call_args.kwargs["reference_images"]
                self.assertEqual(len(references), 1)
                self.assertEqual(file_hash(references[0]), IMAGE_SHA256)
                self.assertIn(module.STYLE_PRESETS[STYLE_NAME], generator.call_args.args[1])
                generator.reset_mock()
