"""Optional, locally typeset visual text with a font/sample approval gate."""
from io import BytesIO
import json
import math
from pathlib import Path
import re

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFont
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

from .project import digest, file_hash, require

ASSETS = Path(__file__).parent / "assets"
FONT_DIR = Path(__file__).resolve().parents[1] / "references/fonts"
PRESENTATIONS = ("plain", *json.loads((ASSETS / "bubbles/templates.json").read_text(encoding="utf-8")))


def fonts(directory=None, *, font_id=None):
    root = Path(directory) if directory else FONT_DIR
    require(root.is_dir(), "字体目录不存在，请使用 --directory 指定 references/fonts")
    rows = []
    for path in sorted(root.iterdir()):
        if path.suffix.lower() not in (".ttf", ".otf", ".woff", ".woff2") or (font_id is not None and path.stem != font_id):
            continue
        with TTFont(path, lazy=True) as font:
            rows.append({"id": path.stem, "name": font["name"].getDebugName(1),
                         "path": str(path.resolve()), "sha256": file_hash(path),
                         "chinese": all(ord(c) in font.getBestCmap() for c in "中文字体"),
                         "axes": {a.axisTag: [a.minValue, a.defaultValue, a.maxValue]
                                  for a in font["fvar"].axes} if "fvar" in font else {}})
    return rows


def choose_font(p, font_id, directory=None, weight=None):
    matches = fonts(directory, font_id=font_id)
    require(len(matches) == 1, "未知或重名字体，请先查看 typography fonts")
    row = matches[0]
    with TTFont(row["path"], recalcTimestamp=False) as font:
        if weight is not None:
            axes = row["axes"]
            require("wght" in axes and axes["wght"][0] <= weight <= axes["wght"][2], "字体不支持该可变字重")
            font = instantiateVariableFont(font, {"wght": weight}, inplace=True)
        font.flavor = None
        buffer = BytesIO()
        font.save(buffer)
    raw = buffer.getvalue()
    import hashlib
    path = f"style/fonts/{hashlib.sha256(raw).hexdigest()}.ttf"
    p.path(path).parent.mkdir(parents=True, exist_ok=True)
    p.path(path).write_bytes(raw)
    p.save("style/typography.json", {"font_id": row["id"], "font_name": row["name"],
           "font_path": path, "source_sha256": row["sha256"], "weight": weight})
    return {"font": row["name"], "path": path, "sample_required": True}


def validate_scene(scene, config):
    items = scene.get("visual_text", [])
    require(isinstance(items, list) and len(items) <= 3, "每镜 visual_text 为最多三条的数组；普通镜头留空")
    require(scene.get("visual_mode", "illustration") in ("illustration", "text_only"), "未知 visual_mode")
    require(scene.get("visual_mode") != "text_only" or items, "纯文字镜头必须提供 visual_text")
    if items:
        require(config.get("render_engine", "whiteboard") == "whiteboard", "visual_text 当前用于 whiteboard；Remotion 请使用原 deck 文本节点")
    for item in items:
        require(isinstance(item, dict) and isinstance(item.get("text"), str)
                and 0 < len(item["text"].strip()) <= 120, "画面文字需为 1..120 字，不会静默截断")
        require(isinstance(item.get("purpose"), str) and item["purpose"].strip(), "请说明画面文字与口播的关联及使用目的")
        require(item.get("presentation", "plain") in PRESENTATIONS, "未知文字/气泡样式")
        require(item.get("animation", "characters") in ("characters", "fade"), "文字 animation 仅支持 characters（逐字渐显）或 fade（整体淡入）")
        box = item.get("box")
        require(isinstance(box, list) and len(box) == 4 and all(type(v) in (int, float)
                and math.isfinite(v) for v in box), "文字 box 使用归一化 [x,y,width,height]")
        x, y, w, h = box
        require(x >= 0 and y >= 0 and w > 0 and h > 0 and x+w <= 1.000001 and y+h <= 1.000001, "文字区域越界")
        scale = item.get("font_scale", .07)
        require(type(scale) in (float, int) and .02 <= scale <= .3, "font_scale 应为画幅高度的 0.02..0.3")
        for key, default in (("color", "#202020"), ("fill", "#FFFFFC")):
            require(isinstance(item.get(key, default), str) and re.fullmatch(r"#[0-9a-fA-F]{6}", item.get(key, default)), "文字及气泡颜色须为 #RRGGBB")
        start, duration = item.get("start", .65), item.get("duration", .25)
        require(all(type(v) in (float, int) and math.isfinite(v) for v in (start, duration))
                and start >= 0 and duration > 0 and start + duration <= .95,
                "文字 start/duration 使用镜头时长比例，且结束后至少留 5% 停留")


def enabled(p):
    return any(s.get("visual_text") for s in p.scenes())


def inputs(p):
    config = p.load("style/typography.json", {})
    return digest({"font": config, "font_bytes": p.hash(config["font_path"]) if config.get("font_path") else None,
                   "text": [{"id": s["scene_id"], "visual_text": s.get("visual_text", []),
                             "mode": s.get("visual_mode", "illustration")} for s in p.scenes()],
                   "size": [p.data["config"]["width"], p.data["config"]["height"]],
                   "text_engine": file_hash(Path(__file__).with_name("text_render.py")),
                   "engine": file_hash(Path(__file__)), "bubbles": file_hash(ASSETS / "bubbles/templates.json")})


def approval_target(p):
    require(enabled(p), "当前分镜没有画面文字，无需字体确认")
    sample = p.load("style/typography-sample.json", {})
    require(sample.get("inputs") == inputs(p), "字体、文字或布局已变，请重新生成 typography sample", 4)
    require(p.hash("previews/typography-sample.png") == sample.get("image_sha256"), "文字样图缺失或已改变", 4)
    require(p.hash(sample["background"]) == sample.get("background_sha256"), "样图背景已改变，请重新生成", 4)
    return digest(sample)


def ready(p):
    if enabled(p):
        p.need_approval("typography", approval_target(p))


def font_path(p):
    selection = p.load("style/typography.json", {})
    require(selection.get("font_path"), "请先用 typography font 选择字体")
    path = p.path(selection["font_path"])
    require(path.is_file(), "项目字体副本缺失")
    return path


def bubble_image(kind, size, fill, ink):
    """Rasterize the reusable normalized polygon assets, including transparent tails."""
    import json
    templates = json.loads((ASSETS / "bubbles/templates.json").read_text(encoding="utf-8"))
    image = Image.new("RGBA", size)
    if kind == "plain":
        return image
    draw = ImageDraw.Draw(image)
    definition = templates[kind]
    width, height = size
    points = [(round(x*width), round(y*height)) for x, y in definition["outline"]]
    draw.polygon(points, fill=fill)
    if definition.get("stroke", True):
        draw.line(points+[points[0]], fill=ink, width=max(1, round(min(size)*.009)), joint="curve")
    for x, y, rx, ry in definition.get("dots", []):
        draw.ellipse(((x-rx)*width, (y-ry)*height, (x+rx)*width, (y+ry)*height), fill=fill, outline=ink, width=max(1, round(min(size)*.009)))
    return image


def layout(p, scene, size):
    """Return ordered glyph masks, and independent bubble shapes; no model-written text."""
    validate_scene(scene, p.data["config"])
    if not scene.get("visual_text"):
        return []
    path = font_path(p)
    with TTFont(path, lazy=True) as source:
        cmap = source.getBestCmap()
        missing = sorted({c for item in scene["visual_text"] for c in item["text"] if not c.isspace() and ord(c) not in cmap})
    require(not missing, "所选字体缺少字符：" + "".join(missing))
    width, height = size
    layers = []
    for item in scene["visual_text"]:
        x, y, w, h = [round(v*d) for v, d in zip(item["box"], (width,height,width,height))]
        px = max(12, round(height*item.get("font_scale", .07)))
        font = ImageFont.truetype(str(path), px)
        kind = item.get("presentation", "plain")
        import json
        safe = ([0, 0, 1, 1] if kind == "plain" else
                json.loads((ASSETS / "bubbles/templates.json").read_text(encoding="utf-8"))[kind]["text_box"])
        left, top_pad, inner_w, inner_h = [round(v*d) for v,d in zip(safe,(w,h,w,h))]
        require(inner_w > 0 and inner_h > 0, "文字区域太小")
        def span(text):
            # Rendering uses separate glyphs, so measure the same advances plus
            # actual bearings rather than a kerned whole-string advance.
            cursor, low, high = 0., 0., 0.
            for char in text:
                bounds = font.getbbox(char, anchor="ls")
                low = min(low, cursor+bounds[0])
                high = max(high, cursor+bounds[2])
                cursor += font.getlength(char)
            return low, max(high, cursor)

        lines = []; line = ""
        for c in item["text"]:
            if c == "\n":
                lines.append(line); line = ""; continue
            low, high = span(c)
            require(high-low <= inner_w, "单字墨迹宽度超出文字区域，请减小字号或增大区域")
            low, high = span(line+c)
            if line and high-low > inner_w:
                lines.append(line); line = ""
            line += c
        lines.append(line)
        ascent, descent = font.getmetrics()
        line_h = max(round(px*1.3), ascent+descent)
        require(len(lines)*line_h <= inner_h, "文字排版溢出，请缩短文字、减小字号或扩大区域；不会截断")
        glyphs = []
        for row, line in enumerate(lines):
            low, high = span(line)
            cursor = x + left + (inner_w-(high-low))/2 - low
            top = y + top_pad + (inner_h-len(lines)*line_h)/2 + row*line_h
            baseline = top + (line_h-ascent-descent)/2 + ascent
            for char in line:
                if not char.isspace():
                    bbox = font.getbbox(char, anchor="ls")
                    gw, gh = max(1, bbox[2]-bbox[0]), max(1, bbox[3]-bbox[1])
                    mask = Image.new("L", (gw+4, gh+4))
                    ImageDraw.Draw(mask).text((2-bbox[0], 2-bbox[1]), char, font=font, fill=255, anchor="ls")
                    alpha = np.asarray(mask)
                    gx, gy = round(cursor)+bbox[0]-2, round(baseline)+bbox[1]-2
                    ys, xs = np.where(alpha > 0)
                    require(not len(xs) or (gx+xs.min() >= x+left and gx+xs.max() < x+left+inner_w
                            and gy+ys.min() >= y+top_pad and gy+ys.max() < y+top_pad+inner_h),
                            "文字墨迹超出安全区，请减小字号或扩大区域；不会截断")
                    glyphs.append({"mask": alpha, "x": gx, "y": gy, "char": char})
                cursor += font.getlength(char)
        bubble = bubble_image(kind, (w, h), item.get("fill", "#FFFFFC"), item.get("color", "#202020"))
        layers.append({"glyphs": glyphs, "bubble": np.asarray(bubble), "x": x, "y": y,
                       "color": ImageColor.getrgb(item.get("color", "#202020")),
                       "animation": item.get("animation", "characters"),
                       "start": item.get("start", .65), "duration": item.get("duration", .25)})
    return layers


def sample(p, scene_id, background=None):
    scene = p.scene(scene_id)
    require(scene.get("visual_text"), "请选一个包含 visual_text 的关键镜头")
    size = (p.data["config"]["width"], p.data["config"]["height"])
    # One sample approves a shared font; validate every authored text slot first.
    for other in p.scenes():
        if other["scene_id"] != scene_id:
            layout(p, other, size)
    layers = layout(p, scene, size)
    dest = p.path("previews/typography-background.png")
    source = Path(background) if background else p.path(f"scenes/{scene_id}/image.png")
    if source.exists():
        with Image.open(source) as im:
            require(abs(im.width/im.height-size[0]/size[1]) < .01, "样图背景比例与项目画幅不符")
            im.convert("RGB").resize(size).save(dest)
    else:
        require(background is None, "样图背景不存在")
        Image.new("RGB", size, p.data["config"]["canvas_hex"]).save(dest)
    from .text_render import TextOverlay
    overlay = TextOverlay(layers, 1000, 30)
    frame = np.asarray(Image.open(dest).convert("RGB"))[:,:,::-1].copy()
    overlay.paint(frame, 1000)
    path = p.path("previews/typography-sample.png")
    Image.fromarray(frame[:,:,::-1]).save(path)
    p.save("style/typography-sample.json", {"inputs": inputs(p), "scene": scene_id,
           "image_sha256": file_hash(path), "background": "previews/typography-background.png",
           "background_sha256": file_hash(dest)})
    return {"image": str(path), "digest": approval_target(p), "approval_required": True}


def create_background(p, scene_id):
    scene = p.scene(scene_id)
    require(scene.get("visual_mode") == "text_only", "仅纯文字镜头可生成空白底图")
    ready(p)
    dest = p.path(f"scenes/{scene_id}/image.png")
    require(not dest.exists(), "底图已存在，保留现有素材；需要替换时请使用 asset --replace")
    Image.new("RGB", (p.data["config"]["width"], p.data["config"]["height"]),
              p.data["config"]["canvas_hex"]).save(dest)
    return {"path": str(dest), "visual_review_required": True}
