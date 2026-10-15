/** Original illustrative rover geometry. Build only; the browser needs no kit. */
import {readFileSync, writeFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname, resolve} from 'node:path';
import * as k from '../vendor/anatomy/kit/iso-kit.mjs';
import * as G from '../vendor/anatomy/kit/lathe.mjs';
import * as A from '../vendor/anatomy/kit/audit.mjs';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const W = 900, H = 590;
const fitPoints = [
  ...k.boxCorners({x:-126,y:-118,w:252,d:236,r:0},5,67),
  ...k.boxCorners({x:48,y:-58,w:50,d:28,r:0},162,178),
  ...k.boxCorners({x:-120,y:-60,w:23,d:23,r:0},126,133),
  [140,38,118],[-56,-49,149],
];
const P = k.fitProjection(fitPoints,W,H,{pad:32,azimuth:54,elevation:34});
const R = A.recorder(P);
const components = [
  ['battery','Battery pack','power',[-73,10,97]], ['pdu','Power distribution','power',[-5,18,86]],
  ['drive_fl','Front left drive','drive',[95,-112,60]], ['drive_ml','Middle left drive','drive',[0,-112,60]], ['drive_rl','Rear left drive','drive',[-95,-112,60]],
  ['drive_fr','Front right drive','drive',[95,112,37]], ['drive_mr','Middle right drive','drive',[0,112,37]], ['drive_rr','Rear right drive','drive',[-95,112,37]],
  ['compute','Onboard computer','avionics',[48,14,88]], ['radio','Radio','avionics',[-70,-39,95]],
  ['gnss','GNSS receiver','avionics',[-111,-48,135]], ['camera','Navigation cameras','avionics',[73,-40,176]],
  ['arm','Manipulator','payload',[137,29,111]], ['science','Science bay','payload',[45,48,89]],
];
const layerOf = Object.fromEntries(components.map(([id,,layer])=>[id,layer]));
function put(name, id, at, paths, shape, {tone='mid', inner='', extra='', material='metal'}={}) {
  const svg = `<g class="ra-part ra-${material}" data-component="${id || ''}" data-layer="${layerOf[id] || 'structure'}" data-solid="${name}">${k.solidSvg(paths,{tone,crease:'lo',inner})}${extra}</g>`;
  return R.put({name, at, svg, shapes:[R.solid(shape)]});
}
function slab(name,id,x,y,w,d,z,h,{r=1,details=true,...style}={}) {
  const plan={x,y,w,d,r};
  const top=z+h;
  let extra=style.extra||'';
  if(details && w>14 && d>12) {
    extra+=k.lineSvg(k.planOutline(k.insetPlan(plan,2.8),top,P,4),{tone:'faint'});
    extra+=k.dotsSvg(k.corners(plan,3.6).map(([a,b])=>k.iso([a,b,top],P)),{size:.75,tone:'hi'});
  }
  return put(name,id,[x+w/2,y+d/2,z+h/2],k.slabOf(plan,z,h,P,4,.65),A.slab(plan,z,h,{name,owner:id||name}),{...style,extra});
}
function turned(name,id,origin,axis,profile,{material='metal',extra='',...style}={}) {
  const F=G.frameAlong(origin,axis);
  const at=G.pointOf(F,(profile[0][0]+profile.at(-1)[0])/2,0,0);
  return put(name,id,at,G.solidOf(profile,F,P,{steps:48}),A.solid(F,profile,{name,owner:id||name}),{material,extra:typeof extra==='function'?extra(F):extra,...style});
}
function disc(name,id,x,y,z,r,h,style={}) {return turned(name,id,[x,y,z],[0,0,1],[[0,r],[h,r]],style);}

// Six independent drive assemblies; each motor face sits flush on its wheel drum.
for (const [side,sign] of [['l',-1],['r',1]]) {
  for (const [position,x] of [['f',95],['m',0],['r',-95]]) {
    const id=`drive_${position}${side}`, y=sign*88;
    slab(`${id}.mount`,id,x-7,sign>0?60:-68,14,8,36,24,{r:.6});
    turned(`${id}.axle`,id,[x,sign*68,36],[0,sign,0],[[0,6],[20,6]]);
    const F=G.frameOf([x,y,36],[0,sign,0],[1,0,0],[0,0,-sign]);
    const meridian=[[0,0],[0,28],[2,31],[24,31],[26,28],[26,0]];
    const ribs=G.ribsOf(F,2,24,31,28,P,{seams:true});
    const tread=k.lineSvg(ribs,{tone:'lo'});
    put(`${id}.tire`,id,[x,y+sign*13,36],G.lathe(meridian,F,P,{steps:72}),A.lathe(F,meridian,{name:`${id}.tire`,owner:id,ground:true}),{material:'rubber',tone:'lo',extra:tread});
    turned(`${id}.motor`,id,[x,y+sign*26,36],[0,sign,0],[[0,14],[2,14]],{extra:frame=>{
      const points=G.dotsOf(frame,2,10,8,P,{all:true});
      return k.dotsSvg(points,{size:.9,tone:'hi'});
    }});
    turned(`${id}.hub`,id,[x,y+sign*28,36],[0,sign,0],[[0,6.4],[2,6.4]],{tone:'hi'});
  }
}

// Load-bearing frame and open electronics deck. Every board lands on the floor.
slab('frame.floor','',-125,-68,250,136,60,7,{r:5,material:'frame'});
slab('frame.rear','',-125,-68,6,136,67,12,{r:1,material:'frame'});
slab('frame.front','',119,-68,6,136,67,12,{r:1,material:'frame'});
slab('frame.far','',-119,-68,238,6,67,12,{r:1,material:'frame'});
slab('frame.near','',-119,62,238,6,67,9,{r:1,material:'frame'});

// Rear battery cassette: four cylindrical cells in one tray, two retaining rails.
slab('battery.tray','battery',-111,-13,75,65,67,4,{r:3});
for(let i=0;i<4;i++) {
  const x=-101+i*17;
  turned(`battery.cell${i}`,'battery',[x,-8,84],[0,1,0],[[0,8],[56,8]],{material:'battery',extra:F=>k.lineSvg(G.ribsOf(F,0,56,8,4,P,{seams:true}),{tone:'faint'})});
}
// Cell mounts meet each cell's bottom at z=76; rails hold the cassette to the deck.
slab('battery.cradle','battery',-110,-10,74,60,71,5,{r:1,details:false});
slab('battery.railA','battery',-111,-13,75,5,76,8,{r:.5,details:false});
slab('battery.railB','battery',-111,48,75,4,76,8,{r:.5,details:false});

slab('pdu.case','pdu',-25,-9,39,58,67,15,{r:2,material:'pcb',inner:k.lineSvg(k.sideSeam({x:-25,y:-9,w:39,d:58,r:2},77,P,4),{tone:'lo'})});
slab('pdu.fuses','pdu',-21,-5,31,16,82,5,{r:1,details:false,extra:Array.from({length:5},(_,i)=>k.lineSvg(k.planOutline({x:-19+i*5.5,y:-3,w:3.2,d:12,r:.6},87,P,3),{tone:'mid'})).join('')});
slab('pdu.terminals','pdu',-21,31,31,13,82,4,{r:1,details:false,extra:k.dotsSvg(Array.from({length:6},(_,i)=>k.iso([-18+i*5,37.5,86],P)),{size:1,tone:'hi'})});

slab('compute.case','compute',24,-10,60,40,67,14,{r:2,material:'pcb'});
slab('compute.sink','compute',30,-4,48,28,81,7,{r:1,details:false,extra:Array.from({length:10},(_,i)=>k.lineSvg(k.planOutline({x:32+i*4.5,y:-2,w:1.8,d:24,r:.3},88,P,2),{tone:'mid'})).join('')});

slab('radio.case','radio',-97,-59,50,35,67,17,{r:2,extra:k.lineSvg(Array.from({length:5},(_,i)=>k.planOutline({x:-91,y:-53+i*5,w:28,d:2,r:.6},84,P,3)).join(''),{tone:'lo'})});
disc('radio.socket','radio',-56,-49,84,3.2,4);
turned('radio.antenna','radio',[-56,-49,88],[0,0,1],[[0,1.2],[61,1.2]],{tone:'hi'});

slab('gnss.mount','gnss',-116,-59,15,22,67,5,{r:1});
disc('gnss.post','gnss',-108.5,-48,72,3,54);
disc('gnss.puck','gnss',-108.5,-48,126,11,7,{tone:'hi'});

slab('camera.foot','camera',57,-58,32,25,67,6,{r:2});
slab('camera.mast','camera',66,-53,14,14,73,83,{r:2,extra:k.lineSvg(k.segment([70,-39,73],[70,-39,156],P),{tone:'faint'})});
disc('camera.pan','camera',73,-46,156,12,6);
slab('camera.head','camera',48,-58,50,24,162,16,{r:3,extra:k.lineSvg(k.sideSeam({x:48,y:-58,w:50,d:24,r:3},169,P,4),{tone:'lo'})});
for(const x of [58,88]) turned(`camera.lens${x}`,'camera',[x,-34,170],[0,1,0],[[0,5.5],[4,5.5]],{material:'glass',tone:'hi',extra:F=>k.lineSvg(G.ribsOf(F,0,4,5.5,12,P,{seams:true}),{tone:'lo'})});

slab('science.case','science',25,37,61,20,67,15,{r:2});
for(let i=0;i<3;i++) disc(`science.sample${i}`,'science',37+i*18,47,82,6,7,{material:'glass',tone:'hi'});

// Folded manipulator: plinth, shoulder, two orthogonal links and instrument tool.
slab('arm.base','arm',92,12,25,40,67,7,{r:2});
disc('arm.turntable','arm',104,32,74,11,7);
slab('arm.upright','arm',98,26,12,12,81,28,{r:1});
slab('arm.link','arm',98,26,42,12,109,9,{r:1});
slab('arm.tool','arm',132,26,8,12,92,17,{r:1});

A.settle(R,P);
R.items.sort((a,b)=>a.key-b.key);
A.auditOrExit(R,P);

const symbols={nominal:'·',warning:'!',fault:'×',offline:'−',unknown:'?',stale:'◷'};
const markers=components.map(([id,label,layer,point],i)=>{
  const [x,y]=k.iso(point,P);
  return `<g class="ra-hotspot" data-hit="${id}" data-component="${id}" data-layer="${layer}" data-status="unknown" transform="translate(${x.toFixed(2)} ${y.toFixed(2)})" tabindex="${i===0?'0':'-1'}" role="button" aria-label="${label}: unknown" aria-pressed="false"><title>${label}: unknown</title><circle class="ra-hotspot-target" r="14"/><circle class="ra-hotspot-ring" r="8.5"/><text class="ra-status-symbol" text-anchor="middle" y="3.6">?</text></g>`;
}).join('');
const svg=k.figureSvg({width:W,height:H,label:'Illustrative six-wheel rover systems cutaway. Select a component to inspect its reported health. Geometry is a reference layout, not measured rover CAD.',body:R.items.map(v=>v.svg).join('')+markers});
const data={svg,components:components.map(([id,label,layer])=>({id,label,layer})),symbols,solidCount:R.items.length};
const runtime=readFileSync(resolve(ROOT,'scripts/rover_anatomy_runtime.js'),'utf8');
const output=`/* Generated by scripts/build_rover_anatomy.mjs; original rover geometry.\n * Anatomy kit MIT Copyright (c) 2026 Ryan; see vendor/anatomy/LICENSE. */\n(function () {\n'use strict';\nconst DATA = ${JSON.stringify(data)};\n${runtime}\n})();\n`;
writeFileSync(resolve(ROOT,'web/rover-anatomy.js'),output);
if(process.argv.includes('--preview')) {
  const css=readFileSync(resolve(ROOT,'web/rover-anatomy.css'),'utf8');
  for(const theme of ['dark','light']) writeFileSync(`/tmp/rover-anatomy-${theme}.html`,`<!doctype html><html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Rover anatomy verification</title><style>body{margin:0;background:${theme==='light'?'#e8edef':'#10171d'};color:${theme==='light'?'#22313a':'#dce4e9'};font-family:monospace}main{max-width:940px;margin:30px auto}.iso-plate{border:1px solid #45515b;padding:16px}header,footer{display:flex;justify-content:space-between;padding:14px}p{font-size:12px;padding:14px} ${css}</style><main class="iso-plate"><header><span>01 / ROVER SYSTEMS</span><span>ILLUSTRATIVE CUTAWAY</span></header><div id="view" data-theme="${theme}"></div><footer><span>Select a component</span><span data-readout>Battery · unknown</span></footer><p>Illustrative six-wheel reference. Health indicators follow supplied telemetry; this standalone verification page has no vehicle connection.</p></main><script>${output}</script><script>window.anatomy=RoverAnatomy.mount(document.getElementById('view'),{onSelect:id=>document.querySelector('[data-readout]').textContent=id});anatomy.select('battery');</script></html>`);
}
console.log(`Built rover anatomy: ${R.items.length} recorded solids; ${components.length} health components; ${Buffer.byteLength(output)} bytes.`);
