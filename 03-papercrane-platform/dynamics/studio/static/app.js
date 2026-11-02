// Render saved and fresh SENBA endpoints alongside recorded MD in the Studio viewer.
import * as THREE from 'three';
import { OrbitControls } from './vendor/OrbitControls.js';

const $ = (id) => document.getElementById(id);
const state = { record: null, view: 'candidate', sample: 0, blend: 1, atoms: false, playing: false, ready: false, busy: false, structureId: 'example-0' };
const colors = { candidate: 0xab8bce, source: 0x7bacc9, target: 0xd5aa72, trajectory: 0xab8bce };
let examples = [], renderer, scene, camera, controls, molecule, ghost, center, atomMeshes, lastFrame = 0;

function initializeViewer() {
  const host = $('viewport');
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setSize(host.clientWidth, host.clientHeight);
  renderer.domElement.setAttribute('aria-hidden', 'true');
  host.prepend(renderer.domElement);
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(35, host.clientWidth / host.clientHeight, 0.1, 2000);
  scene.add(new THREE.AmbientLight(0xffffff, 1.6));
  const key = new THREE.DirectionalLight(0xffffff, 3.3); key.position.set(-10, 30, 40); scene.add(key);
  const fill = new THREE.DirectionalLight(0xdfd4f0, 1.4); fill.position.set(20, -10, -10); scene.add(fill);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.dampingFactor = 0.08; controls.autoRotateSpeed = 0.7;
  controls.minDistance = 8; controls.maxDistance = 400;
  new ResizeObserver(() => { renderer.setSize(host.clientWidth, host.clientHeight); camera.aspect = host.clientWidth / host.clientHeight; camera.updateProjectionMatrix(); charts(); }).observe(host);
  requestAnimationFrame(animate);
}

function frames() {
  const r = state.record;
  if (!r) return [];
  if (state.view === 'target') return r.target ? [r.target] : [];
  return r[state.view] || [];
}
function endpoint() { return frames()[state.sample] || state.record.start; }
function atomData() {
  if (state.view === 'trajectory') return state.sample === 0 ? state.record.start_atoms : null;
  if (state.blend === 0 || !frames().length) return state.record.start_atoms;
  if (state.view === 'candidate') return state.record.candidate_atoms?.[state.sample];
  return null;
}
function clearObject(object) {
  if (!object) return;
  scene.remove(object);
  const geometries = new Set(), materials = new Set();
  object.traverse(child => { if (child.geometry) geometries.add(child.geometry); if (child.material) materials.add(child.material); });
  geometries.forEach(g => g.dispose()); materials.forEach(m => m.dispose());
}
function trace(coords, radius, color, opacity = 1) {
  const points = coords.map(p => new THREE.Vector3(...p).sub(center));
  const curve = new THREE.CatmullRomCurve3(points);
  const geometry = new THREE.TubeGeometry(curve, Math.max(120, points.length * 5), radius, 8, false);
  const material = new THREE.MeshStandardMaterial({ color, roughness: 0.4, metalness: 0.06, transparent: opacity < 1, opacity, depthWrite: opacity === 1 });
  return new THREE.Mesh(geometry, material);
}
function drawAtoms(data) {
  const group = new THREE.Group();
  const positions = data.coordinates.map((p, i) => {
    const start = state.record.start_atoms.coordinates[i];
    return new THREE.Vector3(...p.map((v, k) => start[k] + (v - start[k]) * state.blend)).sub(center);
  });
  const palette = { C: 0x9b85b5, N: 0x688fc0, O: 0xd68177, S: 0xd1b86a };
  const mesh = new THREE.InstancedMesh(new THREE.SphereGeometry(0.36, 12, 8), new THREE.MeshStandardMaterial({ roughness: 0.45 }), positions.length);
  const dummy = new THREE.Object3D();
  positions.forEach((p, i) => { dummy.position.copy(p); dummy.updateMatrix(); mesh.setMatrixAt(i, dummy.matrix); mesh.setColorAt(i, new THREE.Color(palette[data.elements[i]] || palette.C)); });
  group.add(mesh);
  // Inferred display bonds, by distance. They are not chemical bond-order annotations.
  const links = [];
  for (let i = 0; i < positions.length; i++) for (let j = i + 1; j < positions.length; j++) {
    const d = positions[i].distanceTo(positions[j]);
    if (d > 0.7 && d < (data.elements[i] === 'S' || data.elements[j] === 'S' ? 2.1 : 1.9)) links.push([i, j, d]);
  }
  const sticks = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.11, 0.11, 1, 6), new THREE.MeshStandardMaterial({ color: 0xa4a299, roughness: 0.55 }), links.length);
  const up = new THREE.Vector3(0, 1, 0);
  links.forEach(([i, j, length], k) => { dummy.position.copy(positions[i]).add(positions[j]).multiplyScalar(0.5); dummy.quaternion.setFromUnitVectors(up, positions[j].clone().sub(positions[i]).normalize()); dummy.scale.set(1, length, 1); dummy.updateMatrix(); sticks.setMatrixAt(k, dummy.matrix); });
  group.add(sticks);
  return group;
}
function renderStructure() {
  if (!state.record || !scene) return;
  clearObject(molecule);
  const target = endpoint();
  const coords = state.view === 'trajectory' ? target : state.record.start.map((p, i) => p.map((v, k) => v + (target[i][k] - v) * state.blend));
  const data = atomData();
  $('atoms').disabled = !data;
  $('atoms').title = data ? 'Heavy atoms; bonds inferred from distance' : 'Atom coordinates are available for the input and fresh Senba runs';
  if (state.atoms && !data) state.atoms = false;
  molecule = state.atoms && data ? drawAtoms(data) : trace(coords, 0.38, colors[state.view]);
  scene.add(molecule);
  $('atoms').classList.toggle('selected', state.atoms); $('backbone').classList.toggle('selected', !state.atoms);
  if (ghost) ghost.visible = $('ghost').checked;
}
function resetCamera() {
  if (!state.record || !camera) return;
  const points = [...state.record.start, ...endpoint()].map(p => new THREE.Vector3(...p).sub(center));
  const bounds = new THREE.Box3().setFromPoints(points);
  const sphere = bounds.getBoundingSphere(new THREE.Sphere());
  const distance = Math.max(35, sphere.radius * 3.7 / Math.min(camera.aspect, 1.35));
  controls.target.copy(sphere.center);
  camera.position.copy(sphere.center).add(new THREE.Vector3(0.7, 0.25, 1).normalize().multiplyScalar(distance));
  controls.update();
}
function animate(t) {
  requestAnimationFrame(animate);
  if (state.playing && state.record && t - lastFrame > 35) {
    if (state.view === 'trajectory') {
      if (t - lastFrame > 125) { state.sample = (state.sample + 1) % frames().length; updateViews(); lastFrame = t; }
    } else {
      state.blend = (1 - Math.cos(t / 2100)) / 2;
      $('morph').value = Math.round(state.blend * 100); $('morph-value').textContent = `${Math.round(state.blend * 100)}%`;
      renderStructure(); lastFrame = t;
    }
  }
  controls.autoRotate = $('rotate').checked;
  controls.update(); renderer.render(scene, camera);
}
function loadRecord(record, structureId, keepCamera = false) {
  if (record.kind === 'fresh_inference' && structureId.startsWith('example-')) {
    const original = examples.find(r => r.id === structureId);
    if (original) { record.trajectory = original.trajectory; record.trajectory_receipt = original.trajectory_receipt; record.target = original.target; record.transition = original.transition; }
  }
  state.record = record; state.structureId = structureId; state.sample = 0; state.view = 'candidate'; state.blend = (record.candidate?.length ? 1 : 0); state.playing = false; state.atoms = false;
  $('play').textContent = '▶'; $('play').setAttribute('aria-label', 'Play illustrative morph');
  center = new THREE.Vector3(); record.start.forEach(p => center.add(new THREE.Vector3(...p))); center.divideScalar(record.start.length);
  clearObject(ghost); ghost = trace(record.start, 0.12, 0xa4b78f, 0.32); scene.add(ghost);
  $('protein-label').textContent = record.label;
  $('protein-subtitle').textContent = `${record.label === '1rquA01' ? 'Ribosomal L7/L12 domain · ' : ''}${record.start.length} residues`;
  $('residue-end').textContent = `Residue ${record.start.length}`;
  const fresh = record.kind === 'fresh_inference';
  $('data-badge').classList.toggle('live', fresh);
  $('data-badge').replaceChildren(Object.assign(document.createElement('i'), {}), document.createTextNode(fresh ? 'FRESH CHECKPOINT OUTPUT' : record.candidate?.length ? 'SAVED MODEL OUTPUT' : 'INPUT STRUCTURE'));
  $('morph').value = state.blend * 100; $('morph-value').textContent = `${state.blend * 100}%`;
  updateViews();
  if (!keepCamera) resetCamera();
}
function updateViews() {
  document.querySelectorAll('[data-view]').forEach(button => {
    button.classList.toggle('selected', state.view === button.dataset.view);
    button.disabled = button.dataset.view === 'source' ? !state.record.source?.length : button.dataset.view === 'target' ? !state.record.target : button.dataset.view === 'trajectory' ? !state.record.trajectory : false;
  });
  const total = frames().length;
  state.sample = Math.min(state.sample, Math.max(total - 1, 0));
  $('sample').max = Math.max(total - 1, 0); $('sample').value = state.sample; $('sample').disabled = total < 2;
  const md = state.view === 'trajectory';
  $('sample-count').textContent = total ? md ? `${state.sample} / ${total - 1}` : `${state.sample + 1} / ${total}` : 'Input only';
  document.querySelector('label[for="sample"]').textContent = md ? 'Recorded simulation frame' : 'Independent sample';
  $('morph').disabled = !total; $('play').disabled = !total;
  $('legend-label').textContent = { candidate: 'Senba endpoint', source: 'MarS-FM endpoint', target: 'MD endpoint', trajectory: 'Recorded MD frame' }[state.view];
  document.querySelector('.legend-dot.purple').style.background = `#${colors[state.view].toString(16)}`;
  $('timeline-end').textContent = md ? '50 saved frames later' : state.view === 'target' ? 'Observed MD endpoint' : 'Predicted endpoint';
  $('morph').max = md ? total - 1 : 100;
  $('morph').value = md ? state.sample : Math.round(state.blend * 100);
  $('morph-value').textContent = md ? String(state.sample).padStart(2, '0') : `${Math.round(state.blend * 100)}%`;
  $('morph').setAttribute('aria-label', md ? 'Recorded molecular dynamics frame' : 'Illustrative interpolation from input to endpoint');
  $('motion-note').textContent = md ? 'Recorded MD · 450 K · playback speed ≠ physical time' : 'Visual interpolation · not a simulated path';
  $('data-badge').lastChild.textContent = md || state.view === 'target' ? 'RECORDED MOLECULAR DYNAMICS' : state.record.kind === 'fresh_inference' ? 'FRESH CHECKPOINT OUTPUT' : state.record.candidate?.length ? 'SAVED MODEL OUTPUT' : 'INPUT STRUCTURE';
  $('data-badge').classList.toggle('live', !md && state.view !== 'target' && state.record.kind === 'fresh_inference');
  document.querySelector('.metric-note').textContent = md ? 'MD frame aligned to input.' : 'Endpoint coordinates aligned to input.';
  renderStructure(); charts();
}
function chartContext(id, height) {
  const canvas = $(id), width = canvas.clientWidth, dpr = window.devicePixelRatio || 1;
  canvas.width = width * dpr; canvas.height = height * dpr;
  const ctx = canvas.getContext('2d'); ctx.scale(dpr, dpr);
  return { ctx, width, height };
}
function charts() {
  if (!state.record) return;
  const coords = endpoint(), start = state.record.start;
  const values = coords.map((p, i) => Math.hypot(...p.map((v, k) => v - start[i][k])));
  const rmsd = Math.sqrt(values.reduce((a, b) => a + b * b, 0) / values.length);
  const mean = [0, 1, 2].map(k => coords.reduce((a, p) => a + p[k], 0) / coords.length);
  const rg = Math.sqrt(coords.reduce((a, p) => a + p.reduce((s, v, k) => s + (v - mean[k]) ** 2, 0), 0) / coords.length);
  $('rmsd').textContent = rmsd.toFixed(2); $('rg').textContent = rg.toFixed(2);
  const { ctx, width, height } = chartContext('displacement', 75);
  const max = Math.max(1, ...values) * 1.1, top = 8, bottom = height - 4;
  ctx.strokeStyle = '#30422a'; ctx.lineWidth = 0.6;
  for (let y = 10; y < height; y += 22) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke(); }
  ctx.beginPath(); ctx.moveTo(0, bottom);
  values.forEach((v, i) => ctx.lineTo(i * width / (values.length - 1), bottom - v / max * (bottom - top)));
  ctx.lineTo(width, bottom); ctx.closePath(); ctx.fillStyle = '#ad8dcc28'; ctx.fill();
  ctx.beginPath(); values.forEach((v, i) => { const x = i * width / (values.length - 1), y = bottom - v / max * (bottom - top); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }); ctx.strokeStyle = '#b99ad5'; ctx.lineWidth = 1.5; ctx.stroke();
  ctx.fillStyle = '#a0b389'; ctx.font = '8px monospace'; ctx.fillText(`${max.toFixed(1)} Å`, 2, 8);
  const map = $('contacts'), n = coords.length, c = map.getContext('2d'); map.width = map.height = n;
  c.fillStyle = '#1d2d1a'; c.fillRect(0, 0, n, n); c.fillStyle = '#b89bd0';
  coords.forEach((p, i) => coords.forEach((q, j) => { if (Math.abs(i - j) > 2 && p.reduce((a, v, k) => a + (v - q[k]) ** 2, 0) < 64) c.fillRect(i, j, 1, 1); }));
}
function message(text, error = false) { $('run-message').textContent = text; $('run-message').classList.toggle('error', error); }
async function api(path, body) {
  const response = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `Request failed (${response.status})`);
  return result;
}
function busy(value) {
  state.busy = value;
  for (const id of ['run', 'load-pdb', 'pdb-file', 'example', 'samples', 'seed', 'pdb-id', 'chain']) $(id).disabled = value || (!state.ready && ['run', 'load-pdb', 'pdb-file'].includes(id));
  $('run').firstElementChild.textContent = value ? 'Running Senba…' : 'Run Senba';
}
async function runModel() {
  busy(true); const start = performance.now();
  try {
    const job = await api('/api/run', { structure_id: state.structureId, samples: Number($('samples').value), seed: Number($('seed').value) });
    while (true) {
      const result = await api(`/api/jobs/${job.id}`);
      if (result.status === 'error') throw new Error(result.stage);
      if (result.status === 'complete') {
        loadRecord(result.result, state.structureId, true);
        message(`Fresh run complete · ${result.result.receipt.inference_seconds.toFixed(2)} s · ${result.result.receipt.samples} samples`);
        break;
      }
      message(`${result.stage} · ${((performance.now() - start) / 1000).toFixed(1)} s${result.evaluations ? ` · ${result.evaluations} network evaluations` : ''}`);
      await new Promise(resolve => setTimeout(resolve, 450));
    }
  } catch (error) { message(error.message, true); }
  finally { busy(false); }
}
async function loadPdb(pdbText) {
  busy(true); message('Reading and validating the protein structure…');
  try {
    const payload = { chain: $('chain').value.trim() };
    if (typeof pdbText === 'string') payload.pdb_text = pdbText;
    else { payload.pdb_id = $('pdb-id').value.trim(); if (!payload.pdb_id) throw new Error('Enter a PDB ID or upload a PDB file.'); }
    const r = await api('/api/structure', payload); loadRecord(r, r.id);
    $('example').selectedIndex = -1; message(`${r.label} loaded.`);
  } catch (error) { message(error.message, true); }
  finally { busy(false); }
}
function download(blob, name) { const link = document.createElement('a'); const url = URL.createObjectURL(blob); link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }

$('run').addEventListener('click', runModel);
$('load-pdb').addEventListener('click', () => loadPdb());
$('pdb-id').addEventListener('keydown', e => { if (e.key === 'Enter' && !state.busy && state.ready) loadPdb(); });
$('pdb-file').addEventListener('change', async e => { const file = e.target.files[0]; if (!file) return; if (file.size > 2_000_000) return message('Choose a PDB file under 2 MB.', true); await loadPdb(await file.text()); e.target.value = ''; });
$('example').addEventListener('change', () => { const r = examples[Number($('example').value)]; loadRecord(r, r.id); message('Saved predictions loaded.'); });
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => { state.view = button.dataset.view; state.sample = 0; updateViews(); }));
$('sample').addEventListener('input', () => { state.sample = Number($('sample').value); updateViews(); });
$('morph').addEventListener('input', () => { state.playing = false; $('play').textContent = '▶'; $('play').setAttribute('aria-label', 'Play motion'); if (state.view === 'trajectory') { state.sample = Number($('morph').value); updateViews(); } else { state.blend = Number($('morph').value) / 100; $('morph-value').textContent = `${$('morph').value}%`; renderStructure(); } });
$('play').addEventListener('click', () => { state.playing = !state.playing; $('play').textContent = state.playing ? 'Ⅱ' : '▶'; $('play').setAttribute('aria-label', state.playing ? 'Pause motion' : 'Play motion'); });
$('backbone').addEventListener('click', () => { state.atoms = false; renderStructure(); });
$('atoms').addEventListener('click', () => { state.atoms = true; renderStructure(); });
$('ghost').addEventListener('change', renderStructure);
$('reset-camera').addEventListener('click', resetCamera);
$('present').addEventListener('click', () => { document.body.classList.toggle('presentation'); $('present').textContent = document.body.classList.contains('presentation') ? 'Exit presentation ↙' : 'Present ↗'; });
$('download').addEventListener('click', () => download(new Blob([JSON.stringify(state.record, null, 2)], { type: 'application/json' }), `senba-${state.record.kind || 'input'}-${Date.now()}.json`));
$('snapshot').addEventListener('click', () => {
  renderer.render(scene, camera);
  const canvas = document.createElement('canvas'); canvas.width = 1600; canvas.height = 1200;
  const ctx = canvas.getContext('2d'); ctx.fillStyle = '#101812'; ctx.fillRect(0, 0, 1600, 1200);
  const aspect = renderer.domElement.width / renderer.domElement.height;
  const h = Math.min(950, 1500 / aspect), w = h * aspect;
  ctx.drawImage(renderer.domElement, (1600 - w) / 2, 100, w, h);
  ctx.fillStyle = '#c4d6b5'; ctx.font = '32px sans-serif'; ctx.fillText(`Papercrane / Senba · ${state.record.label}`, 60, 65);
  ctx.font = '20px sans-serif'; ctx.fillText(`${state.record.kind || 'Input'} · ${$('legend-label').textContent} · sample ${state.sample + 1}`, 60, 1110);
  ctx.fillText(state.view === 'trajectory' ? `Recorded MD frame ${state.sample} · 450 K · aligned to input` : `Illustrative morph ${Math.round(state.blend * 100)}% · not a physical trajectory`, 60, 1145);
  canvas.toBlob(blob => download(blob, 'senba-structure.png'));
});

try {
  initializeViewer();
  const data = await (await fetch('/data/examples.json')).json(); examples = data.records;
  $('example').replaceChildren(...examples.map((r, i) => { const o = document.createElement('option'); o.value = i; o.textContent = `L7/L12 domain · start frame ${r.transition.start_frame}`; return o; }));
  loadRecord(examples[0], examples[0].id);
  state.view = 'trajectory'; updateViews();
  if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) { state.playing = true; $('play').textContent = 'Ⅱ'; $('play').setAttribute('aria-label', 'Pause motion'); }
} catch (error) { $('viewport-error').hidden = false; $('viewport-error').textContent = `The 3D viewer could not start: ${error.message}. Check that WebGL is enabled and reload.`; }
async function checkHealth() {
  try {
    const health = await api('/api/health'); state.ready = health.status === 'ready';
    $('local-status').textContent = state.ready ? '● LOCAL CPU READY' : health.status === 'error' ? 'ENGINE UNAVAILABLE' : 'LOADING ENGINE';
    $('local-status').classList.toggle('ready', state.ready); busy(state.busy);
    if (state.ready) { message('Senba ready.'); return; }
    message(health.message, health.status === 'error');
    if (health.status === 'error') return;
  } catch { $('local-status').textContent = 'SAVED DEMO'; message('Saved predictions are available. Start the Python server to run fresh inference.'); }
  setTimeout(checkHealth, 1500);
}
checkHealth();

// V3 portfolio export: original coordinates, native geometry/materials, fixed camera.
$('export-clean-clip').addEventListener('click', async () => {
  const button = $('export-clean-clip');
  if (!state.record || !renderer || button.disabled) return;
  const md = state.view === 'trajectory';
  if (!md && state.view !== 'candidate') { button.textContent='Select Senba or MD movie first'; return; }
  const previous={sample:state.sample,blend:state.blend,playing:state.playing};
  const previousCamera=camera.position.clone(), previousTarget=controls.target.clone(), previousAspect=camera.aspect;
  const previousSize=renderer.getSize(new THREE.Vector2()), previousPixelRatio=renderer.getPixelRatio();
  const previousGhost=$('ghost').checked, previousOrbit=$('rotate').checked;
  state.playing=false; $('ghost').checked=true; $('rotate').checked=false;
  controls.autoRotate=false; button.disabled=true;
  await document.fonts.ready; renderer.setPixelRatio(1); renderer.setSize(1920,820,false); camera.aspect=1920/820; camera.updateProjectionMatrix();
  const allCoordinates=[...state.record.start,...(state.record.trajectory||[]).slice(0,24).flat(),...state.record.candidate[8]];
  const points=allCoordinates.map(p=>new THREE.Vector3(...p).sub(center));
  const bounds=new THREE.Box3().setFromPoints(points), sphere=bounds.getBoundingSphere(new THREE.Sphere());
  const direction=new THREE.Vector3(0.7,0.25,1).normalize();
  controls.target.copy(sphere.center); camera.position.copy(sphere.center).addScaledVector(direction,100); camera.lookAt(sphere.center); camera.updateMatrixWorld();
  const inverse=camera.matrixWorldInverse;
  let required=0; const tangent=Math.tan(THREE.MathUtils.degToRad(camera.fov/2));
  for(const p of points){const q=p.clone().sub(sphere.center); const depth=q.dot(direction); const right=new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld,0); const up=new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld,1); required=Math.max(required,depth+Math.abs(q.dot(up))/tangent,depth+Math.abs(q.dot(right))/(tangent*camera.aspect));}
  const distance=required*1.07;
  camera.position.copy(sphere.center).addScaledVector(direction,distance); controls.update();
  const canvas=document.createElement('canvas'); canvas.width=1920; canvas.height=1080; const context=canvas.getContext('2d');
  const count=md?90:240, files=[];
  try {
    for(let i=0;i<count;i++){
      if(md)state.sample=Math.min(frames().length-1,Math.floor(i/30*8));
      else {state.sample=8; const u=Math.min(1,Math.max(0,(i/30-1)/6));state.blend=(1-Math.cos(Math.PI*u))/2;}
      renderStructure(); renderer.render(scene,camera);
      context.save();context.translate(960,540);context.scale(1.7777778,1);const bg=context.createRadialGradient(0,0,0,0,0,650);bg.addColorStop(0,'#1d291f');bg.addColorStop(.68,'#151f18');bg.addColorStop(1,'#0e1610');context.fillStyle=bg;context.fillRect(-960,-540,1920,1080);context.restore();
      context.drawImage(renderer.domElement,0,220,1920,820); drawNativeWidgetChrome(context);
      const encoded=atob(canvas.toDataURL('image/png').split(',')[1]);const bytes=new Uint8Array(encoded.length);for(let j=0;j<encoded.length;j++)bytes[j]=encoded.charCodeAt(j);
      files.push({name:`frame-${String(i).padStart(4,'0')}.png`,data:bytes});
      
      button.textContent=`Exporting V3 native frames ${i+1}/${count}`;
    }
    files.push({name:'capture.json',data:new TextEncoder().encode(JSON.stringify({mode:md?'recorded_mdcath_trajectory':'illustrative_input_to_senba_endpoint_morph',source_record:state.record.id,endpoint_sample:8,frames:count,fps:30,width:1920,height:1080,ui_included:'native widget tabs, title and legend redrawn from live DOM state',ghost:true,orbit:false,camera_direction:direction.toArray(),camera_target:sphere.center.toArray(),camera_distance:distance,coordinates_unchanged:true,geometry:'Native Studio trace radius 0.38, ghost radius 0.12 opacity0.32',note:md?'First24 recorded MD frames at native Studio8fps;3seconds of display playback, not physical time.':'Saved SENBA endpoint sample8 (ninth of16): hold input1s, visual interpolation6s, hold endpoint1s. Not a simulated trajectory.'},null,2))});
    download(storedZip(files),md?'senba-v3-tight-recorded-md-frames.zip':'senba-v3-tight-model-morph-frames.zip');button.textContent='V3 native frames downloaded ✓';
  }catch(error){button.textContent=`Export failed: ${error.message}`;}
  finally{Object.assign(state,previous);$('ghost').checked=previousGhost;$('rotate').checked=previousOrbit;renderer.setPixelRatio(previousPixelRatio);renderer.setSize(previousSize.x,previousSize.y,false);camera.aspect=previousAspect;camera.updateProjectionMatrix();camera.position.copy(previousCamera);controls.target.copy(previousTarget);controls.update();updateViews();button.disabled=false;}
});

function drawNativeWidgetChrome(ctx) {
  // Canvas export of the actual widget labels and selected tab state, using Studio CSS.
  const round=(x,y,w,h,r,fill,stroke)=>{ctx.beginPath();ctx.roundRect(x,y,w,h,r);if(fill){ctx.fillStyle=fill;ctx.fill();}if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=2;ctx.stroke();}};
  round(1,1,1918,1078,26,null,'#2c392d');
  const buttons=[...document.querySelectorAll('.viewer-toolbar [data-view]')];
  let total=12; const widths=buttons.map(b=>{const cs=getComputedStyle(b);ctx.font=`${cs.fontWeight} 22px ${cs.fontFamily}`;const w=ctx.measureText(b.textContent).width+48;total+=w+4;return w;});
  round(40,36,total,78,14,'#17211ae8','#32412f');
  let x=48; buttons.forEach((b,i)=>{const cs=getComputedStyle(b);if(b.classList.contains('selected'))round(x,44,widths[i],62,8,'#c0d0b5');ctx.font=`${cs.fontWeight} 22px ${cs.fontFamily}`;ctx.textBaseline='middle';ctx.fillStyle=cs.color;ctx.fillText(b.textContent,x+24,75);x+=widths[i]+4;});
  round(1816,44,64,64,12,'#1b261cdd','#344331');ctx.fillStyle='#adc09e';ctx.font='44px sans-serif';ctx.textAlign='center';ctx.fillText('⌖',1848,76);ctx.textAlign='left';
  const title=$('protein-label'), sub=$('protein-subtitle');
  ctx.font=`400 24px ${getComputedStyle(title).fontFamily}`;ctx.fillStyle=getComputedStyle(title).color;ctx.fillText(title.textContent,48,178);
  ctx.font=`400 22px ${getComputedStyle(sub).fontFamily}`;ctx.fillStyle=getComputedStyle(sub).color;ctx.fillText(sub.textContent,48,220);
  const label=$('legend-label'), cs=getComputedStyle(label);ctx.font=`400 20px ${cs.fontFamily}`;const labels=[label.textContent,'Input reference'];const widths2=labels.map(t=>ctx.measureText(t).width);const left=1874-Math.max(...widths2);
  labels.forEach((t,i)=>{ctx.fillStyle=i?'#738168':`#${colors[state.view].toString(16)}`;ctx.beginPath();ctx.arc(left-20,180+i*42,6,0,Math.PI*2);ctx.fill();ctx.fillStyle=cs.color;ctx.fillText(t,left,180+i*42);});
}

function storedZip(files) {
  const table=new Uint32Array(256);
  for(let i=0;i<256;i++){let c=i;for(let j=0;j<8;j++)c=(c&1)?0xedb88320^(c>>>1):c>>>1;table[i]=c>>>0;}
  const crc=data=>{let c=0xffffffff;for(const v of data)c=table[(c^v)&255]^(c>>>8);return(c^0xffffffff)>>>0;};
  const local=[],central=[];let offset=0,centralSize=0;
  for(const file of files){
    const name=new TextEncoder().encode(file.name), sum=crc(file.data), size=file.data.length;
    const h=new Uint8Array(30+name.length),d=new DataView(h.buffer);
    d.setUint32(0,0x04034b50,true);d.setUint16(4,20,true);d.setUint32(14,sum,true);d.setUint32(18,size,true);d.setUint32(22,size,true);d.setUint16(26,name.length,true);h.set(name,30);
    const ch=new Uint8Array(46+name.length),cd=new DataView(ch.buffer);
    cd.setUint32(0,0x02014b50,true);cd.setUint16(4,20,true);cd.setUint16(6,20,true);cd.setUint32(16,sum,true);cd.setUint32(20,size,true);cd.setUint32(24,size,true);cd.setUint16(28,name.length,true);cd.setUint32(42,offset,true);ch.set(name,46);
    local.push(h,file.data);central.push(ch);offset+=h.length+size;centralSize+=ch.length;
  }
  const end=new Uint8Array(22),ed=new DataView(end.buffer);
  ed.setUint32(0,0x06054b50,true);ed.setUint16(8,files.length,true);ed.setUint16(10,files.length,true);ed.setUint32(12,centralSize,true);ed.setUint32(16,offset,true);
  return new Blob([...local,...central,end],{type:'application/zip'});
}
