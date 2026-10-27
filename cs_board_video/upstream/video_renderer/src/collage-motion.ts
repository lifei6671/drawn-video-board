import type {CollageElement, Effect, Property, Timed} from './collage-types';

const clamp = (n: number) => Math.max(0, Math.min(1, n));
const easeOut = (n: number) => 1 - (1 - clamp(n)) ** 3;

// All motion is evaluated from an absolute frame. Seeking and concurrent rendering
// must produce the same pixels, with no CSS timers or mutable animation state.
function effectAt(effect: Effect, progress: number, exiting: boolean) {
  const remaining = exiting ? easeOut(progress) : 1 - easeOut(progress);
  const d = remaining * effect.distance;
  return {
    x: effect.type === 'slide-left' ? -d : effect.type === 'slide-right' ? d : 0,
    y: effect.type === 'slide-up' ? (exiting ? -d : d) : effect.type === 'slide-down' ? (exiting ? d : -d) : 0,
    opacity: effect.type === 'none' ? 1 : 1 - remaining,
    scale: effect.type === 'pop' ? 1 - .18 * remaining : 1,
  };
}

export function timedState(item: Timed, frame: number) {
  const visible = frame >= item.startFrame && frame < item.endFrame;
  const enter = effectAt(item.enter, item.enter.frames ? (frame - item.startFrame) / item.enter.frames : 1, false);
  const leave = effectAt(item.exit, item.exit.frames ? (frame - (item.endFrame - item.exit.frames)) / Math.max(1, item.exit.frames - 1) : 0, true);
  return {visible, x: enter.x + leave.x, y: enter.y + leave.y,
    scale: enter.scale * leave.scale, opacity: visible ? enter.opacity * leave.opacity : 0};
}

function valueAt(item: CollageElement, prop: Property, frame: number) {
  const lane = item.keyframes[prop];
  if (!lane) return item[prop];
  if (frame <= lane.frames[0]) return lane.values[0];
  for (let i = 1; i < lane.frames.length; i++) {
    if (frame <= lane.frames[i]) {
      const progress = (frame - lane.frames[i - 1]) / (lane.frames[i] - lane.frames[i - 1]);
      return lane.values[i - 1] + (lane.values[i] - lane.values[i - 1]) * progress;
    }
  }
  return lane.values[lane.values.length - 1];
}

export function elementState(item: CollageElement, frame: number) {
  const state = timedState(item, frame);
  const local = frame - item.startFrame;
  const phase = local / item.motion.periodFrames * 2 * Math.PI;
  return {...state,
    x: valueAt(item, 'x', local) + state.x,
    y: valueAt(item, 'y', local) + state.y + (item.motion.type === 'float' ? Math.sin(phase) * item.motion.amplitude : 0),
    rotation: valueAt(item, 'rotation', local) + (item.motion.type === 'sway' ? Math.sin(phase) * item.motion.amplitude : item.motion.type === 'spin' ? local / item.motion.periodFrames * 360 : 0),
    scale: valueAt(item, 'scale', local) * state.scale,
    opacity: valueAt(item, 'opacity', local) * state.opacity,
  };
}
