"""Built-in drawing hands and project pen selection."""
import shutil

from .bridge import ROOT, Config, project_context
from .project import require


def hand_path(kind):
    require(kind in ("marker", "fountain"), "未知画笔类型")
    return ROOT / "assets" / ("drawing-hand-fountain.png" if kind == "fountain" else "drawing-hand-clean.png")


def catalog():
    return [{"id": kind, "name": name, "image": str(hand_path(kind)),
             "reveal_radius": Config(pen_type=kind).pen_reveal_radius}
            for kind, name in (("marker", "马克笔"), ("fountain", "钢笔"))]


def select(project, kind):
    require(project.data["config"].get("render_engine", "whiteboard") == "whiteboard",
            "画笔选择用于白板绘制引擎")
    source = hand_path(kind)
    require(source.is_file(), "安装包缺少画笔素材")
    destination = project.path("style/drawing-hand.png")
    shutil.copyfile(source, destination)
    if kind == "marker" and project.data["config"].get("pen_text"):
        with project_context(project) as module:
            module.make_branded_hand(project.data["config"]["pen_text"], destination)
    project.data["config"]["pen_type"] = kind
    from .workflow import style_target
    return {"pen_type": kind, "image": str(destination), "digest": style_target(project),
            "approval_required": True}
