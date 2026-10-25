"""Reusable style contracts; all approvals and images are isolated test fixtures."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from cs_board_video import bridge, styles, workflow as w
from cs_board_video.cli import main
from cs_board_video.project import Project, WorkflowError, file_hash, file_lock
from helpers import approve, fixture


class StyleLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.library = self.base / "shared-styles"
        patcher = patch.object(styles, "LIBRARY_DIR", self.library)
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, *args, code=0):
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(list(args))
        data = json.loads(output.getvalue())
        self.assertEqual(result, code, data)
        return data.get("result") if code == 0 else data

    def project(self, name, reference=True):
        p = fixture(self.base / name, name=name)
        approve(p, "storyboard")
        p.save("style/style.json", {"name": "自定义测试画风", "recipe": "黑色清晰轮廓，红色点缀，背景留白"})
        shutil.copyfile(bridge.ROOT / "assets/drawing-hand-clean.png", p.path("style/drawing-hand.png"))
        if reference:
            # A non-default filename proves explicit references reach the prompt bridge.
            Image.effect_noise((128, 128), 64).convert("RGB").save(p.path("style/mood.png"))
            p.data["visual_references"] = {"style_image": "style/mood.png"}
        p.data["config"]["canvas_hex"] = "#EEE8D5"
        p.persist()
        approve(p, "style")
        return p

    def test_list_without_project_before_storyboard_is_read_only(self):
        result = self.call("style", "list")
        self.assertEqual(len(result["presets"]), 17)
        self.assertTrue(all(item["source"] == "builtin" for item in result["presets"]))
        self.assertFalse(self.library.exists())
        p = fixture(self.base, name="new-project")
        before = p.path("project.json").read_bytes()
        self.call("style", "list", "--project", str(p.root))
        self.assertEqual(p.path("project.json").read_bytes(), before)

    def test_save_select_and_generate_prompts_after_source_is_gone(self):
        source = self.project("source")
        source.data["visual_references"]["characters"] = [{"id": "old", "name": "旧主角", "images": ["style/mood.png"]}]
        source.persist()
        approve(source, "style")
        source_approval = deepcopy(source.approvals)
        ref_hash = source.hash("style/mood.png")
        saved = self.call("style", "save", "--project", str(source.root), "--name", "暖纸漫画")
        self.assertEqual(Project(source.root).approvals, source_approval)
        listing = self.call("style", "list")["presets"]
        self.assertEqual(len(listing), 18)
        self.assertEqual(listing[-1]["id"], saved["id"])
        self.assertEqual(file_hash(Path(listing[-1]["image_path"])), ref_hash)
        # Remove only this test's source project to prove the library owns its assets.
        shutil.rmtree(source.root)
        target = fixture(self.base / "target", name="target")
        approve(target, "storyboard")
        Image.effect_noise((128, 128), 64).convert("RGB").save(target.path("characters/references/hero.png"))
        hero = {"id": "hero", "name": "新主角", "description": "测试人物", "images": ["characters/references/hero.png"]}
        target.data["visual_references"] = {"characters": [hero]}
        target.persist()
        result = self.call("style", "set", "--project", str(target.root), "--preset", "暖纸漫画")
        target = Project(target.root)
        self.assertTrue(result["approval_required"])
        self.assertEqual(target.data["config"]["canvas_hex"], "#EEE8D5")
        self.assertEqual(target.load("style/style.json")["name"], "暖纸漫画")
        self.assertNotIn("preset", target.load("style/style.json"))
        self.assertEqual(target.data["visual_references"]["characters"], [hero])
        self.assertEqual(file_hash(styles.reference_path(target)), ref_hash)
        self.assertTrue(styles.reference_path(target).is_relative_to(target.root))
        with self.assertRaises(WorkflowError):
            w.style_ready(target)
        approve(target, "style")
        self.call("image-mode", "set", "--project", str(target.root), "--choice", "manual")
        target = Project(target.root)
        approve(target, "image_mode")
        self.call("images", "prompts", "--project", str(target.root))
        prompt = target.path("scenes/scene-001/prompt.md").read_text(encoding="utf-8")
        self.assertIn("暖纸漫画", prompt)
        with bridge.project_context(target) as module:
            self.assertEqual(module.style_recipe(bridge.style_name(target, module)), "黑色清晰轮廓，红色点缀，背景留白")
        self.assertIn("唯一的画面风格参考", prompt)
        self.assertIn("新主角", prompt)
        self.assertNotIn("旧主角", prompt)
        self.assertEqual(len(target.load("scenes/scene-001/prompt-context.json")["references"]), 2)

    def test_replace_keeps_existing_project_snapshot_and_requires_flag(self):
        source = self.project("source")
        saved = self.call("style", "save", "--project", str(source.root))
        target = self.project("target", reference=False)
        self.call("style", "set", "--project", str(target.root), "--preset", saved["id"])
        target = Project(target.root)
        approve(target, "style")
        previous = w.style_target(target)
        library_before = (self.library / "library.json").read_bytes()
        source.save("style/style.json", {"name": "自定义测试画风", "recipe": "新的蓝色线稿"})
        Image.effect_noise((128, 128), 30).convert("RGB").save(source.path("style/mood.png"))
        source.data["config"]["canvas_hex"] = "#FFFFFF"
        source.persist()
        approve(source, "style")
        failure = self.call("style", "save", "--project", str(source.root), code=2)
        self.assertIn("--replace", failure["error"])
        self.assertEqual((self.library / "library.json").read_bytes(), library_before)
        replaced = self.call("style", "save", "--project", str(source.root), "--replace")
        self.assertEqual(replaced["id"], saved["id"])
        self.assertEqual(w.style_target(target), previous)
        w.style_ready(target)
        self.call("style", "set", "--project", str(target.root), "--preset", saved["id"])
        target = Project(target.root)
        self.assertEqual(target.load("style/style.json")["recipe"], "新的蓝色线稿")
        self.assertEqual(target.data["config"]["canvas_hex"], "#FFFFFF")
        self.assertNotEqual(w.style_target(target), previous)
        with self.assertRaises(WorkflowError):
            w.style_ready(target)

    def test_text_only_and_builtin_selection_disable_old_reference_without_deleting_it(self):
        source = self.project("text-only", reference=False)
        saved = self.call("style", "save", "--project", str(source.root))
        self.call("image-mode", "set", "--project", str(source.root), "--choice", "manual")
        source = Project(source.root)
        approve(source, "image_mode")
        self.call("images", "prompts", "--project", str(source.root))
        self.assertIn("黑色清晰轮廓", source.path("scenes/scene-001/prompt.md").read_text(encoding="utf-8"))
        target = self.project("target")
        shutil.copyfile(target.path("style/mood.png"), target.path("style/reference.png"))
        old_hash = target.hash("style/reference.png")
        for value in (saved["id"], bridge.presets()[0]["id"]):
            self.call("style", "set", "--project", str(target.root), "--preset", value)
            target = Project(target.root)
            self.assertIsNone(styles.reference_path(target))
            with bridge.project_context(target) as module:
                refs, _, _ = module.custom_reference_context(target.root.name, require_characters=False)
                self.assertEqual(refs, [])
            self.assertEqual(target.hash("style/reference.png"), old_hash)

    def test_legacy_default_reference_and_detailed_recipe_are_saved(self):
        from helpers import STYLE
        p = self.project("legacy")
        p.save("style/style.json", STYLE)
        shutil.copyfile(p.path("style/mood.png"), p.path("style/reference.png"))
        p.data.pop("visual_references")
        p.persist()
        approve(p, "style")
        saved = self.call("style", "save", "--project", str(p.root))
        record = styles.select(saved["id"])
        self.assertIn("lines: 深灰线", record["recipe"])
        self.assertEqual(file_hash(Path(record["image_path"])), p.hash("style/reference.png"))

    def test_explicit_reference_import_reactivates_reference_after_preset_switch(self):
        p = self.project("source")
        self.call("style", "set", "--project", str(p.root), "--preset", bridge.presets()[0]["id"])
        custom = p.path("style/custom.json")
        custom.write_text(json.dumps({"name": "新参考风格", "recipe": "清晰线稿"}), encoding="utf-8")
        self.call("style", "set", "--project", str(p.root), "--file", str(custom))
        p = Project(p.root)
        self.assertIsNone(styles.reference_path(p))
        # Explicit import overrides the previous disabled value, including normalized paths.
        self.call("asset", "--project", str(p.root), "--source", str(p.path("style/mood.png")),
                  "--dest", "./style/reference.png")
        p = Project(p.root)
        self.assertEqual(styles.reference_path(p), p.path("style/reference.png"))
        approve(p, "style")
        saved = self.call("style", "save", "--project", str(p.root))
        self.assertEqual(file_hash(Path(styles.select(saved["id"])["image_path"])), p.hash("style/mood.png"))
        self.call("image-mode", "set", "--project", str(p.root), "--choice", "manual")
        p = Project(p.root)
        approve(p, "image_mode")
        self.call("images", "prompts", "--project", str(p.root))
        references = p.load("scenes/scene-001/prompt-context.json")["references"]
        self.assertEqual(len(references), 1)
        self.assertEqual(p.hash(references[0]), p.hash("style/mood.png"))

    def test_invalid_assets_and_unapproved_styles_do_not_publish(self):
        p = self.project("source")
        p.path("style/mood.png").unlink()
        self.call("style", "save", "--project", str(p.root), code=4)
        approve(p, "style")
        self.call("style", "save", "--project", str(p.root), code=2)
        self.assertFalse((self.library / "library.json").exists())

    def test_invalid_library_asset_does_not_mutate_target(self):
        source = self.project("source")
        saved = self.call("style", "save", "--project", str(source.root))
        path = self.library / "library.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        target = self.project("target")
        previous = w.style_target(target)
        for value in ("../outside.png", "assets/missing.png"):
            data["presets"][saved["id"]]["reference"] = value
            path.write_text(json.dumps(data), encoding="utf-8")
            self.call("style", "set", "--project", str(target.root), "--preset", saved["id"], code=2)
            self.assertEqual(w.style_target(Project(target.root)), previous)

    def test_library_lock_prevents_simultaneous_save_and_releases(self):
        p = self.project("source")
        lock_path = styles.library_path("library.lock")
        script = ("from pathlib import Path; from cs_board_video import styles; from cs_board_video.cli import main; "
                  "import sys; styles.LIBRARY_DIR=Path(sys.argv[1]); "
                  "sys.exit(main(['style','save','--project',sys.argv[2]]))")
        with file_lock(lock_path, "test lock"):
            result = subprocess.run([sys.executable, "-c", script, str(self.library), str(p.root)],
                                    capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
            self.assertIn("预设库正在保存", json.loads(result.stdout)["error"])
        self.assertFalse((self.library / "library.json").exists())
        self.call("style", "save", "--project", str(p.root))

    def test_preset_canvas_only_update_invalidates_target_approval(self):
        source = self.project("source")
        saved = self.call("style", "save", "--project", str(source.root))
        target = self.project("target")
        self.call("style", "set", "--project", str(target.root), "--preset", saved["id"])
        target = Project(target.root)
        approve(target, "style")
        source.data["config"]["canvas_hex"] = "#FFFFFF"
        source.persist()
        approve(source, "style")
        self.call("style", "save", "--project", str(source.root), "--replace")
        self.call("style", "set", "--project", str(target.root), "--preset", saved["id"])
        target = Project(target.root)
        with self.assertRaises(WorkflowError):
            w.style_ready(target)
        self.assertEqual(target.data["config"]["canvas_hex"], "#FFFFFF")

    def test_builtin_name_collision_is_rejected(self):
        p = self.project("source")
        name = bridge.presets()[0]["name"]
        self.call("style", "save", "--project", str(p.root), "--name", name, code=2)
        self.assertFalse((self.library / "library.json").exists())
