#!/usr/bin/env python3
"""
SRT 白板动画 - 整合渲染器（mask 编排 + stream 画法）

把一张线稿图 + 同名 annotation.json 渲染成白板手绘动画：
  - 编排沿用 whiteboard-mask-animation：按 sequence/startMs 顺序逐区域揭示，
    每个区域的可作画范围 = 矩形 region 扣除「后续区域 + protectedRegions」，
    未开始的区域因掩码限制不会提前露线（mask 的核心不变量）。
  - 画法换成 whiteboard-stream-animation：每个区域在自己的允许掩码内，
    沿真实轮廓笔迹连续落墨（起笔 ink → 添彩 color），笔尖跟随真实笔迹，
    所有区域共享同一张持久画布，已画完的区域保留在画布上。

与 mask 的矩形擦除揭示不同：这里是「笔尖沿线滑行、边走边落墨」的连贯笔迹。
输出末行打印 OUTPUT=<路径>，便于上层捕获。

用法：
  <ENV_PY> render_stream_whiteboard.py <图片> <标注json> <输出mp4> [手部素材png]
  可选参数见 --help（--ink-path / --color-fill / --pause / --total-ms 等）。
  --total-ms 缺省时用标注里的 sceneDurationMs。
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import sys
from dataclasses import dataclass
from bisect import bisect_left
from pathlib import Path

import cv2
import numpy as np

# 复用 stream 渲染器的全部构件（同目录）
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
import stream_render as sr  # noqa: E402
import fountain_pen as fp  # noqa: E402

DEFAULT_HAND = _SCRIPT_DIR.parent / "assets" / "drawing-hand.png"


def validate_drawing_layers(annotation: dict) -> None:
    """Layers are ordered back-to-front; every layer is drawn and filled once."""
    if "layers" not in annotation:
        if any("layer_id" in element for element in annotation.get("elements", [])):
            raise ValueError("layer_id 必须引用 layers 中的独立图层")
        return
    layers = annotation["layers"]
    if not isinstance(layers, list) or not layers:
        raise ValueError("layers 必须包含独立背景及前景图层")
    ids = []
    for layer in layers:
        if not isinstance(layer, dict) or not isinstance(layer.get("id"), str) or not layer["id"]:
            raise ValueError("图层必须有非空 id")
        if not isinstance(layer.get("image"), str) or not layer["image"]:
            raise ValueError("图层必须引用独立 PNG 素材")
        ids.append(layer["id"])
    elements = annotation.get("elements", [])
    if len(set(ids)) != len(ids) or [element.get("layer_id") for element in elements] != ids:
        raise ValueError("绘制事件必须按 layers 的背景到前景顺序逐层对应，且每层只绘制一次")
    end = 0
    for element in elements:
        reveal = element.get("reveal", {})
        start, duration = reveal.get("startMs"), reveal.get("durationMs")
        if (not isinstance(start, (int, float)) or not isinstance(duration, (int, float))
                or not math.isfinite(start) or not math.isfinite(duration) or start < end or duration <= 0):
            raise ValueError("图层时间必须连续串行，前一层完成后才能开始下一层")
        if reveal.get("phase", "both") != "both":
            raise ValueError("每个图层必须在同一事件内完成描线和填色，phase 使用 both")
        if element.get("contours") or element.get("holes") or reveal.get("protectedRegions"):
            raise ValueError("分层模式以素材 alpha 为完整轮廓，不再裁切 contours、holes 或保护区")
        end = start + duration


def layer_asset_paths(annotation: dict, base_dir: Path) -> dict[str, Path]:
    validate_drawing_layers(annotation)
    base = base_dir.resolve()
    paths = {}
    for layer in annotation.get("layers", []):
        name = Path(layer["image"])
        path = (base / name).resolve()
        if name.is_absolute() or name.drive or ".." in name.parts or not path.is_relative_to(base):
            raise ValueError("图层素材必须使用镜头目录内的相对路径")
        paths[layer["id"]] = path
    return paths


def load_layer_images(annotation: dict, base_dir: Path) -> dict[str, np.ndarray]:
    images = {}
    canvas = annotation["canvas"]
    for index, (key, path) in enumerate(layer_asset_paths(annotation, base_dir).items()):
        if not path.is_file() or path.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError(f"图层素材缺失或不是 PNG: {path.name}")
        image = sr._imread_any(path, cv2.IMREAD_UNCHANGED)
        if image is None or image.ndim != 3 or image.shape[2] not in (3, 4):
            raise ValueError(f"图层无法解码为 RGB/RGBA: {path.name}")
        if image.shape[:2] != (canvas["height"], canvas["width"]):
            raise ValueError("所有图层素材必须与标注画布尺寸一致")
        if image.shape[2] == 3 and index == 0:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
        if image.shape[2] != 4 or (index > 0 and not np.any(image[:, :, 3] == 0)):
            raise ValueError("前景必须是包含透明区域的 RGBA PNG")
        if not np.any(image[:, :, 3]):
            raise ValueError("图层不能完全透明")
        images[key] = image
    return images


def validate_subject_contours(annotation: dict) -> None:
    """Optional source-pixel polygons; all events use one geometry mode."""
    elements = annotation.get("elements", [])
    if not any("contours" in e for e in elements):
        if any(e.get("reveal", {}).get("phase", "both") != "both" for e in elements):
            raise ValueError("独立描线/填色阶段需要主体 contours")
        return
    width, height = annotation["canvas"]["width"], annotation["canvas"]["height"]
    for e in elements:
        if not isinstance(e.get("contours"), list) or not e["contours"]:
            raise ValueError("主体模式的每个元素必须包含 contours")
        holes = e.get("holes", [])
        if not isinstance(holes, list):
            raise ValueError("holes 必须是多边形数组")
        for polygon in e["contours"] + holes:
            if not isinstance(polygon, list) or len(polygon) < 3:
                raise ValueError("主体轮廓至少需要三个点")
            for point in polygon:
                if (not isinstance(point, (list, tuple)) or len(point) != 2
                        or any(type(v) is not int for v in point)
                        or not (0 <= point[0] <= width and 0 <= point[1] <= height)):
                    raise ValueError("主体轮廓必须使用画布内的整数坐标")
            if cv2.contourArea(np.asarray(polygon, dtype=np.int32)) <= 0:
                raise ValueError("主体轮廓面积必须大于零")
        if e.get("reveal", {}).get("phase", "both") not in ("ink", "color", "both"):
            raise ValueError("绘制 phase 必须是 ink、color 或 both")


# ──────────────────────────────────────────────────────────────
# 区域几何：把标注画布坐标缩放到输出尺寸
# ──────────────────────────────────────────────────────────────
def _scaled_rect(region: dict, sx: float, sy: float, out_w: int, out_h: int) -> tuple[int, int, int, int]:
    x0 = int(round(region["x"] * sx))
    y0 = int(round(region["y"] * sy))
    x1 = int(round((region["x"] + region["width"]) * sx))
    y1 = int(round((region["y"] + region["height"]) * sy))
    x0 = max(0, min(out_w, x0))
    x1 = max(0, min(out_w, x1))
    y0 = max(0, min(out_h, y0))
    y1 = max(0, min(out_h, y1))
    return x0, y0, x1, y1


def _frame_progress_indices(n_steps: int, target_frames: int) -> list[int]:
    """把 n_steps 个笔尖位置均匀映射到 target_frames 帧。"""
    if n_steps == 0 or target_frames <= 0:
        return []
    if target_frames == 1:
        return [n_steps - 1]
    return [round(f * (n_steps - 1) / (target_frames - 1)) for f in range(target_frames)]


@dataclass(frozen=True)
class StrokeGroupPlan:
    strokes: list[list[tuple[int, int]]]
    draw_frames: int
    pause_frames: int


def _stroke_length(stroke: list[tuple[int, int]]) -> float:
    return sum(
        math.hypot(curr[0] - prev[0], curr[1] - prev[1])
        for prev, curr in zip(stroke, stroke[1:])
    )


def _stroke_turn_score(stroke: list[tuple[int, int]]) -> float:
    """返回累计转角，转折越多，绘制权重越高。"""
    if len(stroke) < 3:
        return 0.0
    score = 0.0
    for prev, current, nxt in zip(stroke, stroke[1:], stroke[2:]):
        first = (current[0] - prev[0], current[1] - prev[1])
        second = (nxt[0] - current[0], nxt[1] - current[1])
        first_len = math.hypot(*first)
        second_len = math.hypot(*second)
        if first_len <= 1e-6 or second_len <= 1e-6:
            continue
        cosine = (first[0] * second[0] + first[1] * second[1]) / (first_len * second_len)
        score += math.acos(max(-1.0, min(1.0, cosine)))
    return score


def _stroke_weight(stroke: list[tuple[int, int]], turn_weight: float) -> float:
    length = _stroke_length(stroke)
    turns = _stroke_turn_score(stroke)
    return max(1.0, length + turns * max(0.0, turn_weight) * 12.0 + 8.0)


def _allocate_weighted_frames(
    weights: list[float], total_frames: int, max_each: int | None = None
) -> list[int]:
    """按复杂度分配整数帧，并用最大余数法保持总帧数不变。"""
    if not weights or total_frames <= 0:
        return [0 for _ in weights]
    allocations = [0 for _ in weights]
    available = total_frames
    if max_each is not None:
        max_each = max(0, max_each)
    total_weight = sum(max(0.0, weight) for weight in weights) or float(len(weights))
    raw = [available * max(0.0, weight) / total_weight for weight in weights]
    allocations = [int(value) for value in raw]
    if max_each is not None:
        allocations = [min(value, max_each) for value in allocations]
    if total_frames >= len(allocations):
        for index in range(len(allocations)):
            if allocations[index] == 0:
                allocations[index] = 1
    used = sum(allocations)
    order = sorted(range(len(weights)), key=lambda index: raw[index] - int(raw[index]), reverse=True)
    while used < available:
        changed = False
        for index in order:
            if max_each is not None and allocations[index] >= max_each:
                continue
            allocations[index] += 1
            used += 1
            changed = True
            if used >= available:
                break
        if not changed:
            break
    while used > available:
        index = max(range(len(allocations)), key=lambda item: allocations[item])
        if allocations[index] <= 0:
            break
        allocations[index] -= 1
        used -= 1
    return allocations


# ──────────────────────────────────────────────────────────────
# 每区域的 stream 笔迹渲染，写入共享持久画布
# ──────────────────────────────────────────────────────────────
class RegionStreamRenderer:
    """持有整段渲染的共享状态；逐区域把 stream 笔迹画进同一张画布。"""

    def __init__(self, image_bgr: np.ndarray, annotation: dict, cfg: sr.Config,
                 hand_png: Path | None, bare_tip: bool, max_skeleton_strokes: int = 96,
                 layer_images: dict[str, np.ndarray] | None = None) -> None:
        self.cfg = cfg
        self.ann = annotation
        validate_subject_contours(annotation)
        validate_drawing_layers(annotation)
        self.layered_mode = "layers" in annotation
        self.subject_mode = self.layered_mode or any("contours" in e for e in annotation["elements"])
        self.canvas_bgr = sr._hex_to_bgr(cfg.canvas_hex)
        self.max_skeleton_strokes = max(0, max_skeleton_strokes)
        self.outline_strokes = []

        # 输出尺寸：长边限到 cap，对齐到 grid_edge 的偶数倍（编码要求偶数）
        h0, w0 = image_bgr.shape[:2]
        scale = cfg.cap_long_edge / max(h0, w0)
        align = cfg.grid_edge if cfg.grid_edge % 2 == 0 else cfg.grid_edge * 2
        w = max(align, (int(round(w0 * scale)) // align) * align)
        h = max(align, (int(round(h0 * scale)) // align) * align)
        self.out_w, self.out_h = w, h

        # 标注画布坐标 → 输出坐标的缩放比
        cw = annotation["canvas"]["width"]
        ch = annotation["canvas"]["height"]
        self.sx = self.out_w / cw
        self.sy = self.out_h / ch

        self.color_img = cv2.resize(image_bgr, (self.out_w, self.out_h), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(self.color_img, cv2.COLOR_BGR2GRAY)
        margin = max(3, min(self.out_h, self.out_w) // 40)
        corners = [self.color_img[:margin, :margin], self.color_img[:margin, -margin:],
                   self.color_img[-margin:, :margin], self.color_img[-margin:, -margin:]]
        corner_pixels = np.concatenate([part.reshape(-1, 3) for part in corners])
        background_bgr = np.median(corner_pixels, axis=0).astype(np.uint8)
        self.dark_mode = float(cv2.cvtColor(background_bgr.reshape(1, 1, 3), cv2.COLOR_BGR2GRAY)[0, 0]) < 96
        if self.dark_mode:
            # 深色主题依靠亮度/色彩边缘形成金线和霓虹线，不能再按“黑色像素”提取。
            enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
            edges = cv2.Canny(enhanced, 28, 90, L2gradient=True)
            edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
            self.thresh_map = np.where(edges > 0, 0, 255).astype(np.uint8)
            self.canvas_bgr = background_bgr
        else:
            self.thresh_map = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 10
            )
        self.ink_pixels = self.thresh_map < cfg.ink_threshold
        self.ink_paint = (self.color_img if self.dark_mode else np.repeat(self.thresh_map[:, :, None], 3, axis=2)).astype(np.float32)
        if cfg.pen_type == "fountain" and not self.dark_mode:
            # Match the reference engine: trace visible source ink, not every
            # adaptive-threshold texture edge of a photograph or paper surface.
            blue, green, red = [self.color_img[:, :, c].astype(float) for c in range(3)]
            maximum = self.color_img.max(axis=2)
            cool_ink = (blue >= red + 4) & (blue >= green - 4) & (red < 218)
            neutral_ink = (maximum.astype(float) - self.color_img.min(axis=2)) < 48
            dark = ((maximum < 125) & neutral_ink) | cool_ink
            distance = cv2.distanceTransform(dark.astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
            core = dark & (distance < 5.2)
            neutral_edge = (maximum.astype(float) - self.color_img.min(axis=2) < 32) & (maximum < 235)
            self.ink_pixels = core | ((cv2.dilate(core.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0) & neutral_edge)
            self.ink_paint = self.color_img.astype(np.float32)

        # 背景染成画布底色，让上色阶段背景与起笔一致（不碰墨迹）
        if cfg.match_bg and not self.dark_mode and not self.layered_mode:
            self._match_original_background()
        self.color_img_float = self.color_img.astype(np.float32)

        # 共享持久画布
        self.drawn = np.empty((self.out_h, self.out_w, 3), dtype=np.float32)
        self.drawn[...] = self.canvas_bgr.astype(np.float32)
        self.frame_u8 = np.empty_like(self.color_img)
        self.layer_pixels = {}
        if self.layered_mode:
            expected = [layer["id"] for layer in annotation["layers"]]
            if layer_images is None or set(layer_images) != set(expected):
                raise ValueError("分层绘制需要所有独立图层素材，不能从单张成图推测被遮挡内容")
            self.canvas_bgr = sr._hex_to_bgr(cfg.canvas_hex)
            self.drawn[...] = self.canvas_bgr
            for index, key in enumerate(expected):
                rgba = layer_images[key]
                if not isinstance(rgba, np.ndarray) or rgba.shape != (ch, cw, 4) or rgba.dtype != np.uint8:
                    raise ValueError("图层必须是与标注画布一致的 uint8 RGBA 图像")
                if not np.any(rgba[:, :, 3]) or (index > 0 and not np.any(rgba[:, :, 3] == 0)):
                    raise ValueError("图层不能全透明，前景必须包含透明区域")
                alpha = rgba[:, :, 3:4].astype(np.float32) / 255
                premultiplied = np.concatenate((rgba[:, :, :3] * alpha, alpha), axis=2)
                resized = cv2.resize(premultiplied, (w, h), interpolation=cv2.INTER_AREA)
                self.layer_pixels[key] = resized
            for element in annotation["elements"]:
                reveal = element["reveal"]
                frames = round((reveal["startMs"] + reveal["durationMs"]) * cfg.fps / 1000) - round(reveal["startMs"] * cfg.fps / 1000)
                if frames < 2:
                    raise ValueError("每个图层至少需要两帧以完成描线和填色")
            self.color_img = self.completed_layers_image(float("inf")).astype(np.uint8)
            self.color_img_float = self.color_img.astype(np.float32)

        # 笔尖覆盖
        self.tip: sr.TipOverlay | None = None
        if not bare_tip:
            hand_height = min(cfg.target_hand_height, max(120, round(self.out_h * 0.28)))
            hand_data = sr._load_hand(hand_png, hand_height) if hand_png else None
            ax, ay = cfg.tip_anchor_x, cfg.tip_anchor_y
            if hand_data is None:
                hand_data = sr._procedural_tip(hand_height)
                ax, ay = 0.5, 0.70
            self.tip = sr.TipOverlay(hand_data[0], hand_data[1], tip_anchor_x=ax, tip_anchor_y=ay)

    # 采样原图四角，把接近背景色的像素替换为画布底色
    def _match_original_background(self) -> None:
        img = self.color_img
        h, w = img.shape[:2]
        margin = max(3, min(h, w) // 50)
        samples = [img[:margin, :margin], img[:margin, -margin:],
                   img[-margin:, :margin], img[-margin:, -margin:]]
        bg = np.median(np.concatenate([s.reshape(-1, 3) for s in samples]), axis=0)
        diff = np.abs(img.astype(np.int16) - bg.astype(np.int16)).sum(axis=2)
        img[diff < self.cfg.match_bg_threshold] = self.canvas_bgr


    def _snapshot_with_tip(self, px: int, py: int) -> np.ndarray:
        np.copyto(self.frame_u8, self.drawn, casting="unsafe")
        snap = self.frame_u8
        if self.tip is not None:
            self.tip.stamp(snap, px, py)
        return snap

    def _snapshot(self) -> np.ndarray:
        """把浮点画布转换到可复用的视频帧缓冲，避免每帧分配新数组。"""
        np.copyto(self.frame_u8, self.drawn, casting="unsafe")
        return self.frame_u8

    def completed_layers_image(self, at_ms: float) -> np.ndarray:
        result = np.empty((self.out_h, self.out_w, 3), np.float32)
        result[...] = self.canvas_bgr
        for element in self.ann["elements"]:
            reveal = element["reveal"]
            if reveal["startMs"] + reveal["durationMs"] <= at_ms:
                pixels = self.layer_pixels[element["layer_id"]]
                result = pixels[:, :, :3] + result * (1 - pixels[:, :, 3:4])
        return result

    def prepare_element(self, element: dict) -> None:
        if not self.layered_mode:
            return
        pixels = self.layer_pixels[element["layer_id"]]
        alpha = pixels[:, :, 3:4]
        # The unpainted foreground stays transparent: its background is the
        # already completed lower layers, never blank paper or a white cutout.
        behind = self.drawn.copy()
        self.color_img_float = pixels[:, :, :3] + behind * (1 - alpha)
        self.color_img = self.color_img_float.astype(np.uint8)
        isolated = np.rint(pixels[:, :, :3] + self.canvas_bgr * (1 - alpha)).astype(np.uint8)
        linework = RegionStreamRenderer(isolated, {"canvas": {"width": self.out_w, "height": self.out_h},
                                                   "elements": []}, self.cfg, None, True,
                                        max_skeleton_strokes=self.max_skeleton_strokes)
        self.ink_pixels = linework.ink_pixels & (alpha[:, :, 0] > 0)
        self.ink_paint = linework.ink_paint * alpha + behind * (1 - alpha)
        self.outline_strokes = []
        if self.cfg.pen_type == "fountain" and self.max_skeleton_strokes and np.any(alpha < .5):
            # Transparent subject boundaries are structural, even when the source
            # is a collage with no black linework. Never discard a limb or leaf
            # silhouette just because it is shorter than an interior texture line.
            contours, _ = cv2.findContours((alpha[:, :, 0] > .12).astype(np.uint8),
                                          cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            outline = np.zeros(alpha.shape[:2], np.uint8)
            for contour in contours:
                if cv2.contourArea(contour) < 9:
                    continue
                points = cv2.approxPolyDP(contour, .7, True).reshape(-1, 2)
                if len(points) < 3:
                    continue
                stroke = [tuple(p) for p in points] + [tuple(points[0])]
                self.outline_strokes.append(stroke)
                cv2.polylines(outline, [points], True, 255, 1, cv2.LINE_AA)
            self.outline_strokes = fp.orient(self.outline_strokes)
            coverage = outline.astype(np.float32)[:, :, None] / 255
            # A temporary fine ink outline; color restores the exact layer pixels.
            self.ink_paint = np.where(coverage > 0, behind * (1-coverage) + 35 * coverage, self.ink_paint)
            self.ink_pixels |= outline > 0

    # ── 单区域的允许掩码：矩形 - 后续区域 - protectedRegions ──
    def _allowed_mask(self, element: dict, later_elements: list[dict]) -> np.ndarray:
        if self.layered_mode:
            return self.layer_pixels[element["layer_id"]][:, :, 3] > 0
        mask = np.zeros((self.out_h, self.out_w), dtype=bool)
        if "contours" in element:
            pixels = np.zeros(mask.shape, dtype=np.uint8)
            for key, value in (("contours", 1), ("holes", 0)):
                for polygon in element.get(key, []):
                    points = np.rint(np.asarray(polygon) * [self.sx, self.sy]).astype(np.int32)
                    cv2.fillPoly(pixels, [points], value)
            mask = pixels > 0
            # Explicit subject ownership is independent of later ink/color events.
            for prot in element.get("reveal", {}).get("protectedRegions", []):
                x0, y0, x1, y1 = _scaled_rect(prot, self.sx, self.sy, self.out_w, self.out_h)
                mask[y0:y1, x0:x1] = False
            return mask
        x0, y0, x1, y1 = _scaled_rect(element["region"], self.sx, self.sy, self.out_w, self.out_h)
        mask[y0:y1, x0:x1] = True
        for later in later_elements:
            lx0, ly0, lx1, ly1 = _scaled_rect(later["region"], self.sx, self.sy, self.out_w, self.out_h)
            mask[ly0:ly1, lx0:lx1] = False
        for prot in element.get("reveal", {}).get("protectedRegions", []):
            px0, py0, px1, py1 = _scaled_rect(prot, self.sx, self.sy, self.out_w, self.out_h)
            mask[py0:py1, px0:px1] = False
        return mask


    def _region_skeleton_strokes(self, allowed: np.ndarray) -> list[list[tuple[int, int]]]:
        """骨架模式：沿原图真实墨线追踪，不使用会偏离线条的曲线平滑。"""
        cfg = self.cfg
        region_ink = self.ink_pixels & allowed
        if not region_ink.any():
            return []
        min_points = 4 if self.max_skeleton_strokes == 0 else 10 if self.max_skeleton_strokes >= 96 else 18 if self.max_skeleton_strokes >= 48 else cfg.skeleton_min_points
        if cfg.pen_type == "fountain":
            raw = fp.extract_paths(region_ink)
        else:
            skel = sr._zhang_suen_skeleton(region_ink, max_iterations=160)
            raw = sr.trace_8connected(skel, min_points=min_points)
        if not raw:
            return []
        spacing = min(cfg.skeleton_resample_spacing, 2.5)
        out: list[list[tuple[int, int]]] = []
        for stroke in raw:
            pts = [(float(x), float(y)) for x, y in stroke]
            pts = sr._resample_stroke_points(pts, spacing)
            if len(pts) >= 2 and sr._stroke_cumulative_length(pts)[-1] > 2.0:
                out.append([(int(round(x)), int(round(y))) for x, y in pts])
        # 优先绘制最长的主要轮廓；数量由页面的“线条绘制量”控制。
        out.sort(
            key=lambda stroke: sr._stroke_cumulative_length(
                [(float(x), float(y)) for x, y in stroke]
            )[-1],
            reverse=True,
        )
        selected = out[:self.max_skeleton_strokes] if self.max_skeleton_strokes else out
        if self.outline_strokes:
            boundary = np.zeros(region_ink.shape, np.uint8)
            for stroke in self.outline_strokes:
                cv2.polylines(boundary, [np.rint(stroke).astype(np.int32)], False, 1, 7)
            # Keep a few interior source strokes, without retracing the silhouette.
            interior = [s for s in selected if np.mean([boundary[y, x] for x, y in s]) < .25]
            return self.outline_strokes + fp.orient(interior[:8])
        return fp.orient(selected) if cfg.pen_type == "fountain" else self._order_strokes_continuously(selected)

    @staticmethod
    def _order_strokes_continuously(
        strokes: list[list[tuple[int, int]]],
    ) -> list[list[tuple[int, int]]]:
        """按上一笔的末端选择最近的下一笔，减少断笔之间的远距离跳跃。"""
        remaining = [list(stroke) for stroke in strokes if stroke]
        if len(remaining) <= 1:
            return remaining

        first_index = min(
            range(len(remaining)),
            key=lambda index: (
                min(point[1] for point in remaining[index]),
                min(point[0] for point in remaining[index]),
                -len(remaining[index]),
            ),
        )
        ordered = [remaining.pop(first_index)]
        tail = ordered[0][-1]
        while remaining:
            index, reverse = min(
                (
                    (index, reverse)
                    for index, stroke in enumerate(remaining)
                    for reverse in (False, True)
                ),
                key=lambda item: (
                    (remaining[item[0]][-1 if item[1] else 0][0] - tail[0]) ** 2
                    + (remaining[item[0]][-1 if item[1] else 0][1] - tail[1]) ** 2,
                    -len(remaining[item[0]]),
                ),
            )
            stroke = remaining.pop(index)
            if reverse:
                stroke.reverse()
            ordered.append(stroke)
            tail = stroke[-1]
        return ordered

    # ── 落墨（限制在 allowed 内）──
    def _reveal_ink_segment(self, a: tuple[int, int], b: tuple[int, int], allowed: np.ndarray) -> None:
        thick = max(1, self.cfg.pen_reveal_radius * 2 + 1)
        padding = thick + 1
        x0 = max(0, min(a[0], b[0]) - padding)
        y0 = max(0, min(a[1], b[1]) - padding)
        x1 = min(self.out_w, max(a[0], b[0]) + padding + 1)
        y1 = min(self.out_h, max(a[1], b[1]) + padding + 1)
        if x1 <= x0 or y1 <= y0:
            return
        segment = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
        cv2.line(
            segment,
            (a[0] - x0, a[1] - y0),
            (b[0] - x0, b[1] - y0),
            255,
            thickness=thick,
            lineType=cv2.LINE_AA,
        )
        ink_region = self.ink_pixels[y0:y1, x0:x1]
        allowed_region = allowed[y0:y1, x0:x1]
        revealed = (segment > 0) & ink_region & allowed_region
        drawn_region = self.drawn[y0:y1, x0:x1]
        drawn_region[revealed] = self.ink_paint[y0:y1, x0:x1][revealed]


    @staticmethod
    def _flatten_strokes(
        strokes: list[list[tuple[int, int]]],
    ) -> tuple[list[tuple[int, int]], set[int]]:
        samples: list[tuple[int, int]] = []
        pen_lifts: set[int] = set()
        for stroke_index, stroke in enumerate(strokes):
            if stroke_index > 0:
                pen_lifts.add(len(samples))
            samples.extend(stroke)
        return samples, pen_lifts

    def _group_strokes_for_budget(
        self, strokes: list[list[tuple[int, int]]], group_count: int
    ) -> list[list[list[tuple[int, int]]]]:
        """先按空间邻近关系聚成对象，再按帧数合并相邻对象。"""
        if not strokes:
            return []
        brush_radius = getattr(self.cfg, "brush_radius", 40)
        gap = max(10, min(24, brush_radius // 2))
        bboxes = []
        for stroke in strokes:
            xs = [point[0] for point in stroke]
            ys = [point[1] for point in stroke]
            bboxes.append((min(xs), min(ys), max(xs), max(ys)))

        parents = list(range(len(strokes)))

        def find(index: int) -> int:
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index

        def union(left: int, right: int) -> None:
            left_root = find(left)
            right_root = find(right)
            if left_root != right_root:
                parents[right_root] = left_root

        for left, (left_x0, left_y0, left_x1, left_y1) in enumerate(bboxes):
            for right in range(left + 1, len(bboxes)):
                right_x0, right_y0, right_x1, right_y1 = bboxes[right]
                if (
                    left_x0 - gap <= right_x1
                    and right_x0 - gap <= left_x1
                    and left_y0 - gap <= right_y1
                    and right_y0 - gap <= left_y1
                ):
                    union(left, right)

        natural: list[list[list[tuple[int, int]]]] = []
        natural_indices: dict[int, int] = {}
        for index, stroke in enumerate(strokes):
            root = find(index)
            group_index = natural_indices.setdefault(root, len(natural))
            if group_index == len(natural):
                natural.append([])
            natural[group_index].append(stroke)

        if len(natural) <= max(1, group_count):
            return natural

        groups = [list(group) for group in natural]
        target_count = max(1, min(len(groups), group_count))
        while len(groups) > target_count:
            merge_index = min(
                range(len(groups) - 1),
                key=lambda index: _stroke_weight(groups[index][-1], self.cfg.stroke_turn_weight)
                + _stroke_weight(groups[index + 1][0], self.cfg.stroke_turn_weight),
            )
            groups[merge_index].extend(groups.pop(merge_index + 1))
        return groups

    def _plan_stroke_groups(
        self, strokes: list[list[tuple[int, int]]], total_frames: int
    ) -> list[StrokeGroupPlan]:
        """为笔画组分配绘制帧与抬笔停顿帧。"""
        if not strokes or total_frames <= 0:
            return []
        mode = self.cfg.pause_mode
        if mode == "off":
            pause_ratio = 0.0
        elif mode == "light":
            pause_ratio = self.cfg.stroke_pause_ratio_light
        elif mode == "auto":
            frames_per_stroke = total_frames / max(1, len(strokes))
            pause_ratio = (
                self.cfg.stroke_pause_ratio_heavy
                if frames_per_stroke >= 2.5
                else self.cfg.stroke_pause_ratio_light
                if frames_per_stroke >= 1.5
                else 0.0
            )
        else:
            pause_ratio = self.cfg.stroke_pause_ratio_heavy

        pause_total = min(
            round(total_frames * max(0.0, pause_ratio)),
            max(0, total_frames - min(len(strokes), total_frames)),
        )
        draw_total = max(1, total_frames - pause_total)
        group_count = min(len(strokes), draw_total)
        groups = self._group_strokes_for_budget(strokes, group_count)
        weights = [
            sum(_stroke_weight(stroke, self.cfg.stroke_turn_weight) for stroke in group)
            for group in groups
        ]
        pause_weights = [
            sum(_stroke_turn_score(stroke) + 1.0 for stroke in group)
            for group in groups
        ]
        pause_allocations = _allocate_weighted_frames(
            pause_weights,
            pause_total,
            max_each=max(1, self.cfg.stroke_pause_max_frames),
        )
        actual_pause = sum(pause_allocations)
        draw_allocations = _allocate_weighted_frames(weights, total_frames - actual_pause)
        return [
            StrokeGroupPlan(group, draw_frames, pause_frames)
            for group, draw_frames, pause_frames in zip(
                groups, draw_allocations, pause_allocations
            )
        ]

    def _path_progress_indices(
        self,
        samples: list[tuple[int, int]],
        pen_lifts: set[int],
        target_frames: int,
    ) -> list[int]:
        """沿路径弧长推进，转角位置降低速度而不是匀速跳过。"""
        if not samples or target_frames <= 0:
            return []
        if target_frames == 1:
            return [len(samples) - 1]
        if len(samples) == 1:
            return [0 for _ in range(target_frames)]
        cumulative = [0.0]
        for index in range(1, len(samples)):
            if index in pen_lifts:
                cumulative.append(cumulative[-1])
                continue
            previous = samples[index - 1]
            current = samples[index]
            distance = math.hypot(current[0] - previous[0], current[1] - previous[1])
            turn = 0.0
            if index + 1 < len(samples) and index + 1 not in pen_lifts:
                before = (current[0] - previous[0], current[1] - previous[1])
                after = (samples[index + 1][0] - current[0], samples[index + 1][1] - current[1])
                before_len = math.hypot(*before)
                after_len = math.hypot(*after)
                if before_len > 1e-6 and after_len > 1e-6:
                    cosine = (before[0] * after[0] + before[1] * after[1]) / (before_len * after_len)
                    turn = math.acos(max(-1.0, min(1.0, cosine))) / math.pi
            cumulative.append(
                cumulative[-1] + distance * (1.0 + turn * self.cfg.stroke_turn_weight)
            )
        total = cumulative[-1]
        if total <= 1e-6:
            return _frame_progress_indices(len(samples), target_frames)
        indices: list[int] = []
        for frame in range(target_frames):
            target = total * frame / max(1, target_frames - 1)
            indices.append(min(len(samples) - 1, bisect_left(cumulative, target)))
        indices[-1] = len(samples) - 1
        return indices

    def _lay_ink_strokes(
        self,
        writer,
        frames: int,
        strokes: list[list[tuple[int, int]]],
        allowed: np.ndarray,
    ) -> None:
        """按笔画组逐段落墨，抬笔时只移动笔尖不留下墨迹。"""
        if self.cfg.pen_type == "fountain":
            self._lay_fountain_strokes(writer, frames, strokes, allowed)
            return
        if not strokes:
            for _ in range(frames):
                writer.write(self._snapshot())
            return
        previous_tail: tuple[int, int] | None = None
        for plan in self._plan_stroke_groups(strokes, frames):
            first_point = plan.strokes[0][0]
            for pause_index in range(plan.pause_frames):
                if previous_tail is None:
                    point = first_point
                else:
                    progress = (pause_index + 1) / plan.pause_frames
                    eased = sr._ease_in_out_sine(progress)
                    point = (
                        round(previous_tail[0] + (first_point[0] - previous_tail[0]) * eased),
                        round(previous_tail[1] + (first_point[1] - previous_tail[1]) * eased),
                    )
                writer.write(self._snapshot_with_tip(*point))
            samples, pen_lifts = self._flatten_strokes(plan.strokes)
            self._lay_ink(writer, plan.draw_frames, samples, pen_lifts, allowed)
            previous_tail = plan.strokes[-1][-1]

    def _lay_fountain_strokes(self, writer, frames, strokes, allowed):
        """Whole strokes with reference pressure starts/ends and timed pen lifts."""
        if frames <= 0:
            return
        if not strokes:
            for _ in range(frames):
                writer.write(self._snapshot())
            return
        # Normal detail draws a few complete structural strokes, then color brings
        # in the remaining detail. Explicit full detail (0) retains every stroke.
        if self.max_skeleton_strokes and not self.outline_strokes:
            ranked = sorted(strokes, key=lambda p: sr._stroke_cumulative_length(p)[-1], reverse=True)
            lengths = [sr._stroke_cumulative_length(p)[-1] for p in ranked]
            count = int(np.searchsorted(np.cumsum(lengths), sum(lengths) * .65)) + 1
            strokes = fp.orient(ranked[:min(18, count, self.max_skeleton_strokes)])
        events = self._fountain_events(strokes)
        required = max(1, len(self.outline_strokes))
        while self.max_skeleton_strokes and len(strokes) > required and sum(e[3] for e in events) > frames:
            # Omit fine strokes rather than accelerating or truncating a stroke.
            candidates = range(required, len(strokes)) if self.outline_strokes else range(len(strokes))
            shortest = min(candidates, key=lambda i: sr._stroke_cumulative_length(strokes[i])[-1])
            strokes = strokes[:shortest] + strokes[shortest + 1:]
            events = self._fountain_events(strokes)
        minimum = sum(event[3] for event in events)
        if frames < minimum:
            raise ValueError(f"钢笔逐笔绘制至少需要 {minimum} 帧，当前只有 {frames} 帧；请延长描线时间或简化线稿")
        extra = _allocate_weighted_frames([event[4] for event in events], frames - minimum)
        base = self.drawn.copy()
        held = np.zeros((self.out_h, self.out_w), np.float32)
        ink_allowed = allowed & self.ink_pixels
        for event, addition in zip(events, extra):
            profile, points, index, least, _ = event
            count = least + addition
            if profile == "travel":
                for t in np.linspace(0, 1, count):
                    q = float(fp.distance_fraction(t, "minjerk"))
                    point = points[0] * (1-q) + points[-1] * q
                    writer.write(self._snapshot_with_tip(*np.rint(point).astype(int)))
                continue
            lengths = fp.weighted_lengths(points)
            radii = self.cfg.pen_reveal_radius * fp.taper(points)
            hashed = (math.sin((index + 7) * 12.9898 + 4.1414) * 43758.5453) % 1
            opacity = np.clip((.9 + .1 * hashed) * (1 + .05 * np.sin(np.linspace(0, 3, len(points)) + index)), 0, 1)
            last = -1
            for t in np.linspace(0, 1, count):
                distance = float(fp.distance_fraction(t, profile)) * lengths[-1]
                end = min(len(points)-1, int(np.searchsorted(lengths, distance, side="right")-1))
                for k in range(last+1, end+1):
                    fp.stamp_source(self.drawn, base, self.ink_paint, ink_allowed, held, points[k], radii[k], opacity[k])
                tip = np.array([np.interp(distance, lengths, points[:, c]) for c in (0, 1)])
                fp.stamp_source(self.drawn, base, self.ink_paint, ink_allowed, held, tip,
                                float(np.interp(distance, lengths, radii)), float(np.interp(distance, lengths, opacity)))
                writer.write(self._snapshot_with_tip(*np.rint(tip).astype(int)))
                last = end

    @staticmethod
    def _fountain_events(strokes):
        events = []
        previous = None
        for index, stroke in enumerate(strokes):
            points = np.asarray(sr._resample_stroke_points(stroke, .6), float)
            if previous is not None:
                distance = float(np.linalg.norm(points[0] - previous))
                events.append(("travel", np.array([previous, points[0]]), None,
                               max(2, math.ceil(1.875 * distance / 120) + 1), distance * .4))
            lengths = fp.weighted_lengths(points)
            profile = "plateau" if lengths[-1] >= 60 else "minjerk"
            minimum = max(2, math.ceil(fp.PEAK[profile] * lengths[-1] / 80) + 1)
            events.append((profile, points, index, minimum, max(1., lengths[-1])))
            previous = points[-1]
        return events

    # ── 起笔段（骨架模式）：沿笔迹逐段揭原图墨迹，无块填充 ──
    def _lay_ink(self, writer, frames: int, samples: list[tuple[int, int]],
                 pen_lifts: set[int], allowed: np.ndarray) -> None:
        if frames <= 0:
            return
        n = len(samples)
        if n == 0:
            for _ in range(frames):
                writer.write(self._snapshot_with_tip(self.out_w // 2, self.out_h // 2))
            return
        idx_for_frame = self._path_progress_indices(samples, pen_lifts, frames)
        last: int | None = None
        for si in idx_for_frame:
            for k in range(0 if last is None else last + 1, si + 1):
                if k == 0 or k in pen_lifts:
                    self._reveal_ink_segment(samples[k], samples[k], allowed)
                else:
                    self._reveal_ink_segment(samples[k - 1], samples[k], allowed)
            sx, sy = samples[si]
            # 换笔时可以瞬移到下一条线，但显示时笔尖始终落在真实骨架坐标上。
            writer.write(self._snapshot_with_tip(sx, sy))
            last = si


    def _reveal_color_segment(self, a, b, allowed, radius=None):
        """Lay color only under the existing pen's continuous round-ended stroke."""
        radius = max(1, self.cfg.pen_reveal_radius) if radius is None else radius
        padding = radius + 1
        x0, x1 = max(0, min(a[0], b[0]) - padding), min(self.out_w, max(a[0], b[0]) + padding + 1)
        y0, y1 = max(0, min(a[1], b[1]) - padding), min(self.out_h, max(a[1], b[1]) + padding + 1)
        if x1 <= x0 or y1 <= y0:
            return
        stroke = np.zeros((y1-y0, x1-x0), np.uint8)
        cv2.line(stroke, (a[0]-x0,a[1]-y0), (b[0]-x0,b[1]-y0), 1, radius*2+1, cv2.LINE_8)
        touched = (stroke > 0) & allowed[y0:y1,x0:x1]
        self.drawn[y0:y1,x0:x1][touched] = self.color_img_float[y0:y1,x0:x1][touched]

    def _wash_subject(self, writer, frames: int, allowed: np.ndarray) -> None:
        """Draw real color strokes; the pen position and revealed path share one clock."""
        if frames <= 0:
            return
        changed = allowed & np.any(self.drawn != self.color_img_float, axis=2)
        if self.cfg.pen_type == "fountain":
            self._wash_quick_subject(writer, frames, changed)
            return
        strokes = sr._paint_strokes(changed, max(1, self.cfg.pen_reveal_radius))
        samples = []
        travel = set()
        for stroke in strokes:
            points = [stroke[0]]
            for a,b in zip(stroke,stroke[1:]):
                points.extend(sr._resample_stroke_points([a,b], max(1, self.cfg.sample_step))[1:])
            if samples:
                movement = sr._resample_stroke_points([samples[-1], points[0]], max(1, self.cfg.sample_step))[1:]
                for x,y in movement:
                    travel.add(len(samples))
                    samples.append((round(x), round(y)))
            samples.extend((round(x), round(y)) for x,y in points)
        if not samples:
            for _ in range(frames):
                writer.write(self._snapshot())
            return
        last = None
        for index in self._path_progress_indices(samples, set(), frames):
            for step in range(0 if last is None else last + 1, index + 1):
                if step in travel:
                    continue
                if step == 0:
                    self._reveal_color_segment(samples[step], samples[step], changed)
                else:
                    self._reveal_color_segment(samples[step-1], samples[step], changed)
            writer.write(self._snapshot_with_tip(*samples[index]))
            last = index

    def _wash_quick_subject(self, writer, frames, changed):
        """Four symbolic left/right passes, clipped to this subject, without blur."""
        ys, xs = np.nonzero(changed)
        if not len(xs):
            for _ in range(frames):
                writer.write(self._snapshot())
            return
        left, right, top, bottom = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
        radius = max(self.cfg.pen_reveal_radius, math.ceil((bottom-top) / 6) + 1)
        route = []
        for index, y in enumerate(np.linspace(top, bottom, 4)):
            a, b = (left, right) if index % 2 == 0 else (right, left)
            route.extend([(a, round(y)), (b, round(y))])
        samples = sr._resample_stroke_points(route, 2)
        active_frames = min(frames, max(1, round(self.cfg.fps * .6)))
        last = 0
        for end in np.linspace(0, len(samples)-1, active_frames + 1)[1:]:
            end = round(end)
            for k in range(last, end+1):
                a, b = samples[max(0,k-1)], samples[k]
                self._reveal_color_segment(tuple(np.rint(a).astype(int)), tuple(np.rint(b).astype(int)), changed, radius)
            writer.write(self._snapshot_with_tip(*np.rint(samples[end]).astype(int)))
            last = end+1
        for _ in range(frames-active_frames):
            writer.write(self._snapshot())

    # ── 主渲染 ──
    def render_to(self, raw_path: Path, total_ms: int, *, writer=None, paths=None) -> Path:
        cfg = self.cfg
        elements = sorted(self.ann["elements"], key=lambda e: e["reveal"]["startMs"])
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        if writer is None:
            writer = cv2.VideoWriter(str(raw_path), fourcc, cfg.fps, (self.out_w, self.out_h))
        if not writer.isOpened():
            raise RuntimeError("无法打开视频写入器")

        cur_ms = 0.0
        ms_per_frame = 1000.0 / cfg.fps

        def fill_static(until_ms: float) -> None:
            nonlocal cur_ms
            n = int(round((until_ms - cur_ms) / ms_per_frame))
            if n <= 0:
                return
            snap = self._snapshot()
            for _ in range(n):
                writer.write(snap)
            cur_ms += n * ms_per_frame

        try:
            for idx, element in enumerate(elements):
                reveal = element["reveal"]
                start_ms = reveal["startMs"]
                dur_ms = reveal["durationMs"]
                fill_static(start_ms)

                self.prepare_element(element)

                allowed = self._allowed_mask(element, elements[idx + 1:])
                phase = reveal.get("phase", "both")
                end_frame = round((start_ms + dur_ms) * cfg.fps / 1000)
                frames = max(0, end_frame - round(cur_ms * cfg.fps / 1000))
                ink_frames = frames if phase == "ink" else 0 if phase == "color" else frames // 2
                if phase == "both" and cfg.pen_type == "fountain" and self.max_skeleton_strokes:
                    ink_frames = min(max(1, round(frames * .3)), round(cfg.fps * 2.5)) if frames > 1 else 0
                color_frames = frames - ink_frames
                if ink_frames:
                    strokes = paths[idx] if paths is not None else self._region_skeleton_strokes(allowed)
                    if phase == "both" and cfg.pen_type == "fountain" and self.max_skeleton_strokes and strokes:
                        longest = max(strokes, key=lambda p: sr._stroke_cumulative_length(p)[-1])
                        essential = strokes[:len(self.outline_strokes)] if self.outline_strokes else [longest]
                        minimum = sum(e[3] for e in self._fountain_events(essential))
                        # The quick timing is a target, not a hard cap that makes
                        # a long contour impossible even in a long scene at low fps.
                        ink_frames = min(max(ink_frames, minimum), frames - 1)
                        color_frames = frames - ink_frames
                    self._lay_ink_strokes(writer, ink_frames, strokes, allowed)
                if color_frames:
                    self._wash_subject(writer, color_frames, allowed)
                cur_ms += frames * ms_per_frame
                fill_static(start_ms + dur_ms)

            # Keep the completed stroke canvas; never reveal the original in one step.
            fill_static(total_ms)
        finally:
            writer.release()
        return raw_path


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="SRT 白板动画整合渲染器（mask 编排 + stream 画法）")
    p.add_argument("image", help="线稿图路径")
    p.add_argument("annotation", help="同名 annotation.json 路径")
    p.add_argument("output", help="输出 MP4 路径")
    p.add_argument("hand", nargs="?", default=None, help="自定义手部素材 PNG（优先于内置画笔素材）")
    p.add_argument("--pen-type", default="marker", choices=["marker", "fountain"], help="画笔：马克笔或钢笔")
    p.add_argument("--total-ms", type=int, default=None, help="总时长；缺省用标注 sceneDurationMs")
    p.add_argument("--bare-tip", action="store_true", help="不叠加笔尖/手部")
    p.add_argument("--ink-path", default="skeleton", choices=["grid", "skeleton"],
                   help="沿轮廓骨架描线；旧 grid 参数统一使用轮廓描线")
    p.add_argument("--color-fill", default="paint", choices=["contour", "paint", "contour-wipe", "brush"],
                   help="沿用现有画笔左右往返、由上向下沿笔尖路径连续落色；旧参数统一使用此画法")
    p.add_argument("--pause", default="heavy", choices=["heavy", "auto", "light", "off"],
                   help="起笔段停顿节奏（预留，逐区域画法下影响较弱）")
    p.add_argument("--fps", type=int, default=None)
    p.add_argument("--grid-edge", type=int, default=None)
    p.add_argument("--brush-radius", type=int, default=None)
    p.add_argument("--cap-long-edge", type=int, default=None,
                   help="输出长边像素上限（预览可调小加速，默认 1080）")
    p.add_argument("--stroke-detail", default="detailed",
                   choices=["light", "standard", "detailed", "full"],
                   help="手绘线条量: light 24条; standard 48条; detailed 96条; full 全部")
    p.add_argument("--keep-raw", action="store_true",
                   help="保留渲染器的 mp4v 中间视频，交给最终音画合成阶段统一转码")
    return p.parse_args(argv)


def _build_cfg(args) -> sr.Config:
    kw: dict = {}
    kw["pen_type"] = args.pen_type
    if args.fps is not None:
        kw["fps"] = args.fps
    if args.grid_edge is not None:
        kw["grid_edge"] = args.grid_edge
    if args.brush_radius is not None:
        kw["brush_radius"] = args.brush_radius
    if args.cap_long_edge is not None:
        kw["cap_long_edge"] = args.cap_long_edge
    kw["ink_path_mode"] = args.ink_path
    kw["color_fill"] = args.color_fill
    kw["pause_mode"] = args.pause
    return sr.Config(**kw)


def main(argv=None) -> int:
    args = _parse_args(argv)
    cfg = _build_cfg(args)

    print("=" * 56)
    print("SRT 白板动画整合渲染器 (mask 编排 + stream 画法)")
    print("=" * 56)

    image_bgr = sr._imread_any(args.image)
    if image_bgr is None:
        print(f"[err] 无法读取图片: {args.image}")
        return 1
    try:
        annotation = json.loads(Path(args.annotation).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[err] 无法读取标注: {e}")
        return 1
    if not annotation.get("elements"):
        print("[err] 标注中没有 elements")
        return 1

    total_ms = args.total_ms if args.total_ms is not None else annotation.get("sceneDurationMs")
    if not total_ms:
        last = max(e["reveal"]["startMs"] + e["reveal"]["durationMs"] for e in annotation["elements"])
        total_ms = last + 1000

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path = out_path.with_name(out_path.stem + "_raw.mp4")

    hand_png = Path(args.hand) if args.hand else (
        DEFAULT_HAND.with_name("drawing-hand-fountain.png") if cfg.pen_type == "fountain" else DEFAULT_HAND)
    stroke_limits = {"light": 24, "standard": 48, "detailed": 96, "full": 0}
    renderer = RegionStreamRenderer(
        image_bgr, annotation, cfg, hand_png, args.bare_tip,
        max_skeleton_strokes=stroke_limits[args.stroke_detail],
        layer_images=load_layer_images(annotation, Path(args.annotation).parent),
    )
    print(f"  输入: {args.image}")
    print(f"  输出尺寸: {renderer.out_w}x{renderer.out_h}, 帧率: {cfg.fps}")
    print(f"  区域数: {len(annotation['elements'])}, 总时长: {total_ms}ms, "
          f"笔迹: {cfg.ink_path_mode}, 线条量: {args.stroke_detail}, 上色: {cfg.color_fill}")

    renderer.render_to(raw_path, total_ms)
    final = raw_path if args.keep_raw else sr.transcode_h264(raw_path, out_path)
    if args.keep_raw:
        raw_path.replace(out_path)
        final = out_path

    size_mb = final.stat().st_size / (1024 * 1024)
    print(f"\n最终视频: {final}  ({size_mb:.2f} MB)")
    print("=" * 56)
    print(f"OUTPUT={final}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
