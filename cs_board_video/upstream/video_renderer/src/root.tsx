import React from 'react';
import {Composition} from 'remotion';
import {InfographicVideo} from './video';
import type {InfographicVideoProps} from './types';
import {CollageVideo} from './collage';
import type {CollageProps} from './collage-types';

const defaults: InfographicVideoProps = {
  fps: 30,
  width: 1920,
  height: 1080,
  totalDurationMs: 3000,
  totalDurationFrames: 90,
  style: '粗线扁平国风卡通',
  pages: [],
};

export const RemotionRoot: React.FC = () => (
  <>
  <Composition
    id="DynamicInfographic"
    component={InfographicVideo}
    width={1920}
    height={1080}
    fps={30}
    durationInFrames={90}
    defaultProps={defaults}
    calculateMetadata={({props}) => ({
      width: props.width,
      height: props.height,
      fps: props.fps,
      durationInFrames: Math.max(1, props.totalDurationFrames),
      props,
      defaultCodec: 'h264',
      defaultPixelFormat: 'yuv420p',
    })}
  />
  <Composition
    id="CollageVideo"
    component={CollageVideo}
    width={1920} height={1080} fps={30} durationInFrames={90}
    defaultProps={{compositionType: 'collage', width: 1920, height: 1080, fps: 30,
      totalDurationFrames: 90, background: '', font: '', elements: [], captions: []} satisfies CollageProps}
    calculateMetadata={({props}) => ({width: props.width, height: props.height, fps: props.fps,
      durationInFrames: props.totalDurationFrames, props})}
  />
  </>
);
