"""Optional A/B-roll scene contracts and composition using existing renderers."""
from __future__ import annotations

import math
import cv2

from .project import require


PLANNING_PROMPT = """
按文案语义选择是否使用 A/B-roll，不强制每段使用，也不机械交替。
人物、主场景、核心观点用 A-roll；具体物品、动作细节、环境、证据、对比或图解适合 B-roll。
只有辅助画面确实补充信息时才插入；单一动作或短句保持普通分镜。不得编造文案没有依据的事实。
可选 roll 对象：type=a|b，mode=draw|hold|return，reason=与本句文案的关联理由。
B 镜必须有 a_scene=前面已建立的 A 镜 scene-NNN，layout=full|inset（默认 full）。
draw 沿轮廓绘制，hold 直接展示完成图；短辅助镜头优先 hold，避免每次重画。
inset 在已完成的 A 镜上放 B 画中画，可指定 box=[x,y,w,h] 归一化区域，w=h 保持原画幅比例。
返回主镜用 type=a, mode=return, a_scene=原 A 镜编号；复用其完成状态，不重新生图或重画。
原 A 镜必须为 type=a 且 mode=draw 或 hold。返回仅保持已完成状态，不表示中途暂停后续画。
普通镜头省略 roll；使用时把 type/mode/reason/关联镜号展示在分镜表中供整体审核。
每镜口播仍须按顺序拼接成完整原文，B 镜使用其对应那段口播，不能重复 A 镜口播。
若采用 roll，可按语义细分上面的固定分幕，并为所有候选镜头额外输出原文 text；
text 必须逐字按顺序完整覆盖全文，不能遗漏、重复或改写。没有 roll 时继续使用原固定分幕格式。
"""


def settings(scene):
    return {"type": "a", "mode": "draw", "layout": "full", **scene.get("roll", {})}


def validate(scenes, engine):
    previous = {}
    for scene in scenes:
        if "roll" not in scene:
            previous[scene["scene_id"]] = scene
            continue
        raw = scene["roll"]
        require(isinstance(raw, dict) and raw, "roll 必须是非空对象")
        require(engine == "whiteboard", "A/B-roll 编排目前用于白板手绘引擎")
        require(not set(raw) - {"type", "mode", "layout", "a_scene", "box", "reason"}, "roll 包含未知字段")
        require(raw.get("type") in ("a", "b"), "roll.type 必须为 a 或 b")
        require(isinstance(raw.get("reason"), str) and raw["reason"].strip(), "roll.reason 须说明与文案的关联")
        spec = settings(scene)
        require(spec["mode"] in ("draw", "hold", "return"), "未知 roll.mode")
        require(spec["layout"] in ("full", "inset"), "未知 roll.layout")
        needs_anchor = spec["type"] == "b" or spec["mode"] == "return"
        anchor = raw.get("a_scene")
        require(not needs_anchor or (isinstance(anchor, str) and anchor in previous), "B 镜或返回镜须引用更早的 A 镜")
        require(needs_anchor or anchor is None, "普通 A 镜不应设置 a_scene")
        if needs_anchor:
            parent = settings(previous[anchor])
            require(parent["type"] == "a" and parent["mode"] != "return", "a_scene 必须指向原始 A 镜，不能指向 B 镜或返回镜")
        require(spec["mode"] != "return" or spec["type"] == "a", "只有 A 镜可以使用 return")
        require(spec["layout"] != "inset" or spec["type"] == "b", "只有 B 镜可以使用画中画")
        require(spec["mode"] != "return" or not scene.get("visual_text"), "返回镜复用原 A 镜文字，不另叠 visual_text")
        if "box" in raw:
            box = raw["box"]
            require(spec["layout"] == "inset" and isinstance(box, list) and len(box) == 4, "box 仅用于画中画，格式 [x,y,w,h]")
            require(all(type(v) in (int, float) and math.isfinite(v) for v in box), "box 必须包含有限数字")
            x, y, w, h = box
            require(x >= 0 and y >= 0 and w >= .05 and h >= .05 and x+w <= 1 and y+h <= 1
                    and abs(w-h) < 1e-6, "box 须在画布内、宽高比例相等且至少 0.05")
        previous[scene["scene_id"]] = scene


def anchor(p, sid):
    return settings(p.scene(sid)).get("a_scene")


def image_scene(p, sid):
    spec = settings(p.scene(sid))
    return spec["a_scene"] if spec["mode"] == "return" else sid


def image_path(p, sid):
    return p.path(f"scenes/{image_scene(p, sid)}/image.png")


def static(p, sid):
    return settings(p.scene(sid))["mode"] in ("hold", "return")


def completed_frame(p, sid):
    """Actual canonical drawing state, never the source art or a lossy preview."""
    from . import media, typography, workflow
    from .text_render import TextOverlay
    inputs = workflow.scene_inputs(p,sid)
    cache = f"render/cache/{sid}-completed.png"
    if p.fresh("completed:"+sid,inputs):
        frame = media._imread_any(p.path(cache))
        require(frame is not None, f"{sid} 完成画布无法解码")
        return frame
    annotation = p.load(f"scenes/{sid}/annotation.json")
    require(annotation, f"{sid} 缺少完成画面标注")
    renderer = media.native_renderer(p, sid, annotation)
    if static(p,sid):
        frame = renderer.color_img.copy()
    else:
        # Selected B/return rendering may run before an A video exists. Replay the
        # same drawing paths without encoding, then retain only the clean canvas.
        class StateWriter:
            def isOpened(self): return True
            def write(self, frame): pass
            def release(self): pass
        cached = p.load(f"render/cache/{sid}-paths.json",{})
        paths = cached.get("paths") if p.fresh("paths:"+sid,inputs) else None
        renderer.tip = None
        renderer.render_to(p.path(f"render/cache/{sid}-state.mp4"),annotation["sceneDurationMs"],
                           writer=StateWriter(),paths=paths)
        frame = renderer._snapshot().copy()
    if p.scene(sid).get("visual_text"):
        typography.ready(p)
        TextOverlay(typography.layout(p, p.scene(sid), (renderer.out_w, renderer.out_h)),
                    annotation["sceneDurationMs"], renderer.cfg.fps).paint(frame, annotation["sceneDurationMs"])
    store_completed(p,sid,frame,inputs)
    return frame


def has_dependants(p, sid):
    return any(settings(scene).get("a_scene") == sid for scene in p.scenes())


def store_completed(p, sid, frame, inputs):
    cache = f"render/cache/{sid}-completed.png"
    success, encoded = cv2.imencode(".png",frame)
    require(success, "无法保存完成画布")
    encoded.tofile(str(p.path(cache)))
    p.receipt("completed:"+sid,inputs,[cache])


def inset_frame(background, foreground, box):
    h, w = background.shape[:2]
    x, y, bw, bh = box
    x0, y0 = round(x*w), round(y*h)
    x1, y1 = round((x+bw)*w), round((y+bh)*h)
    result = background.copy()
    result[y0:y1,x0:x1] = cv2.resize(foreground, (x1-x0,y1-y0), interpolation=cv2.INTER_AREA)
    return result


def check_completed(path, expected, count):
    cap = cv2.VideoCapture(str(path))
    decoded, last = 0, None
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            decoded += 1
            last = frame
    finally:
        cap.release()
    require(last is not None, "A/B-roll 输出无法解码")
    error = float(cv2.absdiff(last, cv2.resize(expected, (last.shape[1],last.shape[0]))).mean())
    return {"passed": decoded == count and error < 18, "decoded_frames": decoded,
            "expected_frames": count, "final_frame_complete": error < 18,
            "final_frame_mae": error, "visual_acceptance": "NOT_RUN"}


def encode(p, raw, output, size, duration_ms):
    from . import media
    pending = output.with_name(output.stem + ".roll-pending.mp4")
    media.run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-an", "-c:v", "libx264",
               "-crf", str(p.data["config"]["crf"]), "-pix_fmt", "yuv420p", "-movflags", "+faststart", pending])
    check = media.video_check(pending, size, p.data["config"]["fps"], duration_ms/1000, audio=False)
    require(check["passed"], "A/B-roll 视频检查失败", 5)
    pending.replace(output)
    raw.unlink(missing_ok=True)


def compose_inset(p, sid, output, expected, duration_ms, base_check):
    from . import media
    spec = settings(p.scene(sid))
    if spec["layout"] != "inset":
        return base_check
    background = completed_frame(p, spec["a_scene"])
    box = spec.get("box", [.6, .06, .34, .34])
    cap = cv2.VideoCapture(str(output))
    size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    raw = p.path(f"render/cache/{sid}-inset-raw.mp4")
    writer = media.PreviewWriter(raw, p.data["config"]["fps"], size)
    require(writer.isOpened(), "无法创建画中画视频")
    back = cv2.resize(background, size, interpolation=cv2.INTER_AREA)
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            writer.write(inset_frame(back, frame, box))
    finally:
        cap.release()
        writer.release()
    encode(p, raw, output, size, duration_ms)
    result = check_completed(output, inset_frame(background, expected, box),
                             round(duration_ms*p.data["config"]["fps"]/1000))
    result.update(roll=spec, base_drawing=base_check, mask_check="REQUIRES_VISUAL_REVIEW")
    return result


def render_static(p, sid, annotation, inputs, preview_size):
    from . import media, typography
    from .text_render import TextOverlay
    config = p.data["config"]
    spec = settings(p.scene(sid))
    frame = completed_frame(p, spec["a_scene"]) if spec["mode"] == "return" else media.native_renderer(p, sid, annotation).color_img.copy()
    size = preview_size or [config["width"],config["height"]]
    require(abs(size[0]/size[1] - config["width"]/config["height"]) < .01, "预览画幅比例必须与正式画幅一致")
    frames = round(annotation["sceneDurationMs"]*config["fps"]/1000)
    raw = p.path(f"render/cache/{sid}-hold-raw.mp4")
    writer = media.PreviewWriter(raw, config["fps"], size)
    require(writer.isOpened(), "无法创建静态镜头视频")
    overlay = None
    if p.scene(sid).get("visual_text"):
        typography.ready(p)
        overlay = TextOverlay(typography.layout(p,p.scene(sid),(frame.shape[1],frame.shape[0])),annotation["sceneDurationMs"],config["fps"])
    try:
        for index in range(frames):
            current = frame.copy()
            if overlay:
                overlay.paint(current, (index+1)*1000/config["fps"])
            writer.write(current)
    finally:
        writer.release()
    if overlay:
        overlay.paint(frame,annotation["sceneDurationMs"])
    name = "preview.mp4" if preview_size else "final.mp4"
    output = p.path(f"scenes/{sid}/{name}")
    encode(p,raw,output,size,annotation["sceneDurationMs"])
    check = check_completed(output,frame,frames)
    check = compose_inset(p,sid,output,frame,annotation["sceneDurationMs"],check)
    check.update(roll=spec, intentional_hold=True)
    if check["passed"] and has_dependants(p,sid):
        store_completed(p,sid,frame,inputs)
    stage = "preview" if preview_size else "final"
    p.save(f"reports/{sid}-{stage}.json",check)
    cache = f"render/cache/{sid}-paths.json"
    p.save(cache,{"inputs":inputs,"mode":spec["mode"],"paths":[]})
    p.receipt("paths:"+sid,inputs,[cache])
    media.contact_sheet(output,p.path(f"scenes/{sid}/{stage}-contact.png"))
    return name,check
