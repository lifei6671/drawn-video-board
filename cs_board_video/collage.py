"""Narration-anchored collage plans and an isolated Remotion production path.

Plan times are milliseconds; only the compiler converts them into frame indices.
Elements may overlap and survive scene changes. Drawing annotations are not used.
"""
from __future__ import annotations

from copy import deepcopy
import math
import os
from pathlib import Path
import re
import shutil

from PIL import Image

from . import media, direction
from .project import WorkflowError, digest, file_hash, now, read_json, require


PLAN = "narration/collage.json"
ENTRANCES = {"none", "fade", "slide-left", "slide-right", "slide-up", "slide-down", "pop"}
PROPERTIES = {"x", "y", "scale", "rotation", "opacity"}


def enabled(p):
    return p.data["config"].get("composition_type") == "collage"


def number(value, label, low=None, high=None):
    require(type(value) in (int, float) and math.isfinite(value), f"{label} 必须为有限数字")
    require((low is None or value >= low) and (high is None or value <= high), f"{label} 超出范围")
    return value


def text(value, label):
    require(isinstance(value, str) and value.strip(), f"缺少 {label}")
    return value


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", value), "元素、段落及素材 ID 仅支持字母数字与连字符")
    return value


def normalized(value):
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE)


def asset_path(p, value):
    text(value, "项目内素材路径")
    path = p.path(value)
    require(path.is_file(), f"素材不存在: {value}")
    return path


def compile_plan(p, plan=None):
    """Validate local inputs and produce the sole renderer-facing contract."""
    plan = deepcopy(plan if plan is not None else p.load(PLAN))
    require(isinstance(plan, dict) and plan.get("schema_version") == 1, "需要 schema_version=1 的拼贴计划")
    config = p.data["config"]
    fps = config["fps"]
    frame = lambda ms: round(ms * fps / 1000)
    duration = number(plan.get("duration_ms"), "duration_ms", 1000)
    total = frame(duration)
    audio = asset_path(p, plan.get("audio"))
    plan["audio"] = audio.relative_to(p.root).as_posix()
    alignment = plan.get("alignment", {})
    require(isinstance(alignment, dict), "alignment 必须为对象")
    text(alignment.get("source"), "对齐来源")
    text(alignment.get("evidence"), "音频与文案比对证据")
    require(alignment.get("audio_sha256") == file_hash(audio), "音频已改变，需要重新对齐并更新 audio_sha256")
    require(any(s.get("codec_type") == "audio" for s in media.probe(audio)["streams"]), "配音文件没有音轨")
    require(abs(media.duration(audio) - total / fps) <= max(.1, 2 / fps), "计划时长必须与真实音频一致")
    font = asset_path(p, plan.get("font"))
    plan["font"] = font.relative_to(p.root).as_posix()
    require(font.suffix.lower() in (".ttf", ".otf", ".woff", ".woff2"), "字体需为本地 TTF/OTF/WOFF 文件")
    assets = plan.get("assets")
    require(isinstance(assets, dict) and assets, "需要素材清单 assets")
    files = {plan["audio"]: file_hash(audio), plan["font"]: file_hash(font)}
    for key, asset in assets.items():
        identifier(key)
        require(isinstance(asset, dict), f"素材 {key} 必须为对象")
        text(asset.get("description"), f"素材 {key} 的视觉描述")
        text(asset.get("source"), f"素材 {key} 的来源")
        path = asset_path(p, asset.get("path"))
        asset["path"] = path.relative_to(p.root).as_posix()
        with Image.open(path) as image:
            require(image.format in ("PNG", "JPEG", "WEBP"), "拼贴素材支持 PNG/JPEG/WebP")
            require(min(image.size) >= 16, f"素材过小: {key}")
            image.verify()
        files[asset["path"]] = file_hash(path)
    require(plan.get("background") in assets, "background 必须引用素材 ID")
    beats = plan.get("beats")
    require(isinstance(beats, list) and beats, "需要带真实时码的文案 beats")
    cues, captions, cursor = {}, [], 0
    for beat in beats:
        require(isinstance(beat, dict), "beat 必须为对象")
        direction.validate(beat)
        key = identifier(beat.get("id"))
        require(key not in cues, "beat ID 重复")
        start = number(beat.get("start_ms"), f"{key}.start_ms", cursor, duration)
        end = number(beat.get("end_ms"), f"{key}.end_ms", start, duration)
        require(frame(end) > frame(start), "文案片段至少一帧")
        text(beat.get("text"), "文案片段")
        text(beat.get("visual_goal"), "文案视觉意图")
        cues[key] = beat
        captions.append({"id": key, "text": beat["text"], "startFrame": frame(start), "endFrame": frame(end)})
        cursor = end
    original = p.path("narration/original.txt").read_text(encoding="utf-8-sig")
    require(normalized("".join(b["text"] for b in beats)) == normalized(original), "beats 必须按顺序完整覆盖原文")

    def interval(item, label):
        if "anchor" in item:
            require("start_ms" not in item and item["anchor"] in cues, f"{label} 的 anchor 无效或与 start_ms 冲突")
            start = cues[item["anchor"]]["start_ms"] + number(item.get("offset_ms", 0), "offset_ms")
        else:
            require("offset_ms" not in item, "offset_ms 需要 anchor")
            start = number(item.get("start_ms"), f"{label}.start_ms")
        number(start, f"{label} 开始时间", 0, duration)
        end = number(item.get("end_ms"), f"{label}.end_ms", start, duration)
        require(frame(end) > frame(start), f"{label} 至少需要一帧")
        return frame(start), frame(end)

    def effect(value, length, exit=False):
        value = value or {"type": "none"}
        require(isinstance(value, dict) and value.get("type") in ENTRANCES - ({"pop"} if exit else set()), "未知入场/退场动画")
        ms = number(value.get("duration_ms", 0 if value["type"] == "none" else 400), "动画时长", 0)
        frames = frame(ms)
        require(frames <= length and (value["type"] == "none" or frames >= 1), "动画时长超出元素可见范围")
        return {"type": value["type"], "frames": frames,
                "distance": number(value.get("distance", 160), "动画位移", 0)}

    groups = {}
    group_list = plan.get("groups", [])
    require(isinstance(group_list, list), "groups 必须为列表")
    for group in group_list:
        require(isinstance(group, dict), "group 必须为对象")
        key = identifier(group.get("id"))
        require(key not in groups, "group ID 重复")
        start, end = interval(group, key)
        enter, leave = effect(group.get("enter"), end-start), effect(group.get("exit"), end-start, True)
        require(enter["frames"] + leave["frames"] <= end-start, "组入场与退场不可重叠")
        groups[key] = {"startFrame": start, "endFrame": end, "enter": enter, "exit": leave}
    elements = plan.get("elements")
    require(isinstance(elements, list) and elements, "需要独立元素 elements")
    compiled, ids = [], set()
    for item in elements:
        require(isinstance(item, dict), "element 必须为对象")
        key = identifier(item.get("id"))
        require(key not in ids, "element ID 重复")
        ids.add(key)
        start, end = interval(item, key)
        kind = item.get("kind")
        require(kind in ("image", "text"), "元素类型支持 image/text")
        if kind == "image":
            require(item.get("asset") in assets, f"{key} 引用未知素材")
        else:
            text(item.get("text"), f"{key}.text")
        group = groups.get(item.get("group"))
        require(not item.get("group") or group is not None, "元素引用未知 group")
        require(not group or (start >= group["startFrame"] and end <= group["endFrame"]), "元素时间必须位于所属组内")
        origin = item.get("origin", [0.5, 0.5])
        require(isinstance(origin, list) and len(origin) == 2, "origin 格式为 [x,y]，范围 0..1")
        for v in origin:
            number(v, "origin", 0, 1)
        enter, leave = effect(item.get("enter"), end-start), effect(item.get("exit"), end-start, True)
        require(enter["frames"] + leave["frames"] <= end-start, "元素入场与退场不可重叠")
        row = {"id": key, "kind": kind, "startFrame": start, "endFrame": end,
               "x": number(item.get("x", 0), "x"), "y": number(item.get("y", 0), "y"),
               "width": number(item.get("width"), "width", 1), "height": number(item.get("height"), "height", 1),
               "z": number(item.get("z", 0), "z"), "scale": number(item.get("scale", 1), "scale", .001),
               "rotation": number(item.get("rotation", 0), "rotation"),
               "opacity": number(item.get("opacity", 1), "opacity", 0, 1),
               "origin": origin, "enter": enter, "exit": leave, "group": group,
               "fit": item.get("fit", "contain"), "text": item.get("text", ""),
               "src": assets[item["asset"]]["path"] if kind == "image" else None,
               "fontSize": number(item.get("font_size", 60), "font_size", 12),
               "color": item.get("color", "#202020"), "keyframes": {}}
        require(row["fit"] in ("contain", "cover"), "fit 仅支持 contain/cover")
        require(isinstance(row["color"], str) and re.fullmatch(r"#[0-9a-fA-F]{6}", row["color"]), "文字颜色必须为 #RRGGBB")
        motion = item.get("motion", {"type": "none"})
        require(isinstance(motion, dict) and motion.get("type") in ("none", "sway", "float", "spin"), "未知循环动画")
        row["motion"] = {"type": motion["type"], "amplitude": number(motion.get("amplitude", 3), "motion.amplitude"),
                         "periodFrames": max(1, frame(number(motion.get("period_ms", 3000), "motion.period_ms", 100)))}
        lanes = item.get("keyframes", {})
        require(isinstance(lanes, dict) and not set(lanes) - PROPERTIES, "未知关键帧属性")
        for prop, points in lanes.items():
            require(isinstance(points, list) and len(points) >= 2, "关键帧轨道至少两个点")
            frames, values = [], []
            for point in points:
                require(isinstance(point, dict), "关键帧必须为对象")
                f = frame(number(point.get("at_ms"), "关键帧时间", 0, (end-start)*1000/fps))
                require(not frames or f > frames[-1], "关键帧时间须严格递增且不落在同一帧")
                value = number(point.get("value"), "关键帧数值", .001 if prop == "scale" else 0 if prop == "opacity" else None,
                               1 if prop == "opacity" else None)
                frames.append(f)
                values.append(value)
            row["keyframes"][prop] = {"frames": frames, "values": values}
        compiled.append(row)
    props = {"compositionType": "collage", "width": config["width"], "height": config["height"], "fps": fps,
             "totalDurationFrames": total, "background": assets[plan["background"]]["path"], "font": plan["font"],
             "elements": sorted(compiled, key=lambda x: x["z"]), "captions": captions if config["subtitles"] else []}
    inputs = digest({"plan": plan, "script": p.hash("narration/original.txt"), "files": files,
                     "config": {k: config[k] for k in ("width", "height", "fps", "subtitles")}})
    return props, files, inputs


def engine_hash():
    root = media.UPSTREAM_ROOT / "video_renderer"
    return digest({"python": file_hash(Path(__file__)), "media": file_hash(Path(media.__file__)), **{name: file_hash(root/name) for name in
        ("render.mjs", "src/root.tsx", "src/collage.tsx", "src/collage-motion.ts", "src/collage-types.ts", "package-lock.json")}})


def render_inputs(p, inputs, size, preview):
    return digest({"inputs": inputs, "engine": engine_hash(), "size": size,
                   "crf": 23 if preview else p.data["config"]["crf"]})


def preview_target(p):
    _, _, inputs = compile_plan(p)
    p.need_approval("collage", inputs)
    size = p.data.get("collage_preview_size")
    require(size and p.fresh("collage:preview", render_inputs(p, inputs, size, True)), "完整拼贴预览缺失或已失效", 4)
    return digest({"inputs": inputs, "engine": engine_hash(), "video": p.hash("previews/full-preview.mp4"),
                   "report": p.hash("previews/review.json")})


def render(p, preview, size=None):
    props, files, inputs = compile_plan(p)
    p.need_approval("collage", inputs)
    if not preview:
        p.need_approval("preview", preview_target(p))
    size = size or [props["width"], props["height"]]
    require(len(size) == 2 and all(type(v) is int and v >= 100 and v % 2 == 0 for v in size), "预览宽高须为偶数且至少 100")
    require(abs(size[0]/size[1] - props["width"]/props["height"]) < .001, "预览须保持项目画幅比例")
    stage = "preview" if preview else "final"
    key = "collage:" + stage
    target = render_inputs(p, inputs, size, preview)
    output = "previews/full-preview.mp4" if preview else "output/final.mp4"
    if p.fresh(key, target):
        return {"cached": True, "video": output}
    public = p.path(f"render/cache/collage-public/{inputs}")
    public.mkdir(parents=True, exist_ok=True)
    audio_name = p.path(p.load(PLAN)["audio"]).relative_to(p.root).as_posix()
    for name in files:
        if name == audio_name:
            continue
        destination = public / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p.path(name), destination)
    p.save("render/collage-props.json", props)
    native = p.path(f"render/cache/collage-{stage}-silent.mp4")
    env = {**os.environ, "CS_BOARD_CRF": str(23 if preview else p.data["config"]["crf"]), "CS_BOARD_CONCURRENCY": "2",
           "CS_BOARD_BUNDLE_DIR": str(p.path("render/cache/collage-bundle"))}
    media.run(["node", media.UPSTREAM_ROOT / "video_renderer/render.mjs", p.path("render/collage-props.json"), native, public],
              cwd=media.UPSTREAM_ROOT / "video_renderer", env=env)
    pending = p.path(output).with_suffix(".pending.mp4")
    media.run(["ffmpeg", "-y", "-v", "error", "-i", native, "-i", p.path(p.load(PLAN)["audio"]),
               "-map", "0:v:0", "-map", "1:a:0", "-vf", f"scale={size[0]}:{size[1]}", "-c:v", "libx264",
               "-crf", str(23 if preview else p.data["config"]["crf"]), "-pix_fmt", "yuv420p", "-c:a", "aac",
               "-t", str(props["totalDurationFrames"]/props["fps"]), "-movflags", "+faststart", pending])
    report = media.video_check(pending, size, props["fps"], props["totalDurationFrames"]/props["fps"])
    require(report["passed"], "拼贴视频技术校验失败", 5)
    pending.replace(p.path(output))
    report.update(mode="collage", input_digest=inputs, visual_acceptance="NOT_RUN", listening_acceptance="NOT_RUN",
                  beats=p.load(PLAN)["beats"], elements=[{"id":e["id"], "startFrame":e["startFrame"], "endFrame":e["endFrame"]} for e in props["elements"]])
    report_path = "previews/review.json" if preview else "reports/final-validation.json"
    p.save(report_path, report)
    media.contact_sheet(p.path(output), p.path(f"previews/collage-{stage}-contact.png"))
    p.receipt(key, target, [output, report_path])
    if preview:
        p.data["collage_preview_size"] = size
    p.data["state"] = "preview_pending" if preview else "delivered"
    p.persist()
    return {"video": output, "report": report_path, "approval_required": preview}


def dispatch(p, args):
    command, action = args.command, getattr(args, "action", None)
    if command == "collage":
        if action == "request":
            request = {"narration": p.path("narration/original.txt").read_text(encoding="utf-8-sig"),
                       "prompt": "按原文规划拼贴分镜，每段包含原文 text、visual_goal、visual_plan 和前后景与动画安排。先讨论表达与素材，再取得素材、按真实音频时码编写完整 collage.json；不得编造语音时码。" + direction.PLANNING_PROMPT,
                       "protocol": "references/collage.md"}
            p.save("narration/collage-request.json", request)
            return {"request": "narration/collage-request.json"}
        if action == "import":
            plan = read_json(Path(args.file))
            props, _, inputs = compile_plan(p, plan)
            p.save(PLAN, plan)
            return {"digest": inputs, "frames": props["totalDurationFrames"], "approval_required": True}
        props, _, inputs = compile_plan(p)
        if action == "prompts":
            prompts = [{"id": key, "path": asset["path"], "description": asset["description"], "source": asset["source"]}
                       for key, asset in p.load(PLAN)["assets"].items()]
            visual_plans = [{"id": beat["id"], "text": beat["text"], "visual_goal": beat["visual_goal"],
                             **({"visual_plan": beat["visual_plan"]} if "visual_plan" in beat else {})}
                            for beat in p.load(PLAN)["beats"]]
            result = {"assets": prompts, "beats": visual_plans,
                      "cutout_method": "AI image editing; no local segmentation model",
                      "note": "素材与表达计划；不会自动联网下载、生图或执行抠图"}
            p.save("render/collage-assets.json", result)
            return result
        return {"passed": True, "digest": inputs, "elements": len(props["elements"]), "frames": props["totalDurationFrames"]}
    if command in ("review", "approve", "revise"):
        require(args.stage in ("collage", "preview") and not args.scene, "拼贴模式审核阶段为 collage/preview，不按单镜批准")
        if command == "revise":
            text(args.feedback, "修改意见")
            p.approvals.pop(args.stage, None)
            p.data["revision"] = {"stage": args.stage, "feedback": args.feedback, "at": now()}
            p.persist()
            return {"stage": args.stage, "revoked": True}
        target = compile_plan(p)[2] if args.stage == "collage" else preview_target(p)
        if command == "review":
            return {"stage": args.stage, "digest": target, "plan": PLAN,
                    "instruction": "展示素材、分镜、时码与样图；仅用真实用户授权记录批准"}
        require(args.digest == target, "版本已改变，请重新审核", 4)
        text(args.user_message, "用户确认原文")
        p.approvals[args.stage] = {"digest": target, "user_message": args.user_message, "at": now()}
        return {"stage": args.stage, "approved": True}
    if command in ("status", "resume"):
        if not p.path(PLAN).exists():
            return {"mode": "collage", "next": "collage import", "plan": PLAN}
        props, _, inputs = compile_plan(p)
        if not p.approved("collage", inputs):
            return {"mode": "collage", "next": "review --stage collage", "digest": inputs}
        # Preserve portrait and square projects during resume as well.
        size = p.data.get("collage_preview_size", [props["width"], props["height"]])
        if not p.fresh("collage:preview", render_inputs(p, inputs, size, True)):
            return render(p, True, size) if command == "resume" else {"mode": "collage", "next": "preview render"}
        target = preview_target(p)
        final_size = [props["width"], props["height"]]
        if p.approved("preview", target) and p.fresh("collage:final", render_inputs(p, inputs, final_size, False)):
            return {"mode": "collage", "state": "delivered", "video": "output/final.mp4", "next": None}
        return {"mode": "collage", "next": "render --all" if p.approved("preview", target) else "review --stage preview",
                "video": "previews/full-preview.mp4", "digest": target}
    if command == "preview":
        require(not getattr(args, "scene", None), "拼贴预览使用连续完整时间轴，不支持 --scene")
        if action == "compose":
            preview_target(p)
            return {"video": "previews/full-preview.mp4", "cached": True}
        try:
            size = [int(x) for x in args.resolution.split("x")]
            require(len(size) == 2, "预览格式为 960x540")
        except ValueError as error:
            raise WorkflowError("预览格式为 960x540") from error
        return render(p, True, size)
    if command == "render":
        require(args.all, "拼贴动画请使用 render --all")
        return render(p, False)
    if command in ("compose", "validate"):
        props, _, inputs = compile_plan(p)
        p.need_approval("collage", inputs)
        p.need_approval("preview", preview_target(p))
        size = [props["width"], props["height"]]
        require(p.fresh("collage:final", render_inputs(p, inputs, size, False)), "正式拼贴视频不存在或已失效", 4)
        return {"video": "output/final.mp4", "report": p.load("reports/final-validation.json")}
    raise WorkflowError("拼贴模式使用 collage import/validate、asset、materials、review/approve、preview、render、status/resume；手绘命令不适用于此模式")
