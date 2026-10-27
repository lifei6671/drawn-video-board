import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import ts from 'typescript';

// Exercise the shipped pure frame evaluator without adding a runtime test loader.
const source = fs.readFileSync(new URL('./src/collage-motion.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS}}).outputText;
const context = {exports: {}};
vm.runInNewContext(compiled, context);
const {elementState, timedState} = context.exports;
const none = {type:'none', frames:0, distance:0};
const element = {startFrame:30, endFrame:150, enter:{type:'slide-up',frames:15,distance:100},
  exit:{type:'fade',frames:15,distance:0},x:100,y:200,scale:1,rotation:0,opacity:1,
  motion:{type:'sway',amplitude:4,periodFrames:60},keyframes:{}};
assert.equal(elementState(element,29).visible,false);
assert.equal(elementState(element,30).opacity,0);
assert.equal(elementState(element,30).y,300);
assert.equal(elementState(element,45).y,200);
assert.equal(elementState(element,45).rotation,4);
assert.equal(elementState(element,149).opacity,0);
assert.equal(elementState(element,150).visible,false);
const seekResult=JSON.stringify(elementState(element,73));
for(let f=0;f<150;f++) elementState(element,f);
assert.equal(JSON.stringify(elementState(element,73)),seekResult);
const keyed={...element,enter:none,exit:none,keyframes:{x:{frames:[0,60],values:[100,400]}}};
assert.equal(elementState(keyed,60).x,250);
assert.equal(elementState(keyed,120).x,400);
// A crossfade changes only foreground group state, on the same absolute clock.
const outgoing={startFrame:0,endFrame:90,enter:none,exit:{type:'fade',frames:30,distance:0}};
const incoming={startFrame:60,endFrame:150,enter:{type:'fade',frames:30,distance:0},exit:none};
assert.ok(timedState(outgoing,75).opacity>0 && timedState(outgoing,75).opacity<1);
assert.ok(timedState(incoming,75).opacity>0 && timedState(incoming,75).opacity<1);
assert.equal(timedState(incoming,90).opacity,1);
console.log('Collage motion: frame boundaries, keyframes, deterministic seeking and overlapping groups passed.');
