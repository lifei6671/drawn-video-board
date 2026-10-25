"""Small built-in illustration parts, exported independently of character identity."""
import json
from pathlib import Path
import re
from xml.etree.ElementTree import Element, SubElement, tostring

from PIL import Image, ImageDraw, ImageOps

from .project import file_hash, require

ROOT = Path(__file__).parent / "assets/materials"
DEFAULT_COLORS = {"ink": "#252521", "paper": "#F6F1E5", "accent": "#A8B88C"}


def catalog(category=None):
    items = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))["items"]
    items += json.loads((ROOT / "collage-catalog.json").read_text(encoding="utf-8"))["items"]
    if category is not None:
        require(category in {item["category"] for item in items}, "未知素材分类")
        items = [item for item in items if item["category"] == category]
    return items


def select(asset_id):
    item = next((item for item in catalog() if item["id"] == asset_id), None)
    require(item is not None, "未知素材，请先查看 materials list")
    return item


def shapes(item):
    if "bubble" not in item:
        return item["shapes"]
    data = json.loads((ROOT.parent / "bubbles/templates.json").read_text(encoding="utf-8"))[item["bubble"]]
    result = [{"type": "polygon", "points": [[x*600,y*400] for x,y in data["outline"]],
               "fill": "paper", "stroke": "ink" if data.get("stroke", True) else "none", "width": 3}]
    for x,y,rx,ry in data.get("dots", []):
        result.append({"type": "ellipse", "box": [(x-rx)*600,(y-ry)*400,(x+rx)*600,(y+ry)*400],
                       "fill": "paper", "stroke": "ink", "width": 3})
    return result


def options(size, colors):
    require(len(size) == 2 and all(type(n) is int and 64 <= n <= 4096 for n in size), "素材尺寸须为 64..4096 的整数")
    palette = {**DEFAULT_COLORS, **(colors or {})}
    require(set(palette) == set(DEFAULT_COLORS) and all(isinstance(c,str) and re.fullmatch(r"#[0-9a-fA-F]{6}",c) for c in palette.values()),
            "素材颜色使用 ink/paper/accent 和 #RRGGBB")
    return palette


def render(item, size=(600,400), colors=None, flip=False):
    palette = options(size, colors)
    if item.get("raster"):
        require(palette == DEFAULT_COLORS, "纸质剪贴位图保留原色，不支持 ink/paper/accent 改色")
        with Image.open(ROOT / item["raster"]) as source:
            cutout = ImageOps.contain(source.convert("RGBA"), tuple(size), Image.Resampling.LANCZOS)
        image = Image.new("RGBA", tuple(size))
        image.paste(cutout, ((size[0]-cutout.width)//2, (size[1]-cutout.height)//2))
        return ImageOps.mirror(image) if flip else image
    scale = 3 if max(size) <= 1200 else 2
    high = (size[0]*scale, size[1]*scale)
    image = Image.new("RGBA", high)
    sx, sy = high[0]/600, high[1]/400
    for shape in shapes(item):
        layer = Image.new("RGBA", high)
        draw = ImageDraw.Draw(layer)
        def color(key):
            token = shape.get(key, "none")
            return None if token == "none" else palette[token]
        width = max(1, round(shape.get("width", 3)*min(sx,sy)))
        if shape["type"] in ("polygon", "line"):
            points = [(round(x*sx),round(y*sy)) for x,y in shape["points"]]
            if shape["type"] == "polygon":
                if color("fill"): draw.polygon(points, fill=color("fill"))
                if color("stroke"): draw.line(points+[points[0]], fill=color("stroke"), width=width, joint="curve")
            else:
                draw.line(points, fill=color("stroke"), width=width, joint="curve")
        else:
            box = [round(v*s) for v,s in zip(shape["box"],(sx,sy,sx,sy))]
            method = draw.ellipse if shape["type"] == "ellipse" else draw.rectangle
            method(box, fill=color("fill"), outline=color("stroke"), width=width)
        if shape.get("opacity", 1) != 1:
            layer.putalpha(layer.getchannel("A").point(lambda a: round(a*shape["opacity"])))
        image = Image.alpha_composite(image, layer)
    image = image.resize(tuple(size), Image.Resampling.LANCZOS)
    return ImageOps.mirror(image) if flip else image


def svg(item, size=(600,400), colors=None, flip=False):
    require(not item.get("raster"), "纸质剪贴素材是位图，不提供矢量 SVG")
    palette = options(size, colors)
    root = Element("svg", {"xmlns":"http://www.w3.org/2000/svg", "viewBox":"0 0 600 400",
                           "width":str(size[0]), "height":str(size[1]), "preserveAspectRatio":"none"})
    SubElement(root,"title").text = item["name"]
    # Both formats use the same normalized geometry.
    group = SubElement(root,"g", {"transform":"translate(600 0) scale(-1 1)"} if flip else {})
    for shape in shapes(item):
        attrs = {key: palette.get(shape.get(key,"none"),"none") for key in ("fill","stroke")}
        attrs.update({"stroke-width":str(shape.get("width",3)), "stroke-linejoin":"round", "opacity":str(shape.get("opacity",1))})
        kind = shape["type"]
        if kind in ("polygon","line"):
            attrs["points"] = " ".join(f"{x:g},{y:g}" for x,y in shape["points"])
            kind = "polyline" if kind == "line" else "polygon"
        else:
            x0,y0,x1,y1 = shape["box"]
            if kind == "ellipse":
                attrs.update(cx=str((x0+x1)/2),cy=str((y0+y1)/2),rx=str((x1-x0)/2),ry=str((y1-y0)/2))
            else:
                attrs.update(x=str(x0),y=str(y0),width=str(x1-x0),height=str(y1-y0))
        SubElement(group,kind,attrs)
    return tostring(root,encoding="unicode") + "\n"


def export(p, asset_id, size=(600,400), colors=None, flip=False, replace=False):
    item = select(asset_id)
    palette = options(size, colors)
    suffixes = ("png", "json") if item.get("raster") else ("png", "svg", "json")
    paths = {suffix:p.path(f"materials/{asset_id}.{suffix}") for suffix in suffixes}
    require(replace or not any(path.exists() for path in paths.values()), "项目素材已存在；替换需 --replace")
    png = render(item, size, palette, flip)
    vector = None if item.get("raster") else svg(item, size, palette, flip)
    paths["png"].parent.mkdir(parents=True,exist_ok=True)
    png.save(paths["png"])
    if vector is not None:
        paths["svg"].write_text(vector,encoding="utf-8")
    metadata = {k:v for k,v in item.items() if k not in ("shapes","bubble")}
    if flip:
        metadata["direction"] = {"left":"right","right":"left"}.get(item["direction"],item["direction"])
        if metadata.get("text_box"):
            x,y,w,h=metadata["text_box"];metadata["text_box"]=[1-x-w,y,w,h]
    metadata.update(size=list(size),colors=None if item.get("raster") else palette,flip=flip,
                    png_sha256=file_hash(paths["png"]),source="builtin-materials",character_identity=None)
    if vector is not None:
        metadata["svg_sha256"] = file_hash(paths["svg"])
    p.save(f"materials/{asset_id}.json",metadata)
    return {"files":{k:str(v) for k,v in paths.items()},"material":metadata}
