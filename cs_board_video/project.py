"""Project confinement, atomic persistence, receipts and explicit approvals."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


class WorkflowError(Exception):
    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code  # 2 input, 3 dependency, 4 approval, 5 execution


def require(condition, message, code=2):
    if not condition:
        raise WorkflowError(message, code)


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def file_hash(path):
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as out:
            json.dump(value, out, ensure_ascii=False, indent=2, allow_nan=False)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def file_lock(path, message):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        try:
            if not os.fstat(handle.fileno()).st_size:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise WorkflowError(message, 5) from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


class Project:
    def __init__(self, root):
        raw = Path(root).absolute()
        require(raw.parent.name == "content" and not raw.is_symlink(),
                "项目必须是 content/ 下的独立目录")
        self.root = raw.resolve()
        require(self.root.parent == raw.parent.resolve(), "项目目录不能跳出 content")
        self.data = read_json(self.path("project.json"))
        require(self.data.get("schema_version") == 1, "不支持的项目版本")
        validate_config(self.data["config"])
        self.approvals = read_json(self.path("approvals.json"))

    def path(self, relative):
        name = Path(relative)
        require(not name.is_absolute() and not name.drive and ".." not in name.parts,
                f"资源必须使用项目内相对路径: {relative}")
        result = (self.root / name).resolve()
        require(result.is_relative_to(self.root), f"资源路径越界: {relative}")
        return result

    def load(self, relative, default=None):
        path = self.path(relative)
        return read_json(path) if path.exists() else default

    def save(self, relative, value):
        atomic_json(self.path(relative), value)

    def persist(self):
        self.save("project.json", self.data)
        self.save("approvals.json", self.approvals)

    @contextmanager
    def lock(self):
        with file_lock(self.path("render/command.lock"), "项目正在执行其他命令"):
            # Reload under the lock to avoid stale read/modify/write.
            self.data = read_json(self.path("project.json"))
            self.approvals = read_json(self.path("approvals.json"))
            yield self

    def hash(self, relative):
        return file_hash(self.path(relative))

    def scenes(self):
        board = self.load("narration/storyboard.json", {})
        return board.get("scenes", [])

    def scene(self, scene_id):
        require(bool(re.fullmatch(r"scene-\d{3}", scene_id or "")), "镜头编号必须是 scene-NNN")
        result = next((s for s in self.scenes() if s["scene_id"] == scene_id), None)
        require(result is not None, f"未知镜头: {scene_id}")
        return result

    def scene_path(self, scene_id, name):
        self.scene(scene_id)
        return f"scenes/{scene_id}/{name}"

    def approved(self, stage, target):
        return bool(target and self.approvals.get(stage, {}).get("digest") == target)

    def need_approval(self, stage, target):
        require(self.approved(stage, target), f"需要用户确认当前版本: {stage}", 4)

    def receipt(self, key, inputs, outputs):
        self.data.setdefault("receipts", {})[key] = {
            "inputs": inputs, "outputs": {p: self.hash(p) for p in outputs}, "at": now()}
        self.persist()

    def fresh(self, key, inputs):
        entry = self.data.get("receipts", {}).get(key, {})
        return (entry.get("inputs") == inputs and bool(entry.get("outputs"))
                and all(h and self.hash(p) == h for p, h in entry["outputs"].items()))


def initialize(content, name, script, config=None):
    require(bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name)), "项目名使用小写字母、数字和连字符")
    source = Path(script)
    require(source.is_file() and source.read_text(encoding="utf-8-sig").strip(), "口播文案不能为空")
    settings = {"width": 1920, "height": 1080, "fps": 30, "ink_path": "skeleton",
                "color_fill": "paint", "stroke_detail": 96, "bare_tip": False,
                "canvas_hex": "#F5EBD7", "crf": 20, "subtitles": True,
                "render_engine": "whiteboard", "composition_type": "standard",
                "include_key_text": False, "pen_text": "", "pen_type": "marker"}
    if config:
        require(isinstance(config, dict) and not set(config) - set(settings), "配置包含未知字段")
        settings.update(config)
    validate_config(settings)
    parent = Path(content).absolute()
    require(parent.name == "content" and not parent.is_symlink(), "运行目录必须命名为 content")
    parent.mkdir(parents=True, exist_ok=True)
    root = parent / name
    try:
        root.mkdir()
    except FileExistsError as error:
        raise WorkflowError("项目已存在，请使用 status/resume") from error
    for folder in ("narration", "style", "characters/references", "scenes", "audio/original",
                   "previews", "render/cache", "render/logs", "output", "reports"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / "narration/original.txt").write_bytes(source.read_bytes())
    atomic_json(root / "project.json", {"schema_version": 1, "name": name,
                "created_at": now(), "state": "script_ready", "config": settings, "receipts": {}})
    atomic_json(root / "approvals.json", {})
    return Project(root)


def validate_config(config):
    for name in ("width", "height"):
        require(type(config.get(name)) is int and config[name] >= 100 and config[name] % 10 == 0,
                "正式画幅宽高须为 10 的倍数且至少 100")
    require(type(config.get("fps")) is int and 1 <= config["fps"] <= 120, "fps 范围为 1..120")
    require(config.get("ink_path") in ("skeleton", "grid"), "未知笔迹模式")
    require(config.get("color_fill") in ("contour", "contour-wipe", "brush", "paint"), "未知上色模式")
    require(config.get("pen_type", "marker") in ("marker", "fountain"), "未知画笔类型")
    require(type(config.get("stroke_detail")) is int and config["stroke_detail"] >= 0, "stroke_detail 必须为非负整数")
    require(type(config.get("crf")) is int and 0 <= config["crf"] <= 51, "CRF 范围为 0..51")
    require(all(type(config.get(x)) is bool for x in ("bare_tip", "subtitles")), "bare_tip/subtitles 必须为布尔值")
    require(bool(re.fullmatch(r"#[0-9a-fA-F]{6}", config.get("canvas_hex", ""))), "底色必须是 #RRGGBB")
    require(config.get("render_engine", "whiteboard") in ("whiteboard", "remotion"), "原渲染分支为 whiteboard/remotion")
    require(config.get("composition_type", "standard") in ("standard", "collage"), "未知作品类型")
    require(config.get("composition_type") != "collage" or config.get("render_engine") == "remotion",
            "拼贴动画使用 Remotion 渲染引擎")
    if config.get("render_engine") == "remotion":
        require(config["fps"] == 30, "原 Remotion 时间轴固定使用 30fps")
        require(config.get("pen_type", "marker") == "marker", "钢笔选择用于白板绘制引擎")
