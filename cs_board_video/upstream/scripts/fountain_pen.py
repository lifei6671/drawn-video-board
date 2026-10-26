"""Source-ink tracing and pressure/motion profiles adapted from sweety-handdraw-video.

MIT License, copyright (c) 2026 threerocks. Full notice is distributed in
../assets/licenses/sweety-handdraw-video-LICENSE.txt.
"""
import numpy as np

_TAU = np.linspace(0.0, 1.0, 513)
_MINJERK = 10 * _TAU**3 - 15 * _TAU**4 + 6 * _TAU**5


def _plateau(ramp=.2):
    """Cruise at constant speed with min-jerk speed-up/slow-down over the first and last 20% of the time."""
    speed = np.ones_like(_TAU)
    ease = lambda u: 10 * u**3 - 15 * u**4 + 6 * u**5
    speed[_TAU < ramp] = ease(_TAU[_TAU < ramp] / ramp)
    speed[_TAU > 1 - ramp] = ease((1 - _TAU[_TAU > 1 - ramp]) / ramp)
    distance = np.r_[0., np.cumsum((speed[1:] + speed[:-1]) / 2)]
    return distance / distance[-1]


_CURVES = {'minjerk': _MINJERK, 'plateau': _plateau()}
# Peak speed relative to the mean speed of each profile (limits how fast a stroke may be timed).
PEAK = {'linear': 1., 'minjerk': 1.875, 'plateau': float(np.diff(_CURVES['plateau']).max() * (len(_TAU) - 1))}


def distance_fraction(time_fraction, profile='linear'):
    """Fraction of stroke length covered after this fraction of the stroke's time."""
    time_fraction = np.clip(time_fraction, 0.0, 1.0)
    if profile in _CURVES:
        return np.interp(time_fraction, _TAU, _CURVES[profile])
    return time_fraction


def time_fraction(distance_fraction_value, profile='linear'):
    """Inverse of distance_fraction: when the tip reaches this fraction of the stroke length."""
    distance_fraction_value = np.clip(distance_fraction_value, 0.0, 1.0)
    if profile in _CURVES:
        return np.interp(distance_fraction_value, _CURVES[profile], _TAU)
    return distance_fraction_value


def extract_paths(mask):
    from sweety_line_topology import extract_strokes
    return [stroke['points'].tolist() for stroke in extract_strokes(mask)[0]]


def taper(points):
    distances = np.r_[0., np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    reach = max(1., min(.15 * distances[-1], 18.))
    envelope = np.clip(np.minimum(distances, distances[-1] - distances) / reach, 0, 1)
    return .3 + .7 * envelope * envelope * (3 - 2 * envelope)


def weighted_lengths(points):
    from sweety_line_topology import turning
    steps = np.linalg.norm(np.diff(points, axis=0), axis=1)
    if not len(steps):
        return np.zeros(1)
    window = max(1, round(6 / max(.1, float(np.median(steps)))))
    turn = np.radians(turning(points, window))[1:] / 6
    return np.r_[0., np.cumsum(steps * (1 + 1.5 * np.clip(turn / (np.pi / 8), 0, 1)))]


def orient(strokes):
    ordered = []
    for stroke in sorted(strokes, key=lambda p: (min(y for x, y in p), min(x for x, y in p))):
        points = np.asarray(stroke, float)
        if len(points) > 2 and np.linalg.norm(points[0] - points[-1]) <= 2:
            ring = points[:-1] if np.array_equal(points[0], points[-1]) else points
            top = int(np.argmin(ring[:, 1] * 1000 + ring[:, 0]))
            points = np.r_[ring[top:], ring[:top], ring[top:top+1]]
            area = np.sum(points[:-1, 0] * points[1:, 1] - points[1:, 0] * points[:-1, 1])
            if area > 0:
                points = points[::-1]
        else:
            delta = points[-1] - points[0]
            backwards = delta[1] < 0 if abs(delta[1]) >= .6 * abs(delta[0]) else delta[0] < 0
            if backwards:
                points = points[::-1]
        ordered.append([tuple(point) for point in points])
    return ordered


def stamp_source(drawn, base, ink, allowed, held, point, radius, opacity):
    """Reference pressure footprint; retain source ink RGB and its antialiasing."""
    x, y = point
    h, w = allowed.shape
    left, right = max(0, int(x-radius-2)), min(w, int(x+radius+3))
    top, bottom = max(0, int(y-radius-2)), min(h, int(y+radius+3))
    if left >= right or top >= bottom:
        return
    ys, xs = np.ogrid[top:bottom, left:right]
    coverage = np.clip(radius + .5 - np.hypot(xs-x, ys-y), 0, 1) * opacity
    roi = (slice(top, bottom), slice(left, right))
    changed = (coverage > held[roi]) & allowed[roi]
    held[roi][changed] = coverage[changed]
    alpha = coverage[changed, None]
    drawn[roi][changed] = ink[roi][changed] * alpha + base[roi][changed] * (1-alpha)
