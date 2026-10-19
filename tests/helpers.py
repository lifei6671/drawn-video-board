from pathlib import Path
import wave

import cv2
import numpy as np

from cs_board_video.project import initialize
from cs_board_video import workflow as w


STYLE = {"name": "测试暖纸", "lines": "深灰线", "palette": ["#F5EBD7", "#303030"],
         "proportions": "简化人物", "shading": "无", "texture": "纸张", "composition": "留白", "complexity": "低"}


def fixture(base, count=1, mode="manual", width=320, height=180, fps=10, content=None, name="fixture"):
    base = Path(base)
    base.mkdir(parents=True, exist_ok=True)
    script = base / "source.txt"
    texts = [f"第{i}幕，人物递出物品。" for i in range(1, count + 1)]
    script.write_text("".join(texts), encoding="utf-8")
    p = initialize(content or base / "content", name, script, {"width": width, "height": height,
                    "fps": fps, "bare_tip": True, "stroke_detail": 24})
    scenes = [{"scene_id": f"scene-{i:03}", "narration": text, "narrative_goal": "展示动作",
               "visual_description": "左人右物", "composition": "两侧分离", "subjects": ["人", "物"],
               "drawing_order": ["人物", "物品"], "estimated_duration": 2, "transition": "cut"}
              for i, text in enumerate(texts, 1)]
    p.save("narration/storyboard.json", {"scenes": scenes})
    return p


def approve(p, stage, scene=None):
    # Synthetic authorization is restricted to isolated test fixture projects.
    return w.approve(p, stage, w.approval_target(p, stage, scene), "测试夹具明确批准", scene)


def prepare_images(p, mode="manual"):
    approve(p, "storyboard")
    p.save("style/style.json", STYLE)
    import shutil
    shutil.copyfile(Path(__file__).parents[1] / "cs_board_video/upstream/assets/drawing-hand-clean.png", p.path("style/drawing-hand.png"))
    approve(p, "style")
    p.data["image_mode"] = mode
    p.persist()
    approve(p, "image_mode")
    width, height = p.data["config"]["width"], p.data["config"]["height"]
    for scene in p.scenes():
        sid = scene["scene_id"]
        image = np.full((height, width, 3), (215, 235, 245), dtype=np.uint8)
        cv2.circle(image, (width // 4, height // 3), height // 8, (40, 40, 40), 2)
        cv2.line(image, (width // 4, height // 2), (width // 4, height * 4 // 5), (40, 40, 40), 2)
        cv2.rectangle(image, (width * 3 // 5, height // 4), (width * 4 // 5, height * 3 // 4), (60, 90, 190), 3)
        cv2.imencode(".png", image)[1].tofile(str(p.path(f"scenes/{sid}/image.png")))
        p.path(f"scenes/{sid}/prompt.md").write_text("测试图：左侧人物、右侧物品。", encoding="utf-8")
        w.review_image(p, sid, w.image_target(p, sid), "测试几何图内容匹配；无角色差异；统一暖纸；边界清晰")
    w.validate_images(p)
    return p


def prepare_audio(p, seconds=None, generated=False):
    source = p.root / "audio/original/fixture.wav"
    seconds = seconds or len(p.scenes()) * 2
    with wave.open(str(source), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(48000)
        # Audible sine fixture, explicitly not speech or a listening acceptance.
        samples = (np.sin(np.arange(round(seconds * 48000)) * 2 * np.pi * 440 / 48000) * 3000).astype("<i2")
        out.writeframes(samples.tobytes())
    w.import_audio(p, source, "合成测试音，不代表真实口播验收", generated=generated)
    return p


def prepare_plans(p):
    w.timeline_build(p)
    width, height = p.data["config"]["width"], p.data["config"]["height"]
    for scene in p.scenes():
        sid = scene["scene_id"]
        p.save(f"scenes/{sid}/drawing-plan.json", {
            "image_sha256": p.hash(f"scenes/{sid}/image.png"), "visual_evidence": "测试几何图已知边界",
            "elements": [
                {"id": "person", "narrativeRole": "角色", "subtitle": scene["narration"],
                 "region": {"x": 0, "y": 0, "width": width // 2, "height": height}},
                {"id": "object", "narrativeRole": "结果物品", "subtitle": scene["narration"],
                 "region": {"x": width // 2, "y": 0, "width": width // 2, "height": height}}]})
    w.annotation_build(p)
    return p
