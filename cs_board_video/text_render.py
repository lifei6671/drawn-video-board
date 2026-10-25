"""Independent text overlays with character or whole-layer fade entrances."""
import numpy as np


def blend(frame, rgb, alpha, x, y):
    h, w = alpha.shape
    x0, y0, x1, y1 = max(0,x), max(0,y), min(frame.shape[1],x+w), min(frame.shape[0],y+h)
    if x1 <= x0 or y1 <= y0:
        return
    a = alpha[y0-y:y1-y,x0-x:x1-x].astype(np.float32)[:,:,None]/255
    color = np.asarray(rgb)[...,::-1]
    if color.ndim == 3:
        color = color[y0-y:y1-y,x0-x:x1-x]
    target = frame[y0:y1,x0:x1]
    target[:] = np.rint(target*(1-a)+color*a).astype(np.uint8)


def opacity(amount):
    """A bounded ease-out; all pixels of a glyph share the same opacity."""
    return 1 - (1 - min(1., max(0., amount))) ** 3


def faded(alpha, amount):
    return np.rint(alpha.astype(np.float32) * opacity(amount)).astype(np.uint8)


class TextOverlay:
    def __init__(self, layers, total_ms, fps):
        self.layers = layers
        self.total_ms = total_ms
        self.fps = fps
        self.index = 0

    def paint(self, frame, at_ms):
        for layer in self.layers:
            progress = (at_ms/self.total_ms-layer["start"])/layer["duration"]
            if progress < 0:
                continue
            whole = layer.get("animation", "characters") == "fade"
            bubble = layer["bubble"]
            bubble_alpha = faded(bubble[:,:,3], progress) if whole else bubble[:,:,3]
            blend(frame, bubble[:,:,:3], bubble_alpha, layer["x"], layer["y"])
            glyphs = layer["glyphs"]
            for index,glyph in enumerate(glyphs):
                amount = progress if whole else progress*len(glyphs)-index
                if amount <= 0:
                    continue
                alpha = faded(glyph["mask"], amount)
                blend(frame, layer["color"], alpha, glyph["x"], glyph["y"])
        return frame

    def wrap(self, writer):
        overlay=self
        class Writer:
            def isOpened(self):
                return writer.isOpened()
            def write(self, frame):
                out=frame.copy()
                at_ms = overlay.index*1000/overlay.fps
                overlay.paint(out, at_ms)
                writer.write(out)
                overlay.index+=1
            def release(self):
                writer.release()
        return Writer()
