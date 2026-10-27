"""Approval gates and dependency-based incremental production."""
from __future__ import annotations

import math
from pathlib import Path
import re
import shutil

from . import media, rolls
from .project import WorkflowError, digest, file_hash, now, read_json, require


def normalize(text):
    return re.sub(r"\s+", "", text.lstrip("\ufeff"))


def validate_storyboard(p):
    from . import typography, direction
    scenes = p.scenes()
    require(scenes and len(scenes) <= 999, "请先创建 narration/storyboard.json")
    fields = ("scene_id", "narration", "narrative_goal", "visual_description", "composition",
              "subjects", "drawing_order", "estimated_duration", "transition")
    for i, scene in enumerate(scenes, 1):
        require(isinstance(scene, dict) and all(scene.get(k) for k in fields), f"第 {i} 镜缺少必填字段")
        typography.validate_scene(scene, p.data["config"])
        direction.validate(scene)
        require(scene["scene_id"] == f"scene-{i:03}", "镜头必须连续编号 scene-001 起")
        require(isinstance(scene["narration"], str) and isinstance(scene["drawing_order"], list), "分镜字段类型错误")
        require(isinstance(scene["estimated_duration"], (float, int)) and math.isfinite(scene["estimated_duration"])
                and scene["estimated_duration"] > 0, "预估时长必须为正数秒")
        require(scene["transition"] == "cut", "v1 仅支持 cut 硬切转场，请在分镜中明确")
    rolls.validate(scenes, p.data["config"].get("render_engine", "whiteboard"))
    original = p.path("narration/original.txt").read_text(encoding="utf-8-sig")
    require(normalize("".join(s["narration"] for s in scenes)) == normalize(original),
            "分镜口播必须按顺序完整覆盖原文，不得遗漏、改写或重复")
    report = {"passed": True, "scene_count": len(scenes), "script_sha256": p.hash("narration/original.txt")}
    p.save("reports/storyboard-validation.json", report)
    for scene in scenes:
        p.path(f"scenes/{scene['scene_id']}").mkdir(exist_ok=True)
    return report


def board_target(p, scene):
    from . import typography
    return digest({"scene": scene, "script": p.hash("narration/original.txt"),
                   **({"a_scene": p.scene(rolls.anchor(p,scene['scene_id']))} if rolls.anchor(p,scene['scene_id']) else {}),
                   **({"typography": typography.inputs(p)} if scene.get("visual_text") else {})})


def board_ready(p):
    validate_storyboard(p)
    for scene in p.scenes():
        p.need_approval("storyboard:" + scene["scene_id"], board_target(p, scene))
    from . import typography
    typography.ready(p)


def style_target(p):
    config = p.load("style/style.json", {})
    references = p.data.get("visual_references", {})
    files = [references["style_image"]] if references.get("style_image") else []
    files += [path for character in references.get("characters", []) for path in character.get("images", [])]
    return digest({"style": config, "reference": p.hash("style/reference.png"),
                   "hand": p.hash("style/drawing-hand.png"), "characters": references,
                   "reference_files": {path: p.hash(path) for path in files}})


def style_ready(p):
    board_ready(p)
    validate_style(p)
    p.need_approval("style", style_target(p))


def validate_style(p):
    style = p.load("style/style.json", {})
    if style.get("preset"):
        from .bridge import server
        require(style["preset"] in server().BUILTIN_STYLE_BY_ID, "未知原画风预设")
    else:
        require(style.get("name") and (style.get("recipe") or all(style.get(k) for k in
            ("lines", "palette", "proportions", "shading", "texture", "composition", "complexity"))), "画风配置缺少原画风配方或视觉字段")
    require(p.hash("style/drawing-hand.png"), "请先导入项目绘制手模板")


def mode_target(p):
    return digest({"mode": p.data.get("image_mode"), "style": style_target(p)})


def mode_ready(p):
    style_ready(p)
    require(p.data.get("image_mode") in ("agent", "manual"), "请选择 agent/manual 生图方式", 4)
    p.need_approval("image_mode", mode_target(p))


def image_target(p, scene_id):
    source_id = rolls.image_scene(p,scene_id)
    return digest({"image": p.hash(f"scenes/{source_id}/image.png"), "scene": p.scene(scene_id),
                   **({"reused_image": image_target(p,source_id)} if source_id != scene_id else {}),
                   "style": style_target(p), "mode": mode_target(p),
                   "prompt": p.hash(f"scenes/{scene_id}/prompt.md")})


VISUAL_CHECKS = ("story_match", "character_consistency", "style_consistency", "drawable")


def review_image(p, scene_id, expected, evidence):
    mode_ready(p)
    actual = image_target(p, scene_id)
    require(expected == actual, "图片版本已改变，请重新查看")
    require(evidence.strip(), "必须提供实际看图后的逐项视觉检查证据")
    media.image_info(rolls.image_path(p,scene_id))
    p.save(f"scenes/{scene_id}/image-metadata.json", {
        "digest": actual, "reviewer": "agent", "evidence": evidence,
        "checks": dict.fromkeys(VISUAL_CHECKS, "PASS"), "at": now(),
        "source": p.data["image_mode"], "prompt_sha256": p.hash(f"scenes/{scene_id}/prompt.md")})
    return {"scene_id": scene_id, "digest": actual, "visual_review": "PASS"}


def validate_images(p):
    mode_ready(p)
    p.data["state"] = "images_validating"
    p.persist()
    rows = []
    config = p.data["config"]
    for scene in p.scenes():
        sid = scene["scene_id"]
        row = {"scene_id": sid, "digest": image_target(p, sid), "errors": []}
        try:
            source_id = rolls.image_scene(p,sid)
            info = media.image_info(rolls.image_path(p,sid))
            row.update(info)
            require(min(info["width"], info["height"]) >= 64, "源图短边至少为 64 像素")
            row["upscale_required"] = info["width"] < config["width"] or info["height"] < config["height"]
            require(abs(info["width"] / info["height"] - config["width"] / config["height"]) < .01,
                    "图片比例与项目画幅不符")
            require(info["contrast_std"] >= 3 or p.scene(source_id).get("visual_mode") == "text_only", "图片接近空白，需检查线条")
            require(p.hash(f"scenes/{sid}/prompt.md"), "缺少实际使用的 prompt.md")
            metadata = p.load(f"scenes/{source_id}/image-metadata.json", {})
            require(metadata.get("digest") == image_target(p,source_id) and
                    all(metadata.get("checks", {}).get(k) == "PASS" for k in VISUAL_CHECKS),
                    "缺少当前版本的视觉检查；先查看图片再执行 images review")
        except WorkflowError as error:
            row["errors"].append(str(error))
        row["passed"] = not row["errors"]
        rows.append(row)
    report = {"passed": all(r["passed"] for r in rows), "scenes": rows}
    p.save("reports/image-validation.json", report)
    if not report["passed"]:
        p.data["state"] = "images_pending"
        p.persist()
        raise WorkflowError("图片验收未通过，请查看 reports/image-validation.json")
    p.receipt("images", image_validation_inputs(p), ["reports/image-validation.json"])
    return report


def images_ready(p):
    mode_ready(p)
    require(p.fresh("images", image_validation_inputs(p)), "图片验收缺失或已失效，请重新验收")
    for scene in p.scenes():
        source_id = rolls.image_scene(p,scene['scene_id'])
        metadata = p.load(f"scenes/{source_id}/image-metadata.json", {})
        require(metadata.get("digest") == image_target(p,source_id) and
                all(metadata.get("checks", {}).get(k) == "PASS" for k in VISUAL_CHECKS),
                "图片视觉检查已失效")


def image_validation_inputs(p):
    return digest({"images": [image_target(p, s["scene_id"]) for s in p.scenes()],
                   "width": p.data["config"]["width"], "height": p.data["config"]["height"]})


def audio_target(p):
    return digest({"voice": p.hash("audio/voice.wav"), "metadata": p.load("audio/metadata.json", {}),
                   "script": p.hash("narration/original.txt")})


def audio_ready(p):
    images_ready(p)
    metadata = p.load("audio/metadata.json", {})
    require(p.hash("audio/voice.wav") and metadata.get("voice_sha256") == p.hash("audio/voice.wav"),
            "音频缺失或已被替换，请重新导入/合成")
    require(metadata.get("script_sha256") == p.hash("narration/original.txt"), "口播已改变，需要重新校验配音")
    require(metadata.get("content_evidence"), "缺少音频内容与口播匹配检查")
    if metadata["source"] == "generated":
        p.need_approval("audio", audio_target(p))


def import_audio(p, source, evidence, generated=False):
    images_ready(p)
    require(evidence.strip(), "必须提供实际试听或转录比对证据")
    source = Path(source).resolve()
    require(source.is_file(), "音频源文件不存在")
    preserved = p.path(f"audio/original/{file_hash(source)}{source.suffix.lower()}")
    if not preserved.exists():
        shutil.copyfile(source, preserved)
    media.normalize_audio(preserved, p.path("audio/voice.wav"))
    p.save("audio/metadata.json", {"source": "generated" if generated else "user",
           "original": preserved.relative_to(p.root).as_posix(), "content_evidence": evidence,
           "script_sha256": p.hash("narration/original.txt"), "voice_sha256": p.hash("audio/voice.wav"),
           "duration": media.duration(p.path("audio/voice.wav")), "at": now()})
    return {"audio": "audio/voice.wav", "digest": audio_target(p),
            "approval_required": generated}


def timeline_inputs(p):
    return digest({"audio": audio_target(p), "scenes": p.scenes(), "fps": p.data["config"]["fps"],
                   "alignment": p.hash("audio/alignment.json"), "tokens": p.hash("audio/alignment.tokens.json"),
                   "engine": p.data["config"].get("render_engine", "whiteboard"), "upstream": engine_hash(),
                   "remotion_visuals": {"style": p.hash("style/style.json"), "subtitles": p.data["config"]["subtitles"],
                       "deck": p.hash("render/deck-plan.json")} if p.data["config"].get("render_engine") == "remotion" else None})


def timeline_build(p):
    audio_ready(p)
    inputs = timeline_inputs(p)
    if p.fresh("timeline", inputs):
        return {"cached": True, "timeline": p.load("render/timeline.json")}
    fps = p.data["config"]["fps"]
    seconds = media.duration(p.path("audio/voice.wav"))
    frames = round(seconds * fps)
    require(frames >= len(p.scenes()) * fps, "每镜至少需要一秒，当前配音过短")
    alignment = p.load("audio/alignment.json")
    from .bridge import native_scenes, project_context, ROOT
    scenes = p.scenes()
    native = p.load("render/deck-plan.json") if p.data["config"].get("render_engine") == "remotion" else None
    native = native or native_scenes(p)
    rows = []
    elapsed = 0
    method = "upstream-fit-scene-durations"
    if p.data["config"].get("render_engine") == "remotion":
        tokens = p.load("audio/alignment.tokens.json")
        require(tokens, "动态信息图必须先使用原 align.mjs 生成实际词边界，禁止比例估计")
        from scripts.semantic_timeline import build_phrase_timeline, build_deck_timeline
        copy = p.path("narration/original.txt").read_text(encoding="utf-8-sig")
        phrases = build_phrase_timeline(copy, tokens, round(seconds * 1000), fps=fps)
        native, report = build_deck_timeline(copy, native, phrases, round(seconds * 1000), fps=fps)
        require(len(native) == len(scenes), "原 PPT 页面数量与批准的分镜不一致，请重新审核分镜")
        p.save("render/phrase-timeline.json", phrases)
        p.save("reports/alignment-report.json", report)
        method = phrases["timing_source"]
    elif not alignment:
        with project_context(p) as module:
            module.fit_scene_durations(native, seconds)
    if p.data["config"].get("render_engine") == "remotion":
        alignment = None
    if alignment:
        require(len(alignment.get("scenes", [])) == len(scenes), "对齐数据镜头数不匹配")
    for index, scene in enumerate(scenes):
        if alignment:
            item = alignment["scenes"][index]
            require(item["scene_id"] == scene["scene_id"] and abs(item["start_ms"] * fps / 1000 - elapsed) < 1,
                    "对齐数据必须按镜头顺序连续覆盖音频")
            end = round(item["end_ms"] * fps / 1000)
        else:
            end = native[index].get("end_frame") if p.data["config"].get("render_engine") == "remotion" else (
                frames if index == len(scenes) - 1 else elapsed + round(native[index]["duration_ms"] * fps / 1000))
        require(end - elapsed >= fps, "每镜时长至少一秒")
        rows.append({"scene_id": scene["scene_id"], "start_frame": elapsed, "end_frame": end,
                     "duration_ms": (end - elapsed) * 1000 / fps})
        native[index]["duration_ms"] = round((end - elapsed) * 1000 / fps)
        elapsed = end
    require(abs(elapsed - frames) <= 1, "对齐时间轴未覆盖完整音频")
    result = {"fps": fps, "audio_seconds": seconds, "frames": elapsed, "scenes": rows,
              "alignment_method": "provided" if alignment else method,
              "timing_requires_preview_review": True}
    p.save("render/timeline.json", result)
    p.save("render/upstream-scenes.json", native)
    with project_context(p) as module:
        module.write_subtitles(native, p.path("audio/subtitles.srt"))
        if p.data["config"].get("render_engine") == "remotion":
            width, height = p.data["config"]["width"], p.data["config"]["height"]
            divisor = math.gcd(width, height)
            props = module.remotion_infographic_props(native, p.load("style/style.json")["name"],
                        round(seconds * 1000), p.data["config"]["subtitles"], f"{width//divisor}:{height//divisor}")
            p.save("render/remotion-props.json", props)
    outputs = ["render/timeline.json", "render/upstream-scenes.json", "audio/subtitles.srt"]
    if p.data["config"].get("render_engine") == "remotion":
        outputs += ["render/phrase-timeline.json", "reports/alignment-report.json", "render/remotion-props.json"]
    p.receipt("timeline", inputs, outputs)
    return result


def timeline_ready(p):
    audio_ready(p)
    require(p.fresh("timeline", timeline_inputs(p)), "时间轴不存在或已失效")


def row_for(p, sid):
    return next(s for s in p.load("render/timeline.json")["scenes"] if s["scene_id"] == sid)


def annotation_inputs(p, sid):
    return digest({"image": image_target(p, sid), "timing": row_for(p, sid),
                   "plan": p.hash(f"scenes/{sid}/drawing-plan.json")})


def annotation_validate(p, sid, annotation):
    from .upstream.scripts.render_stream_whiteboard import validate_subject_contours, validate_drawing_layers
    try:
        validate_subject_contours(annotation)
        validate_drawing_layers(annotation)
    except ValueError as error:
        raise WorkflowError(str(error)) from error
    info = media.image_info(rolls.image_path(p,sid))
    if "layers" in annotation:
        media.layer_images(p, sid, annotation)
    require(annotation.get("canvas") == {"width": info["width"], "height": info["height"]}, "标注画布必须等于原图尺寸")
    require(abs(annotation.get("sceneDurationMs", 0) - row_for(p, sid)["duration_ms"]) < .01, "标注时长与时间轴不符")
    elements = annotation.get("elements", [])
    if rolls.static(p,sid):
        require(elements == [] and "layers" not in annotation, "直接展示或返回镜头不应包含绘制元素或新图层")
        return
    require(elements, "标注必须包含实际看图确定的元素")
    ids = set()
    end = 0
    for index, element in enumerate(elements, 1):
        require(element.get("id") not in ids and element.get("id"), "绘制对象编号必须唯一")
        ids.add(element["id"])
        require(element.get("sequence") == index and element.get("narrativeRole") and element.get("subtitle"),
                "标注必须包含连续 sequence、narrativeRole 和 subtitle")
        rectangles = [element["region"]] + element["reveal"].get("protectedRegions", [])
        for r in rectangles:
            require(all(type(r.get(k)) is int for k in ("x", "y", "width", "height")), "标注区域必须是整数像素")
            require(r["x"] >= 0 and r["y"] >= 0 and r["width"] > 0 and r["height"] > 0
                    and r["x"] + r["width"] <= info["width"] and r["y"] + r["height"] <= info["height"], "绘制区域越界")
        reveal = element["reveal"]
        require(all(isinstance(reveal[k], (int, float)) and math.isfinite(reveal[k]) for k in ("startMs", "durationMs")), "绘制时间必须是有限数字")
        require(reveal["startMs"] >= end and reveal["durationMs"] >= 1000 / p.data["config"]["fps"] * 3,
                "单笔画时段过短或时间重叠")
        end = reveal["startMs"] + reveal["durationMs"]
    require(end <= annotation["sceneDurationMs"] - 499, "结尾必须保留至少 0.5 秒完整画面")


def annotation_build(p, selected=None):
    timeline_ready(p)
    from .bridge import project_context
    changed = []
    for index, scene in enumerate(p.scenes()):
        sid = scene["scene_id"]
        if selected and sid != selected:
            continue
        if rolls.static(p,sid):
            info = media.image_info(rolls.image_path(p,sid))
            result = {"sceneId":sid,"canvas":{"width":info["width"],"height":info["height"]},
                      "sceneDurationMs":row_for(p,sid)["duration_ms"],"elements":[]}
            path = f"scenes/{sid}/annotation.json"
            if p.fresh("annotation:"+sid,annotation_inputs(p,sid)):
                continue
            annotation_validate(p,sid,result)
            p.save(path,result)
            p.receipt("annotation:"+sid,annotation_inputs(p,sid),[path])
            changed.append(sid)
            continue
        plan = p.load(f"scenes/{sid}/drawing-plan.json", {})
        require(not plan or (plan.get("image_sha256") == p.hash(f"scenes/{sid}/image.png") and plan.get("visual_evidence")),
                f"{sid} 需要基于当前图片的 drawing-plan.json 和实际看图证据")
        inputs = annotation_inputs(p, sid)
        entry = p.data.get("receipts", {}).get("annotation:" + sid, {})
        if entry.get("inputs") == inputs and p.path(f"scenes/{sid}/annotation.json").exists():
            annotation_validate(p, sid, p.load(f"scenes/{sid}/annotation.json"))
            continue
        native = dict(p.load("render/upstream-scenes.json")[index])
        overrides = plan.get("elements", [])
        if overrides:
            native["elements"] = [e.get("label") or e["id"] for e in overrides]
        image = p.path(f"scenes/{sid}/image.png")
        draft = p.path(f"scenes/{sid}/annotation.upstream.json")
        with project_context(p) as module:
            if scene.get("upstream_panels"):
                panels = [dict(panel) for panel in scene["upstream_panels"]]
                module.fit_scene_durations(panels, native["duration_ms"] / 1000)
                module.write_board_annotation(panels, image, draft, index + 1)
                result = read_json(draft)
                result["elements"][-1]["reveal"]["durationMs"] -= 500
            else:
                module.write_annotation(native, image, draft, index + 1)
                result = read_json(draft)
                # Retain original gaps/durations; move its initial 200ms pause to the final hold.
                for element in result["elements"]:
                    element["reveal"]["startMs"] -= 200
        result["sceneId"] = sid
        result["sceneDurationMs"] = row_for(p, sid)["duration_ms"]
        if "layers" in plan:
            result["layers"] = plan["layers"]
        if overrides:
            require(len(overrides) == len(result["elements"]), "分镜面板和人工区域数量不匹配")
            for element, override in zip(result["elements"], overrides):
                element.update({k: v for k, v in override.items() if k not in ("reveal", "weight", "protectedRegions")})
                element["reveal"]["protectedRegions"] = override.get("protectedRegions", [])
                element["reveal"].update(override.get("reveal", {}))
                r = element["region"]
                element["handPath"] = {"start": [r["x"], r["y"]],
                    "end": [r["x"] + r["width"], r["y"] + r["height"]], "easing": "easeInOut"}
        annotation_validate(p, sid, result)
        path = f"scenes/{sid}/annotation.json"
        p.save(path, result)
        p.receipt("annotation:" + sid, inputs, [path])
        changed.append(sid)
    return {"built": changed}


def drawing_config(p):
    excluded = ("crf",) if p.data["config"].get("render_engine") == "remotion" else ("crf", "subtitles")
    return {k: v for k, v in p.data["config"].items() if k not in excluded}


def scene_inputs(p, sid):
    from . import typography
    remotion = None
    if p.data["config"].get("render_engine") == "remotion":
        props = p.load("render/remotion-props.json", {})
        index = next(i for i, s in enumerate(p.scenes()) if s["scene_id"] == sid)
        remotion = {k: v for k, v in props.items() if k not in ("pages", "totalDurationFrames", "totalDurationMs")}
        remotion["page"] = props.get("pages", [])[index]
    return digest({"scene": image_target(p, sid), "annotation": p.hash(f"scenes/{sid}/annotation.json"),
                   **({"a_scene": scene_inputs(p,rolls.anchor(p,sid))} if rolls.anchor(p,sid) else {}),
                   "timing": row_for(p, sid), "drawing": drawing_config(p),
                   "engine": engine_hash(), "hand": p.hash("style/drawing-hand.png"), "remotion": remotion,
                   "layers": media.layer_asset_hashes(p, sid, p.load(f"scenes/{sid}/annotation.json", {})),
                   **({"typography": typography.inputs(p), "text_engine": file_hash(Path(__file__).with_name("text_render.py"))}
                      if p.scene(sid).get("visual_text") else {})})


def engine_hash():
    from .bridge import ROOT
    files = ("scripts/stream_render.py", "scripts/render_stream_whiteboard.py", "scripts/fountain_pen.py",
             "scripts/sweety_line_topology.py", "scripts/sweety_stroke_paths.py", "scripts/semantic_timeline.py",
             "scripts/merge_scenes.py", "scripts/add_key_text.py", "webapp/server.py",
             "video_renderer/render.mjs", "video_renderer/src/video.tsx")
    return digest({**{name: file_hash(ROOT / name) for name in files},
                   "rolls":file_hash(Path(__file__).with_name("rolls.py")),
                   "media":file_hash(Path(__file__).with_name("media.py"))})


def annotation_ready(p, sid):
    timeline_ready(p)
    annotation = p.load(f"scenes/{sid}/annotation.json", {})
    require(p.data.get("receipts", {}).get("annotation:" + sid, {}).get("inputs") == annotation_inputs(p, sid),
            f"{sid} 标注源已改变，请重新构建")
    # Direct timing/order edits are allowed but must pass schema and new preview review.
    annotation_validate(p, sid, annotation)
    return annotation


def preview_inputs(p):
    return digest({"scenes": [scene_inputs(p, s["scene_id"]) for s in p.scenes()],
                   "audio": audio_target(p), "timeline": p.hash("render/timeline.json"),
                   "paths": [p.hash(f"render/cache/{s['scene_id']}-paths.json") for s in p.scenes()],
                   "preview_outputs": [p.hash(f"scenes/{s['scene_id']}/preview.mp4") for s in p.scenes()]})


def preview_target(p):
    return digest({"inputs": preview_inputs(p), "full_preview": p.hash("previews/full-preview.mp4"),
                   "review": p.hash("previews/review.json")})


def render(p, preview, selected=None, size=None):
    timeline_ready(p)
    if not preview:
        preview_ready(p)
        p.need_approval("preview", preview_target(p))
    p.data["state"] = "preview_generating" if preview else "rendering"
    p.persist()
    changed, cached = [], []
    for scene in p.scenes():
        sid = scene["scene_id"]
        if selected and sid != selected:
            continue
        annotation = annotation_ready(p, sid)
        if rolls.anchor(p,sid):
            annotation_ready(p,rolls.anchor(p,sid))
        inputs = scene_inputs(p, sid)
        target_size = size if preview else None
        key = ("preview:" if preview else "render:") + sid
        encode_inputs = digest({"drawing": inputs, "size": target_size, "crf": None if preview else p.data["config"]["crf"]})
        if p.fresh(key, encode_inputs) and p.fresh("paths:" + sid, inputs):
            cached.append(sid)
            continue
        name, check = media.render_scene(p, sid, annotation, inputs, target_size)
        require(check["passed"], f"{sid} 绘制检查失败，请查看 reports", 5)
        p.receipt(key, encode_inputs, [f"scenes/{sid}/{name}", f"reports/{sid}-{'preview' if preview else 'final'}.json"])
        # Keep preview geometry separately; it is encoded into preview approval inputs.
        if preview:
            p.data.setdefault("preview_sizes", {})[sid] = list(size)
        changed.append(sid)
        p.persist()
    return {"rendered": changed, "cached": cached}


def scene_output_ready(p, sid, preview):
    annotation_ready(p, sid)
    require(p.fresh("paths:" + sid, scene_inputs(p, sid)), f"{sid} 绘制路径缓存已改变，请重做预览")
    inputs = digest({"drawing": scene_inputs(p, sid),
                     "size": p.data.get("preview_sizes", {}).get(sid) if preview else None,
                     "crf": None if preview else p.data["config"]["crf"]})
    require(p.fresh(("preview:" if preview else "render:") + sid, inputs), f"{sid} 视频缺失或已失效")


def compose(p, preview):
    timeline_ready(p)
    if preview:
        sizes = [p.data.get("preview_sizes", {}).get(s["scene_id"]) for s in p.scenes()]
        require(sizes and all(size == sizes[0] for size in sizes),
                "单镜预览分辨率不一致，请按统一 --resolution 重渲染后再合成")
    if not preview:
        preview_ready(p)
        p.need_approval("preview", preview_target(p))
    clips = []
    for scene in p.scenes():
        sid = scene["scene_id"]
        scene_output_ready(p, sid, preview)
        clips.append(f"scenes/{sid}/{'preview' if preview else 'final'}.mp4")
    inputs = preview_inputs(p) if preview else compose_inputs(p)
    key = "preview_compose" if preview else "compose"
    if p.fresh(key, inputs):
        return {"cached": True}
    output = media.compose(p, preview, clips, "audio/subtitles.srt")
    config = p.data["config"]
    size = p.data["preview_sizes"][p.scenes()[0]["scene_id"]] if preview else [config["width"], config["height"]]
    report = media.video_check(p.path(output), size, config["fps"],
                               p.load("render/timeline.json")["audio_seconds"],
                               subtitles=False)
    report["subtitle_mode"] = "upstream-burned" if config["subtitles"] else "off"
    report["human_visual_listening_acceptance"] = "NOT_RUN"
    require(report["passed"], "合成视频技术验收失败", 5)
    report_path = "reports/preview-validation.json" if preview else "reports/final-validation.json"
    p.save(report_path, report)
    outputs = [output, report_path]
    if preview:
        review = {"technical": report, "scenes": [
            {"scene_id": s["scene_id"], "timing": row_for(p, s["scene_id"]),
             "drawing": p.load(f"reports/{s['scene_id']}-preview.json"),
             "contact": f"scenes/{s['scene_id']}/preview-contact.png"} for s in p.scenes()]}
        p.save("previews/review.json", review)
        outputs.append("previews/review.json")
    p.receipt(key, inputs, outputs)
    return {"output": output, "report": report_path, "passed": report["passed"]}


def preview_ready(p):
    for scene in p.scenes():
        scene_output_ready(p, scene["scene_id"], True)
    require(p.fresh("preview_compose", preview_inputs(p)), "完整预览缺失或版本已失效")


def compose_inputs(p):
    return digest({"scenes": [p.hash(f"scenes/{s['scene_id']}/final.mp4") for s in p.scenes()],
                   "drawing": [scene_inputs(p, s["scene_id"]) for s in p.scenes()],
                   "audio": audio_target(p), "subtitles": p.hash("audio/subtitles.srt"),
                   "config": p.data["config"], "preview": preview_target(p)})


def validate_final(p):
    preview_ready(p)
    p.need_approval("preview", preview_target(p))
    for scene in p.scenes():
        scene_output_ready(p, scene["scene_id"], False)
    require(p.fresh("compose", compose_inputs(p)), "最终合成缺失或版本已失效")
    p.data["state"] = "final_validating"
    p.persist()
    config = p.data["config"]
    report = media.video_check(p.path("output/final.mp4"), [config["width"], config["height"]],
                               config["fps"], p.load("render/timeline.json")["audio_seconds"],
                               subtitles=False)
    report["subtitle_mode"] = "upstream-burned" if config["subtitles"] else "off"
    report["human_visual_listening_acceptance"] = "NOT_RUN"
    p.save("reports/final-validation.json", report)
    require(report["passed"], "成片技术验收失败", 5)
    # Refresh composition receipt because the report is regenerated by validation.
    p.receipt("compose", compose_inputs(p), ["output/final.mp4", "reports/final-validation.json"])
    p.receipt("validated", compose_inputs(p), ["output/final.mp4", "reports/final-validation.json"])
    return report


def approval_target(p, stage, scene_id=None):
    require(scene_id is None or stage == "storyboard", "只有分镜支持逐镜批准；完整预览必须整段确认", 4)
    if stage == "storyboard":
        validate_storyboard(p)
        from . import typography
        typography.ready(p)
        return board_target(p, p.scene(scene_id)) if scene_id else digest({s["scene_id"]: board_target(p, s) for s in p.scenes()})
    if stage == "typography":
        from . import typography
        validate_storyboard(p)
        return typography.approval_target(p)
    if stage == "style":
        board_ready(p)
        validate_style(p)
        return style_target(p)
    if stage == "image_mode":
        style_ready(p)
        return mode_target(p)
    if stage == "audio":
        images_ready(p)
        metadata = p.load("audio/metadata.json", {})
        require(metadata.get("source") == "generated", "用户提供的音频无需配音批准")
        require(metadata.get("content_evidence") and metadata.get("voice_sha256") == p.hash("audio/voice.wav")
                and metadata.get("script_sha256") == p.hash("narration/original.txt"), "先实际试听并执行 audio verify")
        return audio_target(p)
    if stage == "preview":
        preview_ready(p)
        return preview_target(p)
    raise WorkflowError("未知审核阶段")


def approve(p, stage, expected, user_message, scene_id=None):
    require(user_message.strip(), "必须提供用户明确确认的原文，不得自动批准", 4)
    actual = approval_target(p, stage, scene_id)
    require(expected == actual, "审核摘要不匹配，用户看到的版本已经改变", 4)
    record = {"digest": actual, "user_message": user_message, "at": now(), "action": "approve"}
    if stage == "storyboard":
        for scene in p.scenes():
            if scene_id and scene["scene_id"] != scene_id:
                continue
            p.approvals["storyboard:" + scene["scene_id"]] = {**record, "digest": board_target(p, scene)}
    else:
        p.approvals[stage] = record
    p.data.pop("revision", None)
    p.persist()
    return {"approved": stage, "digest": actual}


def status(p):
    """Derive the last valid checkpoint; never trust a stale state string."""
    stage, next_action = "script_ready", "创建 narration/storyboard.json"
    try:
        validate_storyboard(p)
        from . import typography
        if typography.enabled(p):
            stage, next_action = "typography_review", "分镜选择字体，生成 typography sample 并请用户确认"
            typography.ready(p)
        stage, next_action = "storyboard_review", "展示分镜并等待用户确认"
        board_ready(p)
        stage, next_action = "style_review", "展示画风并等待用户确认"
        style_ready(p)
        stage, next_action = "image_mode_review", "请求用户选择 agent/manual"
        mode_ready(p)
        stage, next_action = "images_pending", "准备提示词、图片并执行逐镜头视觉检查和 images validate"
        images_ready(p)
        stage, next_action = "audio_pending", "导入用户音频或生成本地配音"
        if p.load("audio/metadata.json", {}).get("source") == "generated":
            stage, next_action = "audio_review", "提供新配音试听并等待确认"
        audio_ready(p)
        stage, next_action = "preview_generating", "timeline build → annotation build → preview render → preview compose"
        timeline_ready(p)
        preview_ready(p)
        stage, next_action = "preview_review", "展示完整预览、关键帧与检查报告并等待确认"
        p.need_approval("preview", preview_target(p))
        stage, next_action = "rendering", "render → compose → validate"
        for scene in p.scenes():
            scene_output_ready(p, scene["scene_id"], False)
        require(p.fresh("compose", compose_inputs(p)), "需要合成")
        stage, next_action = "final_validating", "validate"
        require(p.fresh("validated", compose_inputs(p)), "需要成片验收")
        stage, next_action = "completed", "交付 output/final.mp4 及 reports/final-validation.json"
    except (WorkflowError, KeyError, TypeError, ValueError) as error:
        reason = str(error)
    else:
        reason = None
    reported = "needs_revision" if p.data.get("revision") else (
        "failed" if p.data.get("last_error", {}).get("code") in (3, 5) else stage)
    p.data["state"] = reported
    p.persist()
    return {"state": reported,
            "checkpoint": stage, "next_action": next_action, "reason": reason,
            "last_error": p.data.get("last_error"), "revision": p.data.get("revision")}


def resume(p):
    """Run deterministic work until an actual user/creative input is missing."""
    p.data.pop("last_error", None)
    current = status(p)
    if p.data.get("revision"):
        return current
    stage = current["checkpoint"]
    if stage == "images_pending":
        try:
            validate_images(p)
        except WorkflowError:
            return status(p)
        return resume(p)
    if stage == "preview_generating":
        timeline_build(p)
        # Missing visual plans are a creative boundary, not permission to invent boxes.
        annotation_build(p)
        c = p.data["config"]
        size = (960, round(960 * c["height"] / c["width"] / 2) * 2) if c["width"] >= c["height"] else (round(960 * c["width"] / c["height"] / 2) * 2, 960)
        render(p, True, size=size)
        compose(p, True)
    elif stage in ("rendering", "final_validating"):
        render(p, False)
        compose(p, False)
        validate_final(p)
    return status(p)
