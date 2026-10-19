"""JSON CLI protocol. Every project command holds one OS-backed lock."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

from . import media, workflow as w
from .project import Project, WorkflowError, file_hash, initialize, now, read_json, require


def parser():
    cli = argparse.ArgumentParser(description="drawn-video-board 人工审核手绘视频工作流")
    commands = cli.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="环境与可选本地语音接口检查")
    doctor.add_argument("--voice-url")
    init = commands.add_parser("init", help="创建 content/<name> 项目")
    init.add_argument("--name", required=True)
    init.add_argument("--script", required=True)
    init.add_argument("--content", default="content")
    init.add_argument("--config", help="初始项目配置 JSON")
    for name in ("status", "resume", "render", "compose", "validate", "approve", "review", "revise", "asset"):
        sub = commands.add_parser(name)
        sub.add_argument("--project", required=True)
        if name == "render":
            selection = sub.add_mutually_exclusive_group(required=True)
            selection.add_argument("--all", action="store_true")
            selection.add_argument("--scene")
        if name in ("approve", "review", "revise"):
            sub.add_argument("--stage", required=True, choices=("storyboard", "style", "image_mode", "audio", "preview"))
            sub.add_argument("--scene")
        if name == "approve":
            sub.add_argument("--digest", required=True)
            sub.add_argument("--user-message", required=True)
        if name == "revise":
            sub.add_argument("--feedback", required=True)
        if name == "asset":
            sub.add_argument("--source", required=True)
            sub.add_argument("--dest", required=True)
            sub.add_argument("--replace", action="store_true")
    for group, actions in {"storyboard": ("validate", "import", "request", "adapt"), "deck": ("request", "adapt"), "style": ("set", "list"),
                           "image-mode": ("set",), "images": ("validate", "review", "digest", "prompts", "fit", "key-text"),
                           "audio": ("import", "synthesize", "verify", "align"), "timeline": ("build",),
                           "annotation": ("build", "preview", "import"), "preview": ("render", "compose")}.items():
        sub = commands.add_parser(group)
        actions_parser = sub.add_subparsers(dest="action", required=True)
        for action in actions:
            leaf = actions_parser.add_parser(action)
            leaf.add_argument("--project", required=True)
            if (group, action) in (("storyboard", "import"), ("storyboard", "adapt"), ("annotation", "import")):
                leaf.add_argument("--file", required=True)
            if group == "deck" and action == "adapt":
                leaf.add_argument("--file", required=True)
            if group == "storyboard" and action in ("request", "adapt"):
                leaf.add_argument("--duration", type=float, required=True)
                leaf.add_argument("--narrative-only", action="store_true")
            if (group, action) == ("style", "set"):
                style_input = leaf.add_mutually_exclusive_group(required=True)
                style_input.add_argument("--file")
                style_input.add_argument("--preset")
            if group == "image-mode":
                leaf.add_argument("--choice", choices=("agent", "manual"), required=True)
            if group == "images" and action in ("review", "digest"):
                leaf.add_argument("--scene", required=True)
            if group == "images" and action in ("fit", "key-text"):
                leaf.add_argument("--scene")
            if group == "images" and action == "review":
                leaf.add_argument("--digest", required=True)
                leaf.add_argument("--evidence", required=True)
            if group == "audio" and action == "import":
                leaf.add_argument("--source", required=True)
                leaf.add_argument("--content-evidence", required=True)
            if group == "audio" and action == "verify":
                leaf.add_argument("--digest", required=True)
                leaf.add_argument("--content-evidence", required=True)
            if group == "audio" and action == "align":
                leaf.add_argument("--tokens")
            if group == "annotation":
                leaf.add_argument("--scene")
            if group == "preview" and action == "render":
                leaf.add_argument("--scene")
                leaf.add_argument("--resolution", default="960x540")
    return cli


def asset_import(p, source, dest, replace=False):
    output = p.path(dest)
    protected = [p.path(name) for name in ("project.json", "approvals.json", "narration/original.txt", "render/command.lock")]
    require(output not in protected, "不能用 asset 覆盖项目状态、审核、锁或原文")
    source = Path(source).resolve()
    require(source.is_file(), "源文件不存在")
    require(not output.exists() or replace, "目标已存在；替换需显式 --replace")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Preserve both previous and new originals by byte identity before replacement.
    originals = p.path("render/cache/imports")
    originals.mkdir(parents=True, exist_ok=True)
    for path in (output, source):
        if path.is_file():
            preserved = originals / (file_hash(path) + path.suffix)
            if not preserved.exists():
                shutil.copyfile(path, preserved)
    if source != output:
        shutil.copyfile(source, output)
    return {"path": dest, "sha256": file_hash(output)}


def dispatch(p, a):
    c, action = a.command, getattr(a, "action", None)
    if getattr(a, "scene", None):
        p.scene(a.scene)
    if c == "status":
        return w.status(p)
    if c == "resume":
        return w.resume(p)
    if c == "asset":
        return asset_import(p, a.source, a.dest, a.replace)
    if c == "storyboard":
        if action in ("request", "adapt"):
            from .bridge import plan
            return plan(p, a.duration, read_json(Path(a.file)) if action == "adapt" else None,
                        narrative_only=a.narrative_only)
        if action == "import":
            data = read_json(Path(a.file))
            # Validate in memory before replacing the current storyboard.
            original_scenes = p.scenes
            p.scenes = lambda: data.get("scenes", [])
            try:
                w.validate_storyboard(p)
            finally:
                p.scenes = original_scenes
            p.save("narration/storyboard.json", data)
        return w.validate_storyboard(p)
    if c == "deck":
        from .bridge import plan
        return plan(p, 0, read_json(Path(a.file)) if action == "adapt" else None, deck_only=True)
    if c == "style":
        w.board_ready(p)
        from .bridge import presets, project_context
        if action == "list":
            return {"presets": presets()}
        if a.preset:
            definition = next((item for item in presets() if item["id"] == a.preset), None)
            require(definition, "未知原画风预设")
            data = {"name": definition["name"], "preset": definition["id"], "recipe": definition["recipe"]}
            asset_import(p, definition["image_path"], "style/preset-preview" + Path(definition["image_path"]).suffix, True)
        else:
            data = read_json(Path(a.file))
        p.save("style/style.json", data)
        from .bridge import ROOT
        hand = ROOT / "assets/drawing-hand-clean.png"
        if not p.path("style/drawing-hand.png").exists():
            require(hand.exists(), "安装包未包含绘制手模板；请从 Skill assets 导入")
            shutil.copyfile(hand, p.path("style/drawing-hand.png"))
        if p.data["config"].get("pen_text"):
            with project_context(p) as module:
                module.make_branded_hand(p.data["config"]["pen_text"], p.path("style/drawing-hand.png"))
        return {"digest": w.style_target(p), "approval_required": True}
    if c == "image-mode":
        w.style_ready(p)
        p.data["image_mode"] = a.choice
        p.persist()
        return {"choice": a.choice, "digest": w.mode_target(p), "approval_required": True}
    if c == "images":
        if action == "prompts":
            from .bridge import prompts
            return prompts(p)
        if action in ("fit", "key-text"):
            w.mode_ready(p)
            from .bridge import project_context
            changed = []
            for index, scene in enumerate(p.scenes()):
                sid = scene["scene_id"]
                if a.scene and a.scene != sid:
                    continue
                image = p.path(f"scenes/{sid}/image.png")
                original = p.path(f"scenes/{sid}/image.source.png")
                require(image.is_file(), f"{sid} 缺少图片")
                if not original.exists():
                    shutil.copyfile(image, original)
                if action == "fit":
                    import math
                    c = p.data["config"]; divisor = math.gcd(c["width"], c["height"])
                    with project_context(p) as module:
                        module.fit_image_to_aspect(image, f"{c['width']//divisor}:{c['height']//divisor}")
                else:
                    from scripts.add_key_text import add_key_text
                    fitted = p.path(f"scenes/{sid}/image.fitted.png")
                    shutil.copyfile(original, fitted)
                    import math
                    config = p.data["config"]; divisor = math.gcd(config["width"], config["height"])
                    with project_context(p) as module:
                        module.fit_image_to_aspect(fitted, f"{config['width']//divisor}:{config['height']//divisor}")
                    phrases = [str(panel.get("key_text") or panel.get("title", "")) for panel in scene.get("upstream_panels", [])]
                    if not phrases:
                        phrases = [scene.get("key_text") or scene.get("upstream", {}).get("key_text") or scene["narrative_goal"]]
                    add_key_text(fitted, phrases, image)
                changed.append(sid)
            return {"changed": changed, "visual_review_required": True}
        if action == "validate":
            return w.validate_images(p)
        if action == "digest":
            return {"digest": w.image_target(p, a.scene)}
        return w.review_image(p, a.scene, a.digest, a.evidence)
    if c == "audio":
        if action == "align":
            w.audio_ready(p)
            if a.tokens:
                return asset_import(p, a.tokens, "audio/alignment.tokens.json", True)
            import os
            from .bridge import ROOT
            cache = p.path("render/cache/whisper")
            cache.mkdir(parents=True, exist_ok=True)
            media.run(["node", ROOT / "video_renderer/align.mjs", p.path("audio/voice.wav"),
                       p.path("audio/alignment.tokens.json")], cwd=ROOT / "video_renderer",
                      env={**os.environ, "CS_BOARD_CACHE_DIR": str(cache)})
            return {"tokens": "audio/alignment.tokens.json", "producer": "upstream.align.mjs"}
        if action == "import":
            return w.import_audio(p, a.source, a.content_evidence)
        if action == "verify":
            require(a.digest == w.audio_target(p), "配音版本已改变，请重新试听")
            metadata = p.load("audio/metadata.json", {})
            require(metadata and a.content_evidence.strip(), "缺少音频或检查证据")
            metadata["content_evidence"] = a.content_evidence
            p.save("audio/metadata.json", metadata)
            return {"digest": w.audio_target(p)}
        w.images_ready(p)
        from .adapters.voicestudio import synthesize
        source, provenance = synthesize(p)
        result = w.import_audio(p, source, "待实际试听与文案比对", generated=True)
        metadata = p.load("audio/metadata.json")
        metadata.update(provenance)
        metadata["content_evidence"] = None
        p.save("audio/metadata.json", metadata)
        result["digest"] = w.audio_target(p)
        return result
    if c == "timeline":
        return w.timeline_build(p)
    if c == "annotation":
        if action == "build":
            return w.annotation_build(p, a.scene)
        changed = []
        from .bridge import ROOT
        for scene in p.scenes():
            sid = scene["scene_id"]
            if a.scene and sid != a.scene:
                continue
            if action == "import":
                require(a.scene, "从编辑台导入标注时必须指定 --scene")
                annotation = read_json(Path(a.file))
                w.annotation_validate(p, sid, annotation)
                asset_import(p, a.file, f"scenes/{sid}/annotation.json", True)
            else:
                w.annotation_ready(p, sid)
                image = p.path(f"scenes/{sid}/image.png")
                annotation = p.path(f"scenes/{sid}/annotation.json")
                media.run([sys.executable, ROOT / "scripts/render_annotation_preview.py", image,
                           annotation, p.path(f"scenes/{sid}/annotation-preview.png")])
                shutil.copyfile(annotation, p.path(f"scenes/{sid}/image.annotation.json"))
            changed.append(sid)
        editor = p.path("previews/editor.html")
        shutil.copyfile(ROOT / "assets/preview.html", editor)
        return {"scenes": changed, "editor": str(editor), "producer": "upstream annotation preview/editor"}
    if c == "review":
        return {"stage": a.stage, "scene": a.scene,
                "digest": w.approval_target(p, a.stage, a.scene),
                "instruction": "向用户展示实际产物；仅收到明确确认后执行 approve"}
    if c == "approve":
        return w.approve(p, a.stage, a.digest, a.user_message, a.scene)
    if c == "revise":
        require(a.feedback.strip(), "修改反馈不能为空")
        key = a.stage + (":" + a.scene if a.stage == "storyboard" and a.scene else "")
        keys = [key]
        if a.stage == "storyboard" and not a.scene:
            keys = ["storyboard:" + s["scene_id"] for s in p.scenes()]
        for key in keys:
            p.approvals.pop(key, None)
        p.data["revision"] = {"stage": a.stage, "scene": a.scene, "feedback": a.feedback, "at": now()}
        p.persist()
        return w.status(p)
    if c == "preview":
        if action == "compose":
            return w.compose(p, True)
        try:
            width, height = (int(x) for x in a.resolution.split("x"))
        except (ValueError, AttributeError) as error:
            raise WorkflowError("预览分辨率格式: 960x540") from error
        require(min(width, height) >= 100 and width % 2 == 0 and height % 2 == 0,
                "预览宽高必须为偶数且至少 100")
        return w.render(p, True, a.scene, [width, height])
    if c == "render":
        return w.render(p, False, a.scene)
    if c == "compose":
        return w.compose(p, False)
    if c == "validate":
        return w.validate_final(p)
    raise WorkflowError("未知命令")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    a = parser().parse_args(argv)
    project = None
    try:
        if a.command == "doctor":
            result = media.doctor(a.voice_url)
            voice = result["voicestudio"]
            voice_ok = not isinstance(voice, dict) or voice.get("status") == "PASS"
            code = 0 if result["ffmpeg"] and result["ffprobe"] and voice_ok else 3
        elif a.command == "init":
            project = initialize(a.content, a.name, a.script, read_json(Path(a.config)) if a.config else None)
            result = {"project": str(project.root), "state": "script_ready"}
            code = 0
        else:
            project = Project(a.project)
            with project.lock():
                try:
                    result = dispatch(project, a)
                    if a.command not in ("status", "review", "revise"):
                        project.data.pop("last_error", None)
                        project.persist()
                except Exception as error:
                    error_code = error.code if isinstance(error, WorkflowError) else 5
                    if error_code in (3, 5):
                        project.data["state"] = "failed"
                    project.data["last_error"] = {"command": a.command, "message": str(error),
                                                  "code": error_code, "at": now()}
                    project.persist()
                    raise
            code = 0
        print(json.dumps({"ok": code == 0, "result": result}, ensure_ascii=False))
        return code
    except (WorkflowError, OSError, ValueError, KeyError, TypeError) as error:
        code = error.code if isinstance(error, WorkflowError) else 2
        print(json.dumps({"ok": False, "code": code, "error": str(error)}, ensure_ascii=False))
        return code
    except Exception as error:
        # CLI execution boundary: preserve a structured failure instead of exit 1.
        print(json.dumps({"ok": False, "code": 5, "error": str(error)}, ensure_ascii=False))
        return 5
