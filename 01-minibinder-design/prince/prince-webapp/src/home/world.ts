import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import protein from '../lib/protein.json';

// World-grid technique adapted from the user's Papercrane route/groundGrid.ts.
// Prince's world, geometries, chapter choreography, and palette are independent.
function applyGrid(material: THREE.MeshStandardMaterial) {
  material.customProgramCacheKey = () => 'prince-observatory-grid-v1';
  material.onBeforeCompile = shader => {
    shader.vertexShader = `varying vec3 vGridWorld;\n${shader.vertexShader}`.replace('#include <begin_vertex>', '#include <begin_vertex>\nvGridWorld = (modelMatrix * vec4(transformed, 1.0)).xyz;');
    shader.fragmentShader = `
      varying vec3 vGridWorld;
      float gridLine(vec2 p, float width) {
        vec2 footprint = max(fwidth(p), vec2(.00001));
        vec2 distanceToLine = abs(fract(p - .5) - .5) / footprint;
        return (1. - smoothstep(width * .35, width, min(distanceToLine.x, distanceToLine.y))) * (1. - smoothstep(.18, .65, max(footprint.x, footprint.y)));
      }
      ${shader.fragmentShader}`.replace('#include <color_fragment>', `#include <color_fragment>
        float minor = gridLine(vGridWorld.xz / 2.5, .8);
        float major = gridLine(vGridWorld.xz / 12.5, 1.);
        float fade = 1. - smoothstep(65., 160., length(vGridWorld.xz - vec2(40., 0.)));
        diffuseColor.rgb = mix(diffuseColor.rgb, vec3(.061,.047,.024), minor * .72 * fade);
        diffuseColor.rgb = mix(diffuseColor.rgb, vec3(.094,.071,.033), major * .8 * fade);`);
  };
}

const lerp = THREE.MathUtils.lerp;
const clamp = THREE.MathUtils.clamp;
const smooth = (t: number) => t * t * (3 - 2 * t);
const vec = (x: number, y: number, z: number) => new THREE.Vector3(x, y, z);

export function createWorld(host: HTMLElement, chapters: HTMLElement[], initialPaused: boolean) {
  let mobile = innerWidth < 651;
  let paused = initialPaused;
  let modal = false;
  let disposed = false;
  let trace = false;
  let needsRender = true;
  let frame = 0;
  let elapsed = 0;
  let last = performance.now();
  let progress = 0;
  let targetProgress = 0;
  const listeners: Array<() => void> = [];
  function listen(target: EventTarget, type: string, listener: EventListener, options?: AddEventListenerOptions) {
    target.addEventListener(type, listener, options);
    listeners.push(() => target.removeEventListener(type, listener, options));
  }
  const renderer = new THREE.WebGLRenderer({ antialias: false, alpha: false, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(devicePixelRatio, mobile ? 1.5 : 1.75));
  renderer.setSize(innerWidth, innerHeight);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.15;
  renderer.setClearColor('#14120e');
  host.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color('#14120e');
  scene.fog = new THREE.FogExp2('#14120e', .009);
  const camera = new THREE.PerspectiveCamera(37, innerWidth / innerHeight, .5, 330);
  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  const bloom = new UnrealBloomPass(new THREE.Vector2(innerWidth / 2, innerHeight / 2), .45, .45, 1.1);
  composer.addPass(bloom);
  composer.addPass(new OutputPass());

  const materials: THREE.Material[] = [];
  function standard(color: string, metalness = .15, roughness = .55, emissive?: string, intensity = 0) {
    const mat = new THREE.MeshStandardMaterial({ color, metalness, roughness, emissive: emissive || '#000000', emissiveIntensity: intensity });
    materials.push(mat); return mat;
  }
  const graphite = standard('#30291c', .55, .4);
  const dark = standard('#1c180f', .3, .6);
  const edge = standard('#665637', .45, .45);
  const gold = standard('#c8ad65', .18, .38);
  const ceramic = standard('#ded1a5', .15, .36);
  const ochre = standard('#9d813f', .25, .4);
  const light = standard('#ffe0a0', .2, .35, '#efb840', 2.1);
  const mint = standard('#a4c8b7', .2, .4, '#69b59e', .7);
  const coral = standard('#d59c8e', .1, .5, '#ec8c79', .7);
  const floorMaterial = standard('#19160f', .12, .86);
  applyGrid(floorMaterial);
  const geometries = new Set<THREE.BufferGeometry>();
  const boxGeo = new THREE.BoxGeometry(1, 1, 1); geometries.add(boxGeo);
  const sphereGeo = new THREE.IcosahedronGeometry(1, 2); geometries.add(sphereGeo);
  function mesh(geometry: THREE.BufferGeometry, material: THREE.Material, parent: THREE.Object3D = scene) {
    geometries.add(geometry);
    const object = new THREE.Mesh(geometry, material);
    object.castShadow = true; object.receiveShadow = true; parent.add(object); return object;
  }
  function box(parent: THREE.Object3D, at: number[], size: number[], material = graphite) {
    const object = mesh(boxGeo, material, parent); object.position.set(at[0], at[1], at[2]); object.scale.set(size[0], size[1], size[2]); return object;
  }
  function cylinder(parent: THREE.Object3D, radius: number, height: number, y: number, material = graphite) {
    const object = mesh(new THREE.CylinderGeometry(radius, radius, height, 96), material, parent); object.position.y = y; return object;
  }
  function ring(parent: THREE.Object3D, radius: number, tube: number, y: number, material = light, arc = Math.PI * 2) {
    const object = mesh(new THREE.TorusGeometry(radius, tube, 6, 160, arc), material, parent); object.rotation.x = Math.PI / 2; object.position.y = y; return object;
  }
  function path(points: THREE.Vector3[], material: THREE.Material, radius = .045, parent: THREE.Object3D = scene) {
    return mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points), 96, radius, 5, false), material, parent);
  }
  const dummy = new THREE.Object3D();
  const floor = mesh(new THREE.PlaneGeometry(550, 550), floorMaterial); floor.rotation.x = -Math.PI / 2; floor.position.y = -.2; floor.castShadow = false;
  const ambient = new THREE.HemisphereLight('#eee0bb', '#19150e', 2.3); scene.add(ambient);
  const key = new THREE.DirectionalLight('#fff4d8', 4.3); key.position.set(-24, 58, 32); key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048); key.shadow.camera.left = -50; key.shadow.camera.right = 50; key.shadow.camera.top = 45; key.shadow.camera.bottom = -45; key.shadow.camera.far = 160; key.shadow.normalBias = .07; key.shadow.bias = -.0002; scene.add(key, key.target);
  const rim = new THREE.DirectionalLight('#f6cf79', 3.8); rim.position.set(30, 25, -40); scene.add(rim);

  // 01 / An instrument built around a real, public structural specimen.
  const observatory = new THREE.Group(); scene.add(observatory);
  cylinder(observatory, 12.7, .7, .35, dark);
  cylinder(observatory, 11.8, .45, .92, graphite);
  cylinder(observatory, 9.8, .28, 1.28, dark);
  ring(observatory, 12.3, .045, .78, edge);
  ring(observatory, 10.1, .055, 1.43, light);
  ring(observatory, 7.7, .026, 1.47, edge);
  ring(observatory, 5.6, .025, 1.47, edge);
  ring(observatory, 13.4, .025, .06, ochre);
  const dial = new THREE.InstancedMesh(boxGeo, gold, 96); observatory.add(dial);
  for (let i = 0; i < 96; i++) {
    const angle = i / 96 * Math.PI * 2;
    dummy.position.set(Math.cos(angle) * 11.1, 1.2, Math.sin(angle) * 11.1);
    dummy.rotation.set(0, -angle, 0); dummy.scale.set(i % 8 === 0 ? .62 : .24, .035, .04); dummy.updateMatrix(); dial.setMatrixAt(i, dummy.matrix);
  }
  const arms = new THREE.Group(); observatory.add(arms);
  for (let i = 0; i < 3; i++) {
    const group = new THREE.Group(); group.rotation.y = i * Math.PI * 2 / 3; arms.add(group);
    box(group, [12.1, 2.1, 0], [1.3, 3, 2.4]);
    box(group, [12.1, 3.7, 0], [1.5, .18, 2.7], edge);
    box(group, [11.45, 2.9, 0], [.09, .65, 1.5], light);
    box(group, [13.1, .3, 0], [3, .3, 3.6], dark);
  }
  // Render sampled C-alpha positions as connected ceramic beads, not an atomic surface.
  const coordinates = protein.residues.map(residue => new THREE.Vector3(...residue.p as [number, number, number]));
  const bounds = new THREE.Box3().setFromPoints(coordinates);
  const center = bounds.getCenter(new THREE.Vector3());
  const size = bounds.getSize(new THREE.Vector3());
  const scale = 21 / Math.max(size.x, size.y, size.z);
  const points = coordinates.map(p => p.sub(center).multiplyScalar(scale));
  const specimen = new THREE.Group(); specimen.position.set(0, 15.3, 0); specimen.rotation.set(.05, -.55, -.18); observatory.add(specimen);
  const beadGeometry = new THREE.SphereGeometry(.64, 14, 10); geometries.add(beadGeometry);
  const beadMaterial = standard('#dccb91', .2, .34);
  const beads = new THREE.InstancedMesh(beadGeometry, beadMaterial, points.length); beads.castShadow = true; beads.receiveShadow = true; specimen.add(beads);
  const patchIds = new Set(['C350','C366','C367','C368','C370','C371']);
  points.forEach((point, i) => {
    dummy.position.copy(point); dummy.rotation.set(0, 0, 0); dummy.scale.setScalar(1); dummy.updateMatrix(); beads.setMatrixAt(i, dummy.matrix);
    beads.setColorAt(i, new THREE.Color(patchIds.has(protein.residues[i].id) ? '#ffcf68' : i % 7 === 0 ? '#b5a476' : '#e2d2a0'));
  });
  const backbone = new THREE.Group(); specimen.add(backbone);
  let run: THREE.Vector3[] = [];
  function addRun() { if (run.length > 1) path(run, gold, .16, backbone); run = []; }
  points.forEach((p, i) => { if (i && coordinates[i].distanceTo(coordinates[i - 1]) > scale * 5) addRun(); run.push(p); }); addRun();
  const orbit = ring(observatory, 14.5, .038, 13.2, edge, Math.PI * 1.48); orbit.rotation.set(1.04, .23, -.25);
  const orbitLight = ring(observatory, 14.5, .065, 13.2, light, .22); orbitLight.rotation.copy(orbit.rotation);
  const orbit2 = ring(observatory, 15.4, .025, 13.2, ochre, Math.PI * 1.2); orbit2.rotation.set(2.05, .1, .8);
  const scan = ring(observatory, 8.4, .028, 10, light);
  const scanFillMat = new THREE.MeshBasicMaterial({ color:'#edc15c', transparent:true, opacity:.035, side:THREE.DoubleSide, depthWrite:false }); materials.push(scanFillMat);
  const scanFill = mesh(new THREE.CircleGeometry(8.4, 80), scanFillMat, observatory); scanFill.rotation.x = -Math.PI / 2; scanFill.position.y = 10; scanFill.castShadow = false;

  // 02 / A terrain of hypotheses. Heights here are illustrative, not fitted scores.
  const surface = new THREE.Group(); surface.position.set(36, 0, -8); scene.add(surface);
  box(surface, [0,.25,0], [24,.5,22], dark);
  box(surface, [0,.57,0], [22.8,.14,20.8], graphite);
  const cells: {x:number;z:number;height:number;phase:number}[] = [];
  for (let row = -5; row <= 5; row++) for (let col = -5; col <= 5; col++) {
    if (Math.hypot(col * 1.05,row) > 5.5) continue;
    const height = 1 + 4.8 * Math.exp(-((col - 1.5)**2 + (row + .5)**2) / 8) + 1.6 * Math.exp(-((col + 3)**2 + (row - 2)**2)/3);
    cells.push({ x:col*1.83, z:row*1.83, height, phase:row*.5+col*.35 });
  }
  const cellMesh = new THREE.InstancedMesh(boxGeo, ceramic, cells.length); surface.add(cellMesh); cellMesh.castShadow = true; cellMesh.receiveShadow = true;
  cells.forEach((cell,i) => { cellMesh.setColorAt(i, new THREE.Color(cell.height > 4.4 ? '#eed08a' : cell.height > 2.5 ? '#b4964a' : '#62502c')); });
  const outline = path([vec(-10,.76,-10),vec(10,.76,-10),vec(10,.76,10)], light, .033, surface);
  outline.castShadow = false;
  const sensor = new THREE.Group(); surface.add(sensor);
  box(sensor, [-12,5,0], [.32,9,1], edge); box(sensor, [12,5,0], [.32,9,1], edge); box(sensor,[0,9.5,0],[24.3,.38,1],graphite); box(sensor,[0,9.24,0],[22.5,.04,.28],light);
  for (let i = 0; i < 4; i++) { box(surface,[-8+i*5,.85,12],[2.9,.3,.85],i === 2 ? light : edge); }

  // 03 / Independent gates: selected missing residues retain their STOP result.
  const preflight = new THREE.Group(); preflight.position.set(68, 0, 7); scene.add(preflight);
  cylinder(preflight, 12.4, .7, .35, dark); ring(preflight, 12.1, .035, .74, edge);
  const gates: THREE.Group[] = [];
  for (let i = 0; i < 3; i++) {
    const gate = new THREE.Group(); gate.position.set((i-1)*7,0,0); preflight.add(gate); gates.push(gate);
    const tone = i === 2 ? coral : mint;
    box(gate,[0,.65,0],[5.4,.5,8],graphite);
    box(gate,[-2.2,5.1,0],[.48,8.8,.8],edge); box(gate,[2.2,5.1,0],[.48,8.8,.8],edge); box(gate,[0,9.6,0],[4.8,.48,.8],edge);
    box(gate,[-1.92,5.1,0],[.04,8.4,.42],tone); box(gate,[1.92,5.1,0],[.04,8.4,.42],tone); box(gate,[0,9.32,0],[3.9,.04,.42],tone);
    for (let j=0;j<7;j++) box(gate,[0,.94,-3+j],[2.4,.045,.13],j%2 === 0 ? tone : edge);
    if(i === 2) { const x1=box(gate,[0,5.3,0],[3,.22,.24],coral); x1.rotation.z=Math.PI/4; const x2=box(gate,[0,5.3,0],[3,.22,.24],coral); x2.rotation.z=-Math.PI/4; }
    else { const mark=ring(gate,.8,.09,5.3,mint); mark.rotation.x=0; }
  }
  // Dashed, interrupted line marks a separate unresolved path.
  for (let i=0;i<9;i++) box(preflight,[7,.2,7+i*.66],[.065,.04,.33],coral);

  // 04 / Source folios: open, attributed, reviewable.
  const archive = new THREE.Group(); archive.position.set(102, 0, -6); scene.add(archive);
  box(archive,[0,.3,0],[25,.6,19],dark);
  const folios: THREE.Group[] = [];
  for (let i=0;i<5;i++) {
    const folio = new THREE.Group(); folio.position.set((i-2)*4.5, 2 + (2-Math.abs(i-2))*.8, 0); folio.rotation.set(-.18,0,-.1+(i-2)*.04); archive.add(folio); folios.push(folio);
    box(folio,[0,4.8,0],[3.75,8.7,.2],i===2 ? gold : graphite);
    box(folio,[-1.65,4.8,.14],[.045,8.1,.06],i===2 ? light : ochre);
    box(folio,[-.6,8,.16],[1.4,.08,.05],i===2 ? dark : gold);
    for(let row=0;row<8;row++) box(folio,[-.15,7.05-row*.48,.15],[row%3===0?2.4:2.8,.035,.05],i===2 ? ochre : edge);
    const seal=ring(folio,.38,.035,2.2,i===2?light:ochre); seal.rotation.x=0; seal.position.z=.18;
    box(archive,[(i-2)*4.5,.8,0],[3.9,.5,9],graphite);
    box(archive,[(i-2)*4.5,1.07,3.8],[2.6,.03,.07],i===2?light:edge);
  }
  ring(archive,14,.028,.12,ochre);

  // Luminous routes bind the four instruments into a single environment.
  const routeCurves = [
    new THREE.CatmullRomCurve3([vec(12.8,.19,0),vec(19,.19,0),vec(22,.19,-8),vec(24,.19,-8)]),
    new THREE.CatmullRomCurve3([vec(48,.19,-8),vec(52,.19,-8),vec(55,.19,7),vec(55.5,.19,7)]),
    new THREE.CatmullRomCurve3([vec(80.5,.19,7),vec(85,.19,7),vec(87,.19,-6),vec(89.5,.19,-6)]),
  ];
  const pulses: THREE.Mesh[] = [];
  routeCurves.forEach(curve=>{const route = mesh(new THREE.TubeGeometry(curve,70,.045,5,false),ochre); route.castShadow=false; const pulse=mesh(sphereGeo,light); pulse.scale.setScalar(.16); pulses.push(pulse);});

  // Quiet peripheral instruments create depth without filling the reading area.
  const satellites = new THREE.Group(); scene.add(satellites);
  [[-20,-19],[15,-26],[36,-30],[63,-19],[85,-24],[119,12],[92,26],[48,28],[17,27],[-22,18]].forEach(([x,z],i)=>{
    const station=new THREE.Group(); station.position.set(x,0,z); satellites.add(station);
    cylinder(station,2.8,.2,.1,dark); ring(station,3.15,.02,.05,edge);
    for(let j=0;j<5;j++)box(station,[(j-2)*.58,1.2+j%2*.5,0],[.17,2+j%2,2.4],i%3===0?gold:graphite);
    box(station,[0,.5,2],[2.3,.3,.16],ochre);
  });
  // Deterministic points, no remote assets and no random layout shifts.
  const dustArray = new Float32Array(160*3);
  for(let i=0;i<160;i++){dustArray[i*3]=Math.sin(i*71.73)*84+47;dustArray[i*3+1]=2+(Math.sin(i*39.41)*.5+.5)*25;dustArray[i*3+2]=Math.cos(i*23.17)*47;}
  const dustGeo = new THREE.BufferGeometry(); dustGeo.setAttribute('position',new THREE.BufferAttribute(dustArray,3)); geometries.add(dustGeo);
  const dustMat = new THREE.PointsMaterial({color:'#e7d3a0',size:.055,transparent:true,opacity:.55,depthWrite:false}); materials.push(dustMat); const dust=new THREE.Points(dustGeo,dustMat);scene.add(dust);

  let chapterOffsets: number[] = [];
  function measure() { chapterOffsets = chapters.map(chapter=>chapter.offsetTop); }
  function readProgress() {
    const y=scrollY; let index=0;
    while(index<chapterOffsets.length-1 && y>=chapterOffsets[index+1])index++;
    targetProgress=index===4?4:index+clamp((y-chapterOffsets[index])/(chapterOffsets[index+1]-chapterOffsets[index]),0,1);
    needsRender=true; wake();
  }
  const pointer=new THREE.Vector2(0,0), mouse=new THREE.Vector2(0,0),raycaster=new THREE.Raycaster();
  let pointerPresent=false, pointerX=0,pointerY=0;
  const tooltip=document.getElementById('residue-label')!;
  const anchors=[vec(0,7,0),vec(36,3,-8),vec(68,3,7),vec(102,4,-6),vec(0,8,0)];
  const desktopPositions=[vec(35,38,51),vec(35,34,44),vec(28,23,41),vec(26,22,43),vec(36,32,52)];
  const mobilePositions=[vec(35,39,56),vec(30,33,47),vec(26,28,45),vec(25,27,48),vec(35,39,56)];
  const look=new THREE.Vector3(),pos=new THREE.Vector3(),p0=new THREE.Vector3(),p1=new THREE.Vector3(),right=new THREE.Vector3(),up=new THREE.Vector3();
  function pose(index:number,outPos:THREE.Vector3,outLook:THREE.Vector3){
    outLook.copy(anchors[index]); outPos.copy(mobile?mobilePositions[index]:desktopPositions[index]);
    right.set(outPos.z,0,-outPos.x).normalize();
    // Offset in camera-local axes: field on the right / below copy on narrow screens.
    if(mobile){up.crossVectors(outPos.clone().normalize(),right).normalize();outLook.addScaledVector(up,16.7);}
    else outLook.addScaledVector(right,-13.3);
    outPos.add(outLook);
  }
  const look0=new THREE.Vector3(),look1=new THREE.Vector3();
  function animate(now:number){
    frame=0;if(disposed||document.hidden)return;
    // The first RAF timestamp can precede the call that schedules it.
    const dt=clamp((now-last)/1000,0,.05);last=now;
    const live=!paused&&!modal;
    if(live)elapsed+=dt;
    const moving=Math.abs(progress-targetProgress)>.0001;
    if(!live&&!needsRender&&!moving)return;
    progress=paused?targetProgress:lerp(progress,targetProgress,1-Math.exp(-dt*7.5));
    const index=Math.min(3,Math.floor(progress));const blend=smooth(clamp(progress-index,0,1));
    pose(index,p0,look0);pose(index+1,p1,look1);pos.lerpVectors(p0,p1,blend);look.lerpVectors(look0,look1,blend);
    mouse.lerp(pointer,live?.035:0);pos.x+=mouse.x*1.05;pos.y+=mouse.y*.55;
    camera.position.copy(pos);camera.lookAt(look);
    key.position.set(look.x-24,58,look.z+32);key.target.position.set(look.x,0,look.z);
    specimen.rotation.y=-.55+Math.sin(elapsed*.16)*.22;specimen.position.y=15.3+Math.sin(elapsed*.55)*.25;
    const beadScale=trace?.22:1;
    // Keep coordinates fixed in trace mode; only bead radius changes through instance matrices.
    if(beads.userData.trace!==trace){points.forEach((p,i)=>{dummy.position.copy(p);dummy.rotation.set(0,0,0);dummy.scale.setScalar(beadScale);dummy.updateMatrix();beads.setMatrixAt(i,dummy.matrix);});beads.instanceMatrix.needsUpdate=true;beads.userData.trace=trace;}
    orbitLight.rotation.z=orbit.rotation.z+elapsed*.12;
    scan.position.y=11.5+Math.sin(elapsed*.38)*7;scanFill.position.y=scan.position.y;
    scan.material=trace?edge:light;
    sensor.position.z=Math.sin(elapsed*.26)*7.2;
    cells.forEach((cell,i)=>{const h=cell.height+(live?Math.sin(elapsed*.75+cell.phase)*.11:0);dummy.position.set(cell.x,.65+h/2,cell.z);dummy.rotation.set(0,0,0);dummy.scale.set(1.64,h,1.64);dummy.updateMatrix();cellMesh.setMatrixAt(i,dummy.matrix);});cellMesh.instanceMatrix.needsUpdate=true;
    folios.forEach((folio,i)=>{folio.position.y=2+(2-Math.abs(i-2))*.8+Math.sin(elapsed*.5+i*.7)*.16;});
    pulses.forEach((pulse,i)=>pulse.position.copy(routeCurves[i].getPoint((elapsed*.095+i*.31)%1)));
    dust.rotation.y=Math.sin(elapsed*.03)*.03;
    if(pointerPresent&&progress<.4&&!mobile&&!modal){
      raycaster.setFromCamera(pointer,camera);const hit=raycaster.intersectObject(beads)[0];
      if(hit&&hit.instanceId!==undefined){const residue=protein.residues[hit.instanceId];tooltip.textContent=`${residue.id} · ${residue.name} / Cα`;tooltip.style.left=`${Math.min(pointerX+17,innerWidth-145)}px`;tooltip.style.top=`${pointerY-33}px`;tooltip.hidden=false;}else tooltip.hidden=true;
    }else tooltip.hidden=true;
    composer.render();needsRender=false;
    if(!host.classList.contains('is-ready'))host.classList.add('is-ready');
    if(live||moving)frame=requestAnimationFrame(animate);
  }
  function wake(){if(!frame&&!disposed&&!document.hidden){last=performance.now();frame=requestAnimationFrame(animate);}}
  listen(window,'scroll',readProgress,{passive:true});
  listen(window,'resize',()=>{mobile=innerWidth<651;camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();renderer.setPixelRatio(Math.min(devicePixelRatio,mobile?1.5:1.75));renderer.setSize(innerWidth,innerHeight);composer.setSize(innerWidth,innerHeight);measure();readProgress();});
  listen(window,'pointermove',((event:PointerEvent)=>{pointer.set(event.clientX/innerWidth*2-1,-event.clientY/innerHeight*2+1);pointerX=event.clientX;pointerY=event.clientY;pointerPresent=true;if(!paused){needsRender=true;wake();}}) as EventListener,{passive:true});
  listen(document,'pointerleave',()=>{pointerPresent=false;pointer.set(0,0);tooltip.hidden=true;});
  listen(window,'prince:motion',((event:CustomEvent<boolean>)=>{paused=event.detail;needsRender=true;wake();}) as EventListener);
  listen(window,'prince:trace',((event:CustomEvent<boolean>)=>{trace=event.detail;needsRender=true;wake();}) as EventListener);
  listen(window,'prince:dialog',((event:CustomEvent<boolean>)=>{modal=event.detail;needsRender=true;wake();}) as EventListener);
  listen(document,'visibilitychange',()=>{if(document.hidden){cancelAnimationFrame(frame);frame=0;}else{needsRender=true;wake();}});
  listen(renderer.domElement,'webglcontextlost',(event)=>{event.preventDefault();cancelAnimationFrame(frame);frame=0;host.classList.remove('is-ready');});
  listen(renderer.domElement,'webglcontextrestored',()=>{needsRender=true;wake();});
  measure();readProgress();progress=targetProgress;wake();
  return ()=>{disposed=true;cancelAnimationFrame(frame);listeners.forEach(remove=>remove());geometries.forEach(geometry=>geometry.dispose());materials.forEach(material=>material.dispose());bloom.dispose();composer.dispose();renderer.dispose();renderer.domElement.remove();};
}
