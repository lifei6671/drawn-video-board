"""Bind project resources to the migrated CS Board functions.

Business algorithms live in upstream/. This module only maps paths and schemas.
"""
from __future__ import annotations

from contextlib import contextmanager
import importlib
import os
from pathlib import Path
import shutil
import sys
import threading
from copy import deepcopy

from .project import require, file_hash

ROOT = Path(__file__).parent / "upstream"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.render_stream_whiteboard import RegionStreamRenderer
from scripts.stream_render import Config, _imread_any

_scope_lock = threading.RLock()


def server():
    # Upstream restores and starts pending jobs at import; Skill must never do so.
    previous = os.environ.get("CS_BOARD_HEADLESS")
    os.environ["CS_BOARD_HEADLESS"] = "1"
    try:
        return importlib.import_module("cs_board_video.upstream.webapp.server")
    finally:
        if previous is None:
            os.environ.pop("CS_BOARD_HEADLESS", None)
        else:
            os.environ["CS_BOARD_HEADLESS"] = previous


@contextmanager
def project_context(p):
    """Original helpers use module paths; serialize their project-local binding."""
    with _scope_lock:
        module = server()
        folder = p.path("render/upstream")
        folder.mkdir(parents=True, exist_ok=True)
        pronunciation = p.path("audio/pronunciation.yaml")
        if not pronunciation.exists():
            shutil.copyfile(ROOT / "pronunciation.yaml", pronunciation)
        references = deepcopy(p.data.get("visual_references", {}))
        for character in references.get("characters", []):
            for image in character.get("images", []):
                p.path(image)
        if references.get("style_image"):
            p.path(references["style_image"])
        values = {"ROOT": ROOT, "STATE_DIR": folder, "JOBS_DIR": p.root.parent,
                  "STYLES_DIR": p.path("style/library"), "STYLES_PATH": p.path("style/library.json"),
                  "VOICES_DIR": p.path("audio/original"), "CONFIG_PATH": folder / "config.json",
                  "PRONUNCIATION_PATH": pronunciation, "HAND": p.path("style/drawing-hand.png"),
                  "JOBS": {p.root.name: {"id": p.root.name, "status": "preparing",
                            "reference_mode": "custom" if p.path("style/reference.png").exists() else "standard",
                            "visual_references": references}}}
        if p.path("style/reference.png").exists():
            values["JOBS"][p.root.name]["visual_references"].setdefault("style_image", "style/reference.png")
        saved = {name: getattr(module, name) for name in values}
        for name, value in values.items():
            setattr(module, name, value)
        try:
            yield module
        finally:
            for name, value in saved.items():
                setattr(module, name, value)


def style_name(p, module):
    style = p.load("style/style.json", {})
    preset = style.get("preset")
    if preset:
        require(preset in module.BUILTIN_STYLE_BY_ID, "未知上游画风预设")
        return module.BUILTIN_STYLE_BY_ID[preset]["name"]
    name = style.get("name", module.DEFAULT_STYLE)
    if name not in module.STYLE_PRESETS:
        recipe = style.get("recipe") or "；".join(f"{k}: {v}" for k, v in style.items() if k != "name")
        module.save_custom_styles([{"id": "project-style", "name": name,
                                   "description": "本项目确认的画风", "recipe": recipe}])
    return name


def native_scenes(p):
    result = []
    for scene in p.scenes():
        native = dict(scene.get("upstream", {}))
        native.setdefault("text", scene["narration"])
        native.setdefault("title", scene.get("title") or scene["narrative_goal"])
        native.setdefault("concept", scene["narrative_goal"])
        native.setdefault("elements", [str(x) for x in scene["drawing_order"]])
        native.setdefault("key_text", scene.get("key_text", ""))
        native.setdefault("duration_ms", round(scene["estimated_duration"] * 1000))
        result.append(native)
    return result


def presets():
    module = server()
    return [{**item, "recipe": module.STYLE_PRESETS[item["name"]],
             "image_path": str(module.builtin_style_image_path(item))}
            for item in module.BUILTIN_STYLE_DEFINITIONS]


def prompts(p):
    """Original style, composition and character prompts, without API generation."""
    from . import workflow as w
    w.mode_ready(p)
    generated = []
    infographic = p.data["config"].get("render_engine") == "remotion"
    deck = p.load("render/deck-plan.json") if infographic else None
    require(not deck or len(deck) == len(p.scenes()), "原 PPT 页面数量与分镜不一致")
    with project_context(p) as module:
        style = style_name(p, module)
        refs, instruction, characters = module.custom_reference_context(p.root.name, require_characters=False)
        for index, (scene, native) in enumerate(zip(p.scenes(), native_scenes(p))):
            sid = scene["scene_id"]
            if infographic:
                # Before narration is aligned, the approved narrative already names its subjects.
                # Map that original standard-scene field to the original infographic prompt schema.
                native = deck[index] if deck else {**native, "illustration_elements":
                    native.get("illustration_elements") or native.get("nodes") or native["elements"]}
            selected, reference_instruction = refs, instruction
            if not refs and style == module.PAPER_METAPHOR_STYLE:
                selected, reference_instruction = module.paper_metaphor_reference_context([native])
            elif not refs and style == module.OIL_VISUAL_STYLE:
                selected, reference_instruction = module.oil_visual_reference_context([native],
                    p.data["config"].get("render_engine") == "remotion")
            local_refs = []
            for source in selected:
                destination = p.path(f"style/references/{file_hash(source)[:16]}-{source.name}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                if source.resolve() != destination and not destination.exists():
                    shutil.copyfile(source, destination)
                local_refs.append(destination.relative_to(p.root).as_posix())
            from math import gcd
            divisor = gcd(p.data["config"]["width"], p.data["config"]["height"])
            aspect = f"{p.data['config']['width']//divisor}:{p.data['config']['height']//divisor}"
            require(aspect in module.ASPECT_RATIO_SPECS, "原项目支持 16:9、9:16、1:1")
            panels = scene.get("upstream_panels") or [native]
            prompt = module.build_board_prompt(panels, style, reference_instruction, bool(characters),
                       p.data["config"].get("render_engine") == "remotion", aspect)
            p.path(f"scenes/{sid}/prompt.md").write_text(prompt, encoding="utf-8")
            p.save(f"scenes/{sid}/prompt-context.json", {"upstream_function": "build_board_prompt",
                   "style": style, "references": local_refs, "panels": panels})
            generated.append(sid)
    return {"prompts": generated, "producer": "upstream.webapp.server.build_board_prompt"}


def plan(p, duration, candidate=None, *, narrative_only=False, deck_only=False):
    """Original request/normalization; Codex supplies the model response, not new planning code."""
    copy = p.path("narration/original.txt").read_text(encoding="utf-8-sig")
    infographic = p.data["config"].get("render_engine") == "remotion" and not narrative_only
    require(not deck_only or infographic, "deck 仅用于原 Remotion 分支")
    phrases = None
    if infographic:
        from .workflow import audio_ready
        audio_ready(p)
        from scripts.semantic_timeline import build_phrase_timeline
        tokens = p.load("audio/alignment.tokens.json")
        require(tokens, "原动态 PPT 规划需要真实语音词边界；先做叙事分镜时使用 --narrative-only，配音后用 deck request/adapt")
        from .media import duration as audio_duration
        duration = audio_duration(p.path("audio/voice.wav"))
        phrases = build_phrase_timeline(copy, tokens, round(duration * 1000), fps=30)
    with project_context(p) as module:
        style = style_name(p, module) if infographic else module.DEFAULT_STYLE
        if candidate is None:
            request = module.plan_request(copy, duration, style, infographic=infographic, phrase_timeline=phrases)
            path = "render/deck-request.json" if deck_only else "narration/plan-request.json"
            p.save(path, request)
            return {"request": path, "producer": "upstream.plan_request", "infographic": infographic}
        native = module.make_plan(module.DEFAULT_CONFIG, copy, duration, style,
                    infographic=infographic, phrase_timeline=phrases, candidate_response=candidate)
    if deck_only:
        require(infographic, "deck 仅用于原 Remotion 分支")
        require(len(native) == len(p.scenes()), "PPT 页数改变了批准的分镜，需先修改并重新确认分镜")
        from scripts.semantic_timeline import _normalized
        require(all(_normalized(page["text"]) == _normalized(scene["narration"])
                    for page, scene in zip(native, p.scenes())), "PPT 内容分组改变了批准的叙事，需先修改并重新确认分镜")
        p.save("render/deck-plan.json", native)
        return {"plan": "render/deck-plan.json", "producer": "upstream.make_plan/normalize_deck_pages"}
    scenes = [{"scene_id": f"scene-{i:03}", "narration": item["text"],
               "narrative_goal": item.get("concept") or item["title"],
               "visual_description": "；".join(item["elements"]), "composition": item.get("composition") or "按原分镜构图",
               "subjects": item["elements"], "drawing_order": item["elements"],
               "estimated_duration": item["duration_ms"] / 1000, "transition": "cut", "upstream": item}
              for i, item in enumerate(native, 1)]
    p.save("narration/storyboard.json", {"scenes": scenes})
    from .workflow import validate_storyboard
    return validate_storyboard(p)
