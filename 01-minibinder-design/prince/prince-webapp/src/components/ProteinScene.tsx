import { useEffect, useRef, useState } from 'react';
import protein from '../lib/protein.json';

export default function ProteinScene({ compact = false }: { compact?: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const controller = useRef<{ mode: (value: string) => void; reset: () => void; pause: (value: boolean) => void }>();
  const [mode, setMode] = useState('patch');
  const [paused, setPaused] = useState(false);
  const [failed, setFailed] = useState(false);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let dispose = () => {}; let cancelled = false;
    async function start() {
      const THREE = await import('three');
      const { OrbitControls } = await import('three/examples/jsm/controls/OrbitControls.js');
      if (cancelled || !canvas.current) return;
      const el=canvas.current;
      const renderer=new THREE.WebGLRenderer({canvas:el,alpha:true,antialias:true,powerPreference:'low-power'});
      renderer.setPixelRatio(Math.min(window.devicePixelRatio,1.75));
      renderer.setClearColor(0x000000,0); renderer.outputColorSpace=THREE.SRGBColorSpace;
      const scene=new THREE.Scene();
      const camera=new THREE.PerspectiveCamera(32,1,.1,1000);
      const points=protein.residues.map(r=>new THREE.Vector3(...r.p));
      const center=new THREE.Box3().setFromPoints(points).getCenter(new THREE.Vector3());
      points.forEach(p=>p.sub(center));
      const radius=new THREE.Box3().setFromPoints(points).getBoundingSphere(new THREE.Sphere()).radius;
      camera.position.set(radius*.6,radius*.15,radius*3.9);
      const controls=new OrbitControls(camera,el);
      controls.enableZoom=false; controls.enablePan=false; controls.enableDamping=true;
      controls.autoRotate=!window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      controls.autoRotateSpeed=.55;controls.rotateSpeed=.6;
      scene.add(new THREE.HemisphereLight(0xffffff,0x354835,2.5));
      const light=new THREE.DirectionalLight(0xfff6de,3.8);light.position.set(-30,50,80);scene.add(light);
      const rim=new THREE.DirectionalLight(0xf7c49c,2);rim.position.set(50,-10,-40);scene.add(rim);
      const group=new THREE.Group();scene.add(group);
      const material=new THREE.MeshStandardMaterial({color:0x9ba98c,roughness:.36,metalness:.1});
      const beadMaterial=new THREE.MeshStandardMaterial({color:0xbac2a5,roughness:.35,metalness:.12});
      const orange=new THREE.MeshStandardMaterial({color:0xd66437,roughness:.28,metalness:.14,emissive:0x8e250a,emissiveIntensity:.12});
      const traces=new THREE.Group();const beads=new THREE.Group();const patches=new THREE.Group();group.add(traces,beads,patches);
      // Break the trace at unresolved gaps; never draw invented peptide connections.
      const segments: typeof points[]=[];let segment: typeof points=[];
      points.forEach((point,i)=>{if(i>0&&point.distanceTo(points[i-1])>5){if(segment.length>1)segments.push(segment);segment=[];}segment.push(point);});
      if(segment.length>1)segments.push(segment);
      segments.forEach(segment=>{const curve=new THREE.CatmullRomCurve3(segment);const geometry=new THREE.TubeGeometry(curve,segment.length*5,.62,7,false);traces.add(new THREE.Mesh(geometry,material));});
      const sphere=new THREE.SphereGeometry(1.2,12,10);
      const spheres=new THREE.InstancedMesh(sphere,beadMaterial,points.length);
      const matrix=new THREE.Matrix4();points.forEach((p,i)=>{matrix.makeTranslation(p.x,p.y,p.z);spheres.setMatrixAt(i,matrix);});beads.add(spheres);beads.visible=false;
      const patchSet=new Set(protein.patches[0].residues);
      points.forEach((p,i)=>{if(patchSet.has(protein.residues[i].id)){const dot=new THREE.Mesh(new THREE.SphereGeometry(1.9,20,16),orange);dot.position.copy(p);patches.add(dot);}});
      const resize=()=>{const {width,height}=el.getBoundingClientRect();if(!width||!height)return;renderer.setSize(width,height,false);camera.aspect=width/height;camera.updateProjectionMatrix();};
      const observer=new ResizeObserver(resize);observer.observe(el);resize();
      let visible=true;const viewObserver=new IntersectionObserver(([entry])=>{visible=entry.isIntersecting;});viewObserver.observe(el);
      let frame=0;const draw=()=>{frame=requestAnimationFrame(draw);if(!visible||document.hidden)return;controls.update();renderer.render(scene,camera);};draw();
      controller.current={mode(value){beads.visible=value==='residues';traces.visible=value!=='residues';patches.visible=value==='patch';material.color.set(value==='trace'?0x728c76:0x9ba98c);},reset(){controls.reset();},pause(value){controls.autoRotate=!value&&!window.matchMedia('(prefers-reduced-motion: reduce)').matches;}};
      setReady(true);
      dispose=()=>{cancelAnimationFrame(frame);observer.disconnect();viewObserver.disconnect();controls.dispose();scene.traverse(o=>{if(o instanceof THREE.Mesh){o.geometry.dispose();}});material.dispose();beadMaterial.dispose();orange.dispose();renderer.dispose();};
    }
    start().catch(()=>{if(!cancelled)setFailed(true);});
    return ()=>{cancelled=true;dispose();};
  },[]);
  return <div className={`protein-scene ${compact?'compact':''}`}>
    <div className="orbital orbital-one" aria-hidden="true"/><div className="orbital orbital-two" aria-hidden="true"/>
    <span className="scene-cross cross-one" aria-hidden="true">+</span><span className="scene-cross cross-two" aria-hidden="true">+</span>
    <div className="scene-top"><span className="eyebrow">A closer look</span><span className="scene-code">6F5J / C</span></div>
    <canvas ref={canvas} aria-label="Interactive C-alpha structure of 6F5J chain C. Drag to rotate. Orange highlights the recorded top structural proposal." />
    {!ready && !failed && <div className="scene-loading"><span className="loading-orbit"/>Preparing the structure</div>}
    {failed && <div className="scene-fallback"><strong>6F5J</strong><p>393 observed C-alpha positions · chain C</p><p>3D rendering is unavailable in this browser.</p><a href="/method/">Explore the method ↗</a></div>}
    <div className="scene-annotation"><span className="annotation-dot"/><div><span>{mode==='patch'?'A place to investigate':mode==='trace'?'The observed backbone':'Residue-level detail'}</span><small>{mode==='patch'?'6 residues · structural proposal':mode==='trace'?'C-alpha trace · gaps preserved':'393 observed C-alpha positions'}</small></div></div>
    <div className="scene-toolbar"><div className="scene-modes" aria-label="Structure representation">{[['trace','Trace'],['residues','Residues'],['patch','Patch']].map(([value,label])=><button key={value} aria-pressed={mode===value} onClick={()=>{setMode(value);controller.current?.mode(value);}}>{label}</button>)}</div><div className="scene-actions"><button title="Reset view" aria-label="Reset structure view" onClick={()=>controller.current?.reset()}>↺</button><button title={paused?'Resume rotation':'Pause rotation'} aria-label={paused?'Resume rotation':'Pause rotation'} aria-pressed={paused} onClick={()=>{setPaused(!paused);controller.current?.pause(!paused);}}>{paused?'▷':'Ⅱ'}</button></div></div>
    <div className="scene-caption"><span>EXAMPLE STRUCTURE · NOT A LIVE RUN</span><span>Drag to explore <span aria-hidden="true">↔</span></span></div>
  </div>;
}
