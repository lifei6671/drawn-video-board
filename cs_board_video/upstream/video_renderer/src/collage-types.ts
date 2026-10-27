export type Effect = {
  type: 'none' | 'fade' | 'slide-left' | 'slide-right' | 'slide-up' | 'slide-down' | 'pop';
  frames: number;
  distance: number;
};
export type Timed = {startFrame: number; endFrame: number; enter: Effect; exit: Effect};
export type Property = 'x' | 'y' | 'scale' | 'rotation' | 'opacity';
export type CollageElement = Timed & {
  id: string;
  kind: 'image' | 'text';
  x: number; y: number; width: number; height: number; z: number;
  scale: number; rotation: number; opacity: number;
  origin: [number, number];
  group: Timed | null;
  src: string | null;
  text: string; fontSize: number; color: string; fit: 'contain' | 'cover';
  motion: {type: 'none' | 'sway' | 'float' | 'spin'; amplitude: number; periodFrames: number};
  keyframes: Partial<Record<Property, {frames: number[]; values: number[]}>>;
};
export type Caption = {id: string; text: string; startFrame: number; endFrame: number};
export type CollageProps = {
  compositionType: 'collage'; width: number; height: number; fps: number;
  totalDurationFrames: number; background: string; font: string;
  elements: CollageElement[]; captions: Caption[];
};
