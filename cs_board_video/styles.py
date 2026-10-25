"""Local reusable styles; projects always receive their own asset copies."""
from copy import deepcopy
import os
from pathlib import Path
import shutil
import tempfile

from .project import atomic_json, digest, file_hash, file_lock, read_json, require


LIBRARY_DIR = Path(__file__).resolve().parents[1] / "style-presets"


def library_path(relative):
    name = Path(relative)
    require(not name.is_absolute() and not name.drive and ".." not in name.parts,
            "预设资源必须使用库内相对路径")
    root = LIBRARY_DIR.resolve()
    path = (root / name).resolve()
    require(path.is_relative_to(root), "预设资源路径越界")
    return path


def reference_path(p):
    references = p.data.get("visual_references", {})
    # An explicit empty value disables the legacy default after switching styles.
    value = references.get("style_image", "style/reference.png" if p.path("style/reference.png").exists() else "")
    return p.path(value) if value else None


def records():
    path = library_path("library.json")
    if not path.exists():
        return {}
    data = read_json(path)
    require(isinstance(data, dict) and data.get("schema_version") == 1
            and isinstance(data.get("presets"), dict), "不支持的画风预设库格式")
    return data["presets"]


def presets():
    from .bridge import presets as builtin_presets
    result = [{**item, "source": "builtin"} for item in builtin_presets()]
    for key, item in records().items():
        require(isinstance(item, dict) and isinstance(item.get("style"), dict), f"画风预设损坏: {key}")
        result.append({"id": key, "name": item["style"]["name"], "source": "custom",
                       "recipe": item["style"]["recipe"], "canvas_hex": item["style"]["canvas_hex"],
                       "image_path": str(library_path(item["reference"])) if item.get("reference") else None,
                       "hand_path": str(library_path(item["hand"])), "style": item["style"]})
    return result


def select(value):
    matches = [item for item in presets() if value in (item["id"], item["name"])]
    require(len(matches) == 1, "未知或重名画风预设；请先运行 style list")
    return matches[0]


def validate_images(item):
    from .bridge import server
    for key in ("image_path", "hand_path"):
        if item.get(key):
            require(server().valid_image_file(Path(item[key])), f"画风预设图片缺失或无效: {item[key]}")


def store_image(source):
    from .bridge import server
    require(server().valid_image_file(source), f"画风图片缺失或无效: {source}")
    relative = f"assets/{file_hash(source)}{source.suffix.lower()}"
    target = library_path(relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Publish complete immutable assets before publishing the library manifest.
    with tempfile.TemporaryDirectory(prefix=".save-", dir=target.parent) as temporary:
        staged = Path(temporary) / "image"
        shutil.copyfile(source, staged)
        os.replace(staged, target)
    return relative


def save(p, name=None, replace=False):
    from . import workflow as w
    from .bridge import presets as builtin_presets
    w.style_ready(p)
    style = deepcopy(p.load("style/style.json"))
    require(not style.get("preset"), "style save 用于自定义画风；内置画风可直接选用")
    name = " ".join((name if name is not None else style["name"]).split())
    require(0 < len(name) <= 40, "画风名称须为 1 至 40 个字符")
    require(all(name not in (item["id"], item["name"]) for item in builtin_presets())
            and not name.startswith("custom-"), "名称与预设标识或内置画风冲突，请使用其他名称")
    key = "custom-" + digest(name)[:16]
    recipe = style.get("recipe") or "；".join(f"{k}: {v}" for k, v in style.items() if k != "name")
    # Keep the selected canvas in the style snapshot so color-only preset updates
    # invalidate that project's approval without changing legacy digest contracts.
    style.update(name=name, recipe=recipe, canvas_hex=p.data["config"]["canvas_hex"])
    reference = reference_path(p)
    with file_lock(library_path("library.lock"), "画风预设库正在保存，请稍后重试"):
        items = records()
        replaced = key in items
        require(key not in items or replace, "同名预设已存在；更新需显式 --replace")
        item = {"style": style,
                "reference": store_image(reference) if reference else None,
                "hand": store_image(p.path("style/drawing-hand.png"))}
        items[key] = item
        atomic_json(library_path("library.json"), {"schema_version": 1, "presets": items})
    return {"id": key, "name": name, "library": str(LIBRARY_DIR.resolve()), "replaced": replaced}
