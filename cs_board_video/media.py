"""Native drawing, FFmpeg composition and measurable technical checks."""
from __future__ import annotations

from fractions import Fraction
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from copy import deepcopy

import cv2
import numpy as np

from .project import WorkflowError, atomic_json, file_hash, require
from .bridge import ROOT as UPSTREAM_ROOT, RegionStreamRenderer, Config, _imread_any, project_context


def run(argv, *, cwd=None, env=None):
    try:
        result = subprocess.run([str(x) for x in argv], cwd=cwd, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=1800, env=env)
    except FileNotFoundError as error:
        raise WorkflowError(f"缺少程序: {argv[0]}", 3) from error
    except subprocess.TimeoutExpired as error:
        raise WorkflowError("媒体命令超时，可重新执行恢复", 5) from error
    require(result.returncode == 0, f"媒体命令失败: {result.stderr[-2000:]}", 5)
    return result.stdout


def probe(path):
    return json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format",
                           "-of", "json", path]))


def duration(path):
    data = probe(path)
    streams = data.get("streams", [])
    require(streams, f"媒体没有有效流: {path}")
    return float(data["format"]["duration"])


def normalize_audio(source, destination):
    info = probe(source)
    require(any(s["codec_type"] == "audio" for s in info["streams"]), "输入没有音频流")
    temporary = destination.with_name("voice.pending.wav")
    run(["ffmpeg", "-y", "-v", "error", "-i", source, "-map", "0:a:0", "-vn",
         "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", temporary])
    require(duration(temporary) > 0, "音频时长无效")
    temporary.replace(destination)


def image_info(path):
    require(path.is_file(), f"缺少图片: {path}")
    require(path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", "图片必须是真实 PNG")
    image = _imread_any(path, cv2.IMREAD_UNCHANGED)
    require(image is not None and image.size > 0, "图片无法解码")
    require(image.ndim == 3 and image.shape[2] in (3, 4), "图片必须是 RGB/RGBA")
    if image.shape[2] == 4:
        require(np.all(image[:, :, 3] == 255), "场景图片必须有不透明背景")
    h, w = image.shape[:2]
    return {"width": w, "height": h, "contrast_std": float(image[:, :, :3].std())}


class PreviewWriter:
    """Scale canonical drawing frames only at the output boundary."""
    def __init__(self, path, fps, size):
        self.size = tuple(size)
        self.writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, self.size)

    def isOpened(self):
        return self.writer.isOpened()

    def write(self, frame):
        self.writer.write(cv2.resize(frame, self.size, interpolation=cv2.INTER_AREA))

    def release(self):
        self.writer.release()


def native_renderer(project, scene_id, annotation):
    config = project.data["config"]
    width, height = config["width"], config["height"]
    require(width % 10 == 0 and height % 10 == 0 and min(width, height) >= 100,
            "正式画幅宽高须为 10 的倍数且至少 100 像素")
    source = _imread_any(project.path(f"scenes/{scene_id}/image.png"))
    require(source is not None, f"镜头图片无法解码: {scene_id}")
    # Validate aspect before resizing: canonical geometry remains exact.
    source = cv2.resize(source, (width, height), interpolation=cv2.INTER_AREA)
    cfg = Config(fps=config["fps"], cap_long_edge=max(width, height),
                 ink_path_mode=config["ink_path"], color_fill=config["color_fill"],
                 canvas_hex=config["canvas_hex"])
    return RegionStreamRenderer(source, annotation, cfg,
                                project.path("style/drawing-hand.png"), config["bare_tip"],
                                max_skeleton_strokes=config["stroke_detail"])


def render_scene(project, scene_id, annotation, inputs, preview_size=None):
    if project.data["config"].get("render_engine") == "remotion":
        return render_remotion_scene(project, scene_id, inputs, preview_size)
    prefix = f"scenes/{scene_id}"
    renderer = native_renderer(project, scene_id, annotation)
    cache_path = f"render/cache/{scene_id}-paths.json"
    cached = project.load(cache_path, {})
    if not project.fresh("paths:" + scene_id, inputs):
        elements = sorted(annotation["elements"], key=lambda e: e["reveal"]["startMs"])
        paths = []
        for index, element in enumerate(elements):
            allowed = renderer._allowed_mask(element, elements[index + 1:])
            paths.append(renderer._region_skeleton_strokes(allowed) if renderer.subject_mode or renderer.cfg.ink_path_mode == "skeleton"
                         else renderer._region_grid_path(allowed))
        cached = {"inputs": inputs, "canonical_size": [renderer.out_w, renderer.out_h], "paths": paths}
        project.save(cache_path, cached)
        project.receipt("paths:" + scene_id, inputs, [cache_path])
    # JSON lists are valid coordinate sequences for both native algorithms.
    name = "preview.mp4" if preview_size else "final.mp4"
    output = project.path(f"{prefix}/{name}")
    raw = project.path(f"render/cache/{scene_id}-raw.mp4")
    size = preview_size or (renderer.out_w, renderer.out_h)
    require(abs(size[0] / size[1] - renderer.out_w / renderer.out_h) < .01,
            "预览画幅比例必须与正式画幅一致")
    writer = PreviewWriter(raw, renderer.cfg.fps, size)
    text_overlay = None
    if project.scene(scene_id).get("visual_text"):
        from . import typography
        from .text_render import TextOverlay
        typography.ready(project)
        text_overlay = TextOverlay(typography.layout(project, project.scene(scene_id),
                                   (renderer.out_w, renderer.out_h)),
                                   annotation["sceneDurationMs"], renderer.cfg.fps)
        writer = text_overlay.wrap(writer)
    renderer.render_to(raw, annotation["sceneDurationMs"], writer=writer, paths=cached["paths"])
    pending = output.with_name(output.stem + ".pending.mp4")
    run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-an", "-c:v", "libx264",
         "-crf", str(project.data["config"]["crf"]), "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", pending])
    check = video_check(pending, size, renderer.cfg.fps, annotation["sceneDurationMs"] / 1000,
                        audio=False)
    require(check["passed"], f"镜头技术检查失败: {check}", 5)
    pending.replace(output)
    raw.unlink(missing_ok=True)
    quality = drawing_checks(output, renderer, annotation, text_overlay)
    project.save(f"reports/{scene_id}-{'preview' if preview_size else 'final'}.json", quality)
    contact = project.path(f"{prefix}/{'preview' if preview_size else 'final'}-contact.png")
    contact_sheet(output, contact)
    return name, quality


def render_remotion_scene(project, scene_id, inputs, preview_size):
    """Project/clip coordinate adapter for the original Remotion renderer."""
    props = project.load("render/remotion-props.json")
    require(props, "请先使用真实词边界构建原 Remotion 时间轴")
    index = next(i for i, s in enumerate(project.scenes()) if s["scene_id"] == scene_id)
    page = deepcopy(props["pages"][index])
    offset = page["startFrame"]
    frames = page["endFrame"] - offset
    page["startFrame"], page["endFrame"] = 0, frames
    for cue in page["cues"]:
        for key in ("startFrame", "endFrame"):
            cue[key] -= offset
        for key in ("spokenStartMs", "spokenEndMs"):
            cue[key] -= offset * 1000 / props["fps"]
    public = project.path(f"render/cache/remotion/{scene_id}")
    public.mkdir(parents=True, exist_ok=True)
    # Original props use board-NN.png; restrict the remapped public resource to a fixed name.
    page["image"] = "image.png"
    shutil.copyfile(project.path(f"scenes/{scene_id}/image.png"), public / "image.png")
    config = project.data["config"]
    canonical = {**props, "pages": [page], "totalDurationFrames": frames,
                 "totalDurationMs": frames * 1000 / props["fps"]}
    cache_path = f"render/cache/{scene_id}-paths.json"
    if not project.fresh("paths:" + scene_id, inputs):
        project.save(cache_path, {"inputs": inputs, "engine": "upstream-remotion", "props": canonical})
        project.receipt("paths:" + scene_id, inputs, [cache_path])
    size = preview_size or [config["width"], config["height"]]
    require(abs(size[0] / size[1] - canonical["width"] / canonical["height"]) < .001,
            "预览和正式输出必须保持原 Remotion 画幅比例")
    stage = "preview" if preview_size else "final"
    task = f"render/cache/{scene_id}-{stage}-remotion.json"
    project.save(task, canonical)
    output = project.path(f"scenes/{scene_id}/{stage}.mp4")
    temporary = project.path("render/cache/runtime")
    temporary.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "CS_BOARD_BUNDLE_DIR": str(project.path("render/cache/remotion-bundle")),
           "CS_BOARD_CRF": str(config["crf"]), "CS_BOARD_CONCURRENCY": "1",
           "TEMP": str(temporary), "TMP": str(temporary), "TMPDIR": str(temporary)}
    native_output = project.path(f"render/cache/{scene_id}-{stage}-remotion-native.mp4")
    run(["node", UPSTREAM_ROOT / "video_renderer/render.mjs", project.path(task), native_output, public],
        cwd=UPSTREAM_ROOT / "video_renderer", env=env)
    run(["ffmpeg", "-y", "-v", "error", "-i", native_output, "-an", "-vf", f"scale={size[0]}:{size[1]}",
         "-c:v", "libx264", "-crf", str(config["crf"]), "-pix_fmt", "yuv420p", "-movflags", "+faststart", output])
    report = video_check(output, size, props["fps"], frames / props["fps"], audio=False)
    require(report["passed"], f"原 Remotion 镜头技术检查失败: {report}", 5)
    report.update({"engine": "upstream-remotion", "visual_acceptance": "NOT_RUN",
                   "timing_source": "upstream-semantic-timeline", "mask_check": "NOT_APPLICABLE"})
    project.save(f"reports/{scene_id}-{stage}.json", report)
    contact_sheet(output, project.path(f"scenes/{scene_id}/{stage}-contact.png"))
    return stage + ".mp4", report


def drawing_checks(path, renderer, annotation, text_overlay=None):
    """Pixel checks with hand overlay disabled for protected-region semantics."""
    capture = cv2.VideoCapture(str(path))
    fps = capture.get(cv2.CAP_PROP_FPS)
    count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    previous = None
    static_run = longest = 0
    leakage = []
    elements = sorted(annotation["elements"], key=lambda e: e["reveal"]["startMs"])
    subject_masks = ([renderer._allowed_mask(e, []) for e in elements]
                     if renderer.subject_mode else None)
    index = 0
    last = None
    # Every decoded frame is checked for validity and long static runs.
    try:
        while True:
            valid, frame = capture.read()
            if not valid:
                break
            small = cv2.resize(frame, (160, 90))
            if previous is not None and float(cv2.absdiff(small, previous).mean()) < .15:
                static_run += 1
            else:
                static_run = 0
            longest = max(longest, static_run)
            previous = small
            at_ms = index * 1000 / fps
            # Image-region pixels may legitimately be occupied by the moving hand.
            # Report that case as requiring human review, never as a mask PASS.
            if renderer.tip is None and text_overlay is None:
                for ei, e in enumerate(elements):
                    if at_ms + 1000 / fps < e["reveal"]["startMs"]:
                        if subject_masks is not None:
                            future = subject_masks[ei].copy()
                            for prior, mask in zip(elements, subject_masks):
                                if prior["reveal"]["startMs"] <= at_ms:
                                    future &= ~mask
                            future = cv2.resize(future.astype(np.uint8), (frame.shape[1], frame.shape[0]),
                                                interpolation=cv2.INTER_NEAREST) > 0
                            if future.any() and np.abs(frame[future].astype(float) - renderer.canvas_bgr).mean() > 10:
                                leakage.append({"frame": index, "element": e["id"]})
                            continue
                        r = e["region"]
                        sx = frame.shape[1] / annotation["canvas"]["width"]
                        sy = frame.shape[0] / annotation["canvas"]["height"]
                        x, y = round(r["x"] * sx), round(r["y"] * sy)
                        w, h = round(r["width"] * sx), round(r["height"] * sy)
                        crop = frame[y + 2:y + h - 2, x + 2:x + w - 2]
                        if crop.size and np.abs(crop.astype(float) - renderer.canvas_bgr).mean() > 10:
                            leakage.append({"frame": index, "element": e["id"]})
            last = frame
            index += 1
    finally:
        capture.release()
    require(last is not None, "无法解码绘制输出", 5)
    reference = renderer.color_img.copy()
    if text_overlay is not None:
        text_overlay.paint(reference, annotation["sceneDurationMs"])
    expected = cv2.resize(reference, (last.shape[1], last.shape[0]))
    error = float(cv2.absdiff(last, expected).mean())
    return {"decoded_frames": index, "expected_frames": count, "final_frame_mae": error,
            "final_frame_complete": error < 18, "longest_static_seconds": longest / fps,
            "static_warning": longest / fps > 3, "mask_leakage": leakage[:20],
            "mask_check": "REQUIRES_VISUAL_REVIEW" if renderer.tip or text_overlay else ("FAIL" if leakage else "PASS"),
            "text_overlay": text_overlay is not None,
            "order_check": "PASS", "visual_acceptance": "NOT_RUN",
            "passed": index == count and error < 18 and not leakage}


def contact_sheet(source, destination):
    cap = cv2.VideoCapture(str(source))
    try:
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frames = []
        for fraction in (.0, .25, .5, .75, .99):
            cap.set(cv2.CAP_PROP_POS_FRAMES, min(count - 1, round(count * fraction)))
            valid, frame = cap.read()
            require(valid, "关键帧抽取失败", 5)
            frames.append(cv2.resize(frame, (320, 180)))
        cv2.imencode(".png", np.concatenate(frames, axis=1))[1].tofile(str(destination))
    finally:
        cap.release()


def compose(project, preview, clips, srt):
    destination = project.path("previews/full-preview.mp4" if preview else "output/final.mp4")
    silent = project.path(f"render/cache/{'preview' if preview else 'final'}-silent.mp4")
    run([sys.executable, UPSTREAM_ROOT / "scripts/merge_scenes.py", "--inputs",
         *(project.path(clip) for clip in clips), "--output", silent], cwd=project.root)
    with project_context(project) as module:
        module.compose_final_video(silent, project.path("audio/voice.wav"), destination,
            project.path(srt) if project.data["config"]["subtitles"] else None,
            crf=project.data["config"]["crf"])
    return destination.relative_to(project.root).as_posix()


def video_check(path, size, fps, seconds, audio=True, subtitles=False):
    data = probe(path)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), {})
    sound = next((s for s in data["streams"] if s["codec_type"] == "audio"), {})
    tolerance = max(.1, 2 / fps)
    checks = {"h264": video.get("codec_name") == "h264",
              "size": [video.get("width"), video.get("height")] == list(size),
              "fps": abs(float(Fraction(video.get("avg_frame_rate", "0"))) - fps) < .01,
              "video_duration": abs(float(video.get("duration", 0)) - seconds) <= tolerance,
              "audio": (not audio or (bool(sound) and abs(float(sound.get("duration", 0)) - seconds) <= tolerance)),
              "subtitles": not subtitles or any(s["codec_type"] == "subtitle" for s in data["streams"])}
    # FFmpeg decodes the complete streams; container metadata alone is insufficient.
    run(["ffmpeg", "-v", "error", "-xerror", "-i", path, "-f", "null", "-"])
    checks["full_decode"] = True
    return {"passed": all(checks.values()), "checks": checks, "seconds": seconds}


def doctor(url=None):
    result = {"python_dependencies": {"opencv": cv2.__version__, "numpy": np.__version__},
              "ffmpeg": shutil.which("ffmpeg"), "ffprobe": shutil.which("ffprobe"),
              "upstream_root": str(UPSTREAM_ROOT.resolve()), "node": shutil.which("node"),
              "remotion_dependencies": "INSTALLED" if (UPSTREAM_ROOT / "video_renderer/node_modules/@remotion/renderer").is_dir() else "NOT_INSTALLED",
              "voicestudio": "NOT_CONFIGURED"}
    if url:
        from .adapters.voicestudio import discover
        try:
            details = discover(url)
            result["voicestudio"] = {"status": details["status"], "base_url": details["base_url"],
                "endpoints": {path: list(operations) for path, operations in details["paths"].items()},
                "models": details["models"]}
        except WorkflowError as error:
            result["voicestudio"] = {"status": "UNAVAILABLE", "error": str(error)}
    return result
