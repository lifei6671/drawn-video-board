#!/usr/bin/env python3
"""
SRT 白板动画 - 整合渲染器（mask 编排 + stream 画法）

把一张线稿图 + 同名 annotation.json 渲染成白板手绘动画：
  - 编排沿用 whiteboard-mask-animation：按 sequence/startMs 顺序逐区域揭示，
    每个区域的可作画范围 = 矩形 region 扣除「后续区域 + protectedRegions」，
    未开始的区域因掩码限制不会提前露线（mask 的核心不变量）。
  - 画法换成 whiteboard-stream-animation：每个区域在自己的允许掩码内，
    沿骨架/网格笔迹连续落墨（起笔 ink → 添彩 color），笔尖跟随真实笔迹，
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
from pathlib import Path

import cv2
import numpy as np

# 复用 stream 渲染器的全部构件（同目录）
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
import stream_render as sr  # noqa: E402

DEFAULT_HAND = _SCRIPT_DIR.parent / "assets" / "drawing-hand.png"


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
                 hand_png: Path | None, bare_tip: bool, max_skeleton_strokes: int = 96) -> None:
        self.cfg = cfg
        self.ann = annotation
        validate_subject_contours(annotation)
        self.subject_mode = any("contours" in e for e in annotation["elements"])
        self.canvas_bgr = sr._hex_to_bgr(cfg.canvas_hex)
        self.max_skeleton_strokes = max(0, max_skeleton_strokes)

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
        self.grid_blocks = sr._to_grid_blocks(self.thresh_map, cfg.grid_edge)
        self.active_all = sr._active_mask(self.thresh_map, cfg.grid_edge, cfg.ink_threshold)
        self.ink_pixels = self.thresh_map < cfg.ink_threshold
        self.ink_paint = (self.color_img if self.dark_mode else np.repeat(self.thresh_map[:, :, None], 3, axis=2)).astype(np.float32)

        # 背景染成画布底色，让上色阶段背景与起笔一致（不碰墨迹）
        if cfg.match_bg and not self.dark_mode:
            self._match_original_background()
        self.color_img_float = self.color_img.astype(np.float32)

        # 共享持久画布
        self.drawn = np.empty((self.out_h, self.out_w, 3), dtype=np.float32)
        self.drawn[...] = self.canvas_bgr.astype(np.float32)
        self.frame_u8 = np.empty_like(self.color_img)

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

    def _cell_center(self, cell: tuple[int, int]) -> tuple[int, int]:
        r, c = cell
        e = self.cfg.grid_edge
        return (c * e + e // 2, r * e + e // 2)

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

    # ── 单区域的允许掩码：矩形 - 后续区域 - protectedRegions ──
    def _allowed_mask(self, element: dict, later_elements: list[dict]) -> np.ndarray:
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

    # ── 区域内笔迹路径 ──
    def _region_grid_path(self, allowed: np.ndarray) -> list[tuple[int, int]]:
        """网格模式：把区域内含墨的格聚类并串成连续格路径。"""
        allowed_u8 = allowed.astype(np.uint8)
        allowed_cell = sr._to_grid_blocks(allowed_u8, self.cfg.grid_edge).any(axis=(2, 3))
        active = self.active_all & allowed_cell
        if not active.any():
            return []
        streams = sr.cluster_ink_streams(active)
        return sr.flatten_streams(streams)

    def _region_skeleton_strokes(self, allowed: np.ndarray) -> list[list[tuple[int, int]]]:
        """骨架模式：沿原图真实墨线追踪，不使用会偏离线条的曲线平滑。"""
        cfg = self.cfg
        region_ink = self.ink_pixels & allowed
        if not region_ink.any():
            return []
        skel = sr._zhang_suen_skeleton(region_ink, max_iterations=160)
        min_points = 4 if self.max_skeleton_strokes == 0 else 10 if self.max_skeleton_strokes >= 96 else 18 if self.max_skeleton_strokes >= 48 else cfg.skeleton_min_points
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
        return self._order_strokes_continuously(selected)

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
        thick = max(1, self.cfg.ink_reveal_radius * 2 + 1)
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

    def _ink_stamp_cell(self, cell: tuple[int, int], allowed: np.ndarray) -> None:
        r, c = cell
        e = self.cfg.grid_edge
        block = self.grid_blocks[r, c]
        allow_block = allowed[r * e:r * e + e, c * e:c * e + e]
        ink_region = (block < self.cfg.ink_threshold) & allow_block
        paint = np.repeat(block[:, :, None], 3, axis=2)
        target = self.drawn[r * e:r * e + e, c * e:c * e + e]
        target[ink_region] = paint[ink_region]

    def _color_stamp(self, px: int, py: int, disk: np.ndarray, allowed: np.ndarray) -> None:
        radius = self.cfg.brush_radius
        h, w = self.out_h, self.out_w
        y0, y1 = max(0, py - radius), min(h, py + radius + 1)
        x0, x1 = max(0, px - radius), min(w, px + radius + 1)
        if y1 <= y0 or x1 <= x0:
            return
        by0, by1 = y0 - (py - radius), disk.shape[0] - ((py + radius + 1) - y1)
        bx0, bx1 = x0 - (px - radius), disk.shape[1] - ((px + radius + 1) - x1)
        m = disk[by0:by1, bx0:bx1] * allowed[y0:y1, x0:x1]
        inv = 1.0 - m
        target = self.drawn[y0:y1, x0:x1]
        source = self.color_img_float[y0:y1, x0:x1]
        for ch in range(3):
            target[:, :, ch] = target[:, :, ch] * inv + source[:, :, ch] * m

    def _complete_region_color(self, allowed: np.ndarray) -> None:
        """填色阶段收尾时补齐当前分镜，避免局部扫描留下空白。"""
        self.drawn[allowed] = self.color_img_float[allowed]

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
            index = 0
            while index < len(cumulative) - 1 and cumulative[index] < target:
                index += 1
            indices.append(index)
        return indices

    def _lay_ink_strokes(
        self,
        writer,
        frames: int,
        strokes: list[list[tuple[int, int]]],
        allowed: np.ndarray,
    ) -> None:
        """按笔画组逐段落墨，抬笔时只移动笔尖不留下墨迹。"""
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
            if last is None:
                self._reveal_ink_segment(samples[si], samples[si], allowed)
            else:
                for k in range(last + 1, si + 1):
                    if k in pen_lifts:
                        continue
                    self._reveal_ink_segment(samples[k - 1], samples[k], allowed)
            sx, sy = samples[si]
            # 换笔时可以瞬移到下一条线，但显示时笔尖始终落在真实骨架坐标上。
            writer.write(self._snapshot_with_tip(sx, sy))
            last = si

    # ── 添彩段：brush 或 contour-wipe，限制在 allowed 内 ──
    def _wash_brush(self, writer, frames: int, centers: list[tuple[int, int]], allowed: np.ndarray) -> None:
        if frames <= 0:
            return
        n = len(centers)
        if n == 0:
            for _ in range(frames):
                writer.write(self._snapshot_with_tip(self.out_w // 2, self.out_h // 2))
            return
        disk = sr._feathered_disk(self.cfg.brush_radius)
        idx_for_frame = _frame_progress_indices(n, frames)
        last: int | None = None
        for ci in idx_for_frame:
            if last is None:
                self._color_stamp(*centers[ci], disk, allowed)
            else:
                for k in range(last + 1, ci + 1):
                    self._color_stamp(*centers[k], disk, allowed)
            writer.write(self._snapshot())
            last = ci

    def _paint_mask(self, allowed: np.ndarray) -> np.ndarray:
        """提取当前分镜中真正有颜色的像素，排除黑色线稿。"""
        canvas = self.canvas_bgr.astype(np.int16)
        color_diff = np.abs(self.color_img.astype(np.int16) - canvas).sum(axis=2)
        threshold = max(18, self.cfg.match_bg_threshold)
        foreground = color_diff >= threshold
        hsv = cv2.cvtColor(self.color_img, cv2.COLOR_BGR2HSV)
        foreground &= hsv[:, :, 1] >= 40
        ink = (self.ink_pixels.astype(np.uint8) * 255)
        radius = max(1, min(2, self.cfg.brush_radius // 20))
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1)
        )
        line_guard = cv2.dilate(ink, kernel, iterations=1) > 0
        return allowed & foreground & ~line_guard

    def _paint_component_routes(
        self, paint_mask: np.ndarray
    ) -> list[tuple[np.ndarray, list[tuple[int, int]]]]:
        """把颜色分成空间连通的对象，并为每个对象生成短往返笔触。"""
        mask_u8 = paint_mask.astype(np.uint8) * 255
        bridge = max(3, min(9, self.cfg.brush_radius // 5))
        if bridge % 2 == 0:
            bridge += 1
        grouped = cv2.morphologyEx(
            mask_u8,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (bridge, bridge)),
        )
        count, labels, stats, _ = cv2.connectedComponentsWithStats(grouped, 8)
        components: list[tuple[np.ndarray, list[tuple[int, int]], int, int, int]] = []
        spacing = max(3, self.cfg.brush_radius // 2)
        for label in range(1, count):
            x, y, width, height, _ = stats[label]
            component = paint_mask & (labels == label)
            if int(component.sum()) < max(4, spacing):
                continue
            route: list[tuple[int, int]] = []
            forward = True
            for py in range(int(y), int(y + height), spacing):
                row_xs = np.where(component[py])[0]
                if row_xs.size == 0:
                    continue
                left = int(row_xs.min())
                right = int(row_xs.max())
                lane = list(range(left, right + 1, spacing))
                if not lane or lane[-1] != right:
                    lane.append(right)
                if not forward:
                    lane.reverse()
                route.extend((px, int(py)) for px in lane)
                forward = not forward
            if not route:
                ys, xs = np.where(component)
                route = [(int(xs[len(xs) // 2]), int(ys[len(ys) // 2]))]
            components.append((component, route, int(-component.sum()), int(y), int(x)))
        components.sort(key=lambda item: (item[2], item[3], item[4]))
        return [(component, route) for component, route, _, _, _ in components]

    def _wash_paint(self, writer, frames: int, allowed: np.ndarray) -> None:
        """逐个颜色对象用短往返笔触填色，而不是扫描整个分镜。"""
        if frames <= 0:
            return
        paint_mask = self._paint_mask(allowed)
        components = self._paint_component_routes(paint_mask)
        if not components:
            for _ in range(frames):
                writer.write(self._snapshot())
            return
        disk = sr._feathered_disk(self.cfg.brush_radius)
        allocations = _allocate_weighted_frames(
            [len(route) for _, route in components], frames
        )
        emitted = 0
        for (component, route), component_frames in zip(components, allocations):
            if component_frames <= 0:
                continue
            indices = _frame_progress_indices(len(route), component_frames)
            last: int | None = None
            for route_index in indices:
                if last is None:
                    self._color_stamp(*route[route_index], disk, component)
                else:
                    for route_step in range(last + 1, route_index + 1):
                        self._color_stamp(*route[route_step], disk, component)
                emitted += 1
                if emitted == frames:
                    self.drawn[allowed] = self.color_img_float[allowed]
                writer.write(self._snapshot_with_tip(*route[route_index]))
                last = route_index

    def _wash_contour(self, writer, frames: int, allowed: np.ndarray) -> None:
        if frames <= 0:
            return
        cfg = self.cfg
        ys_all, xs_all = np.where(allowed)
        if ys_all.size == 0:
            for _ in range(frames):
                writer.write(self._snapshot())
            return
        top, bottom = int(ys_all.min()), int(ys_all.max())
        left, right = int(xs_all.min()), int(xs_all.max())
        region_h = bottom - top + 1
        region_w = right - left + 1

        # 区域内的阻力场（墨线膨胀 + 模糊 + 逐行向下衰减）
        ink_u8 = ((self.ink_pixels & allowed)[top:bottom + 1, left:right + 1].astype(np.uint8)) * 255
        spread = int(np.clip(min(region_w, region_h) // 32, 3, 17))
        if spread % 2 == 0:
            spread = max(3, spread - 1)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (spread, spread))
        dilated = cv2.dilate(ink_u8, kernel, iterations=1)
        blur_r = max(1, int(round(min(region_w, region_h) / 220.0)))
        if blur_r % 2 == 0:
            blur_r += 1
        resistance = cv2.GaussianBlur(dilated, (blur_r, blur_r), 0).astype(np.float32)
        peak = float(resistance.max())
        resistance = resistance / peak if peak > 1e-6 else np.zeros_like(resistance)
        decay = cfg.wipe_decay
        for row in range(1, region_h):
            resistance[row] = np.maximum(resistance[row], resistance[row - 1] * decay)

        wave = sr._build_wipe_wave(region_w)
        delay_px = int(np.clip(region_h * cfg.wipe_delay_ratio, 12, 52))
        ys = np.arange(region_h, dtype=np.float32)[:, None]
        sweep = region_h + 2 * delay_px
        blocks = max(1, cfg.wipe_blocks)

        allowed_crop = allowed[top:bottom + 1, left:right + 1]
        color_crop = self.color_img_float[top:bottom + 1, left:right + 1]
        drawn_crop = self.drawn[top:bottom + 1, left:right + 1]

        for fi in range(frames):
            progress = 1.0 if frames == 1 else fi / (frames - 1)
            lead = sr._ease_in_out_sine(progress) * sweep - delay_px
            threshold = lead + wave[None, :] - resistance * delay_px
            reveal = (ys <= threshold) & allowed_crop
            drawn_crop[reveal] = color_crop[reveal]

            lane = sr._ease_in_out_sine((fi / blocks * 2.0) % 1.0)
            forward = (int(fi // blocks) % 2 == 0)
            cx = int(lane * region_w) if forward else int((1.0 - lane) * region_w)
            cx = max(0, min(region_w - 1, cx))
            col = np.where(reveal[:, cx])[0]
            cy = int(col[-1]) if col.size > 0 else 0
            if fi == frames - 1:
                drawn_crop[allowed_crop] = color_crop[allowed_crop]
            writer.write(self._snapshot())

        # 收尾：确保区域内允许像素全部揭示
        drawn_crop[allowed_crop] = color_crop[allowed_crop]

    # ── 网格路径的采样计划（插值 + 抬笔 + 块填充索引）──
    def _grid_plan(self, path: list[tuple[int, int]]):
        samples: list[tuple[int, int]] = []
        pen_lifts: set[int] = set()
        sample_cell: list[int] = []
        for idx, cell in enumerate(path):
            cx, cy = self._cell_center(cell)
            if idx == 0:
                samples.append((cx, cy))
                sample_cell.append(idx)
                continue
            prev_cell = path[idx - 1]
            prev = self._cell_center(prev_cell)
            if math.hypot(cell[0] - prev_cell[0], cell[1] - prev_cell[1]) > math.sqrt(2):
                pen_lifts.add(len(samples))
                samples.append((cx, cy))
                sample_cell.append(idx)
                continue
            steps = max(1, int(math.hypot(cx - prev[0], cy - prev[1]) / self.cfg.sample_step))
            for s in range(1, steps + 1):
                samples.append((int(prev[0] + (cx - prev[0]) * s / steps),
                                int(prev[1] + (cy - prev[1]) * s / steps)))
                sample_cell.append(idx)
        return samples, pen_lifts, sample_cell

    def _wash_subject(self, writer, frames: int, allowed: np.ndarray) -> None:
        """Opaque short serpentine strokes inside the silhouette, including gray fills.

        Every changed pixel belongs to a stroke budget; no end-of-region patch or
        final full-image replacement is needed. Existing ink is retained until its
        original antialiased color is restored by the fill pass.
        """
        changed = allowed & np.any(self.drawn != self.color_img_float, axis=2)
        ys, xs = np.where(changed)
        band = max(2, self.cfg.brush_radius // 2)
        lanes = ys // band
        along = np.where(lanes % 2 == 0, xs, self.out_w - 1 - xs)
        order = np.lexsort((ys, along, lanes))
        ys, xs = ys[order], xs[order]
        last = 0
        for frame in range(frames):
            end = round(len(xs) * (frame + 1) / frames)
            self.drawn[ys[last:end], xs[last:end]] = self.color_img_float[ys[last:end], xs[last:end]]
            writer.write(self._snapshot_with_tip(int(xs[end - 1]), int(ys[end - 1]))
                         if end > last else self._snapshot())
            last = end

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

                allowed = self._allowed_mask(element, elements[idx + 1:])
                if self.subject_mode:
                    phase = reveal.get("phase", "both")
                    end_frame = round((start_ms + dur_ms) * cfg.fps / 1000)
                    frames = max(0, end_frame - round(cur_ms * cfg.fps / 1000))
                    ink_frames = frames if phase == "ink" else 0 if phase == "color" else frames // 2
                    color_frames = frames - ink_frames
                    if ink_frames:
                        strokes = paths[idx] if paths is not None else self._region_skeleton_strokes(allowed)
                        if strokes:
                            self._lay_ink_strokes(writer, ink_frames, strokes, allowed)
                        else:
                            for _ in range(ink_frames):
                                writer.write(self._snapshot())
                    if color_frames:
                        self._wash_subject(writer, color_frames, allowed)
                    cur_ms += frames * ms_per_frame
                    fill_static(start_ms + dur_ms)
                    continue
                # 严格分成两段：先画完整线稿，再独立进行颜色揭示。
                ink_frames = max(1, round(dur_ms * 0.52 * cfg.fps / 1000))
                color_frames = max(1, round(dur_ms * 0.28 * cfg.fps / 1000))

                if cfg.ink_path_mode == "skeleton":
                    strokes = paths[idx] if paths is not None else self._region_skeleton_strokes(allowed)
                    if strokes:
                        self._lay_ink_strokes(writer, ink_frames, strokes, allowed)
                    else:
                        for _ in range(ink_frames):
                            writer.write(self._snapshot())
                    centers = [point for stroke in strokes for point in stroke] if strokes else []
                else:
                    path = paths[idx] if paths is not None else self._region_grid_path(allowed)
                    if path:
                        samples, pen_lifts, sample_cell = self._grid_plan(path)
                        # 块填充：随笔尖推进逐格铺满（保证文字/大块实心）
                        self._lay_ink_grid(writer, ink_frames, samples, pen_lifts, sample_cell, path, allowed)
                        centers = [self._cell_center(c) for c in path]
                    else:
                        self._lay_ink(writer, ink_frames, [], set(), allowed)
                        centers = []

                cur_ms += ink_frames * ms_per_frame

                if cfg.color_fill == "paint":
                    self._wash_paint(writer, color_frames, allowed)
                elif cfg.color_fill == "contour-wipe":
                    self._wash_contour(writer, color_frames, allowed)
                else:
                    self._wash_brush(writer, color_frames, centers, allowed)
                cur_ms += color_frames * ms_per_frame
                self._complete_region_color(allowed)
                fill_static(start_ms + dur_ms)

            # Never extend a board past its allocated narration time. The old
            # extra 0.5s per board accumulated and let audio truncate the last
            # image before it appeared.
            if not self.subject_mode:
                self.drawn[...] = self.color_img_float
            fill_static(total_ms)
        finally:
            writer.release()
        return raw_path

    # 网格起笔专用：带块填充，笔尖与揭墨同步
    def _lay_ink_grid(self, writer, frames: int, samples, pen_lifts, sample_cell, path, allowed) -> None:
        if frames <= 0:
            return
        n = len(samples)
        if n == 0:
            for _ in range(frames):
                writer.write(self._snapshot_with_tip(self.out_w // 2, self.out_h // 2))
            return
        idx_for_frame = _frame_progress_indices(n, frames)
        cells_done = 0
        last: int | None = None
        for si in idx_for_frame:
            if last is None:
                self._reveal_ink_segment(samples[si], samples[si], allowed)
            else:
                for k in range(last + 1, si + 1):
                    if k in pen_lifts:
                        continue
                    self._reveal_ink_segment(samples[k - 1], samples[k], allowed)
            target_cell = sample_cell[si]
            while cells_done <= target_cell and cells_done < len(path):
                self._ink_stamp_cell(path[cells_done], allowed)
                cells_done += 1
            sx, sy = samples[si]
            writer.write(self._snapshot_with_tip(sx, sy))
            last = si
        while cells_done < len(path):
            self._ink_stamp_cell(path[cells_done], allowed)
            cells_done += 1


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="SRT 白板动画整合渲染器（mask 编排 + stream 画法）")
    p.add_argument("image", help="线稿图路径")
    p.add_argument("annotation", help="同名 annotation.json 路径")
    p.add_argument("output", help="输出 MP4 路径")
    p.add_argument("hand", nargs="?", default=str(DEFAULT_HAND), help="手部素材 PNG（默认内置）")
    p.add_argument("--total-ms", type=int, default=None, help="总时长；缺省用标注 sceneDurationMs")
    p.add_argument("--bare-tip", action="store_true", help="不叠加笔尖/手部")
    p.add_argument("--ink-path", default="grid", choices=["grid", "skeleton"],
                   help="笔迹路径: grid 网格(默认); skeleton 骨架追踪")
    p.add_argument("--color-fill", default="paint", choices=["paint", "contour-wipe", "brush"],
                   help="上色: paint 画笔往返填充(默认); contour-wipe 轮廓扫描; brush 沿轨迹刷")
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

    hand_png = Path(args.hand) if args.hand else None
    stroke_limits = {"light": 24, "standard": 48, "detailed": 96, "full": 0}
    renderer = RegionStreamRenderer(
        image_bgr, annotation, cfg, hand_png, args.bare_tip,
        max_skeleton_strokes=stroke_limits[args.stroke_detail],
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
