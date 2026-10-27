import React, {useEffect, useState} from 'react';
import {AbsoluteFill, Img, cancelRender, continueRender, delayRender, staticFile, useCurrentFrame} from 'remotion';
import type {CollageProps} from './collage-types';
import {elementState, timedState} from './collage-motion';

export const CollageVideo: React.FC<CollageProps> = (props) => {
  const frame = useCurrentFrame();
  const [fontHandle] = useState(() => delayRender('Loading collage font'));
  useEffect(() => {
    const font = new FontFace('CollageFont', `url("${staticFile(props.font)}")`);
    font.load().then((loaded) => {
      document.fonts.add(loaded);
      continueRender(fontHandle);
    }).catch((error) => cancelRender(error));
    return () => {document.fonts.delete(font);};
  }, [props.font, fontHandle]);
  const caption = props.captions.find((cue) => frame >= cue.startFrame && frame < cue.endFrame);
  return (
    <AbsoluteFill style={{backgroundColor: '#F8F5ED', overflow: 'hidden', fontFamily: 'CollageFont'}}>
      {/* A single persistent layer, outside every animated group. */}
      <Img src={staticFile(props.background)} style={{position: 'absolute', width: '100%', height: '100%', objectFit: 'cover'}} />
      {props.elements.map((item) => {
        const state = elementState(item, frame);
        const group = item.group ? timedState(item.group, frame) : {visible: true, x: 0, y: 0, scale: 1, opacity: 1};
        if (!state.visible || !group.visible) return null;
        return (
          <AbsoluteFill key={item.id} style={{zIndex: item.z, opacity: group.opacity,
            transform: `translate(${group.x}px, ${group.y}px) scale(${group.scale})`}}>
            <div style={{position: 'absolute', left: state.x, top: state.y, width: item.width, height: item.height,
              opacity: state.opacity, transformOrigin: `${item.origin[0] * 100}% ${item.origin[1] * 100}%`,
              transform: `rotate(${state.rotation}deg) scale(${state.scale})`, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
              {item.kind === 'image' ? <Img src={staticFile(item.src!)} style={{width: '100%', height: '100%', objectFit: item.fit}} />
                : <div style={{fontSize: item.fontSize, color: item.color, textAlign: 'center', lineHeight: 1.18, whiteSpace: 'pre-wrap'}}>{item.text}</div>}
            </div>
          </AbsoluteFill>
        );
      })}
      {caption ? <div style={{position: 'absolute', left: '7%', right: '7%', bottom: '5.5%', zIndex: 100000,
        textAlign: 'center', fontSize: props.height * .045, lineHeight: 1.3, color: '#202020',
        textShadow: '0 1px 2px #F8F5ED, 0 -1px 2px #F8F5ED'}}>{caption.text}</div> : null}
    </AbsoluteFill>
  );
};
