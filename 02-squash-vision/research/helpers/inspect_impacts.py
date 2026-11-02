import json, math
from pathlib import Path
import cv2
import numpy as np
import pyarrow.parquet as pq

root = Path(__file__).resolve().parents[1]
artifact = root / 'runtime/demo-data/storage/checkpoints/3ff4ad84-c699-4fa2-8112-6af1f79acaea'
balls = pq.read_table(artifact / 'ball/0-25000000.payload.parquet').to_pylist()
players = pq.read_table(artifact / 'players/0-25000000.payload.parquet').to_pylist()
def valid(row):
    return row['visible'] and row['x'] is not None and row['evidence']=='observed' and not row['ambiguous'] and row['probability'] >= .5
candidates=[]
for i in range(2,len(balls)-2):
    window=balls[i-2:i+3]
    if not all(valid(row) for row in window): continue
    if any(b['source_frame_index']!=a['source_frame_index']+1 for a,b in zip(window,window[1:])): continue
    a,b,c=window[0],window[2],window[4]
    dt1=(b['timestamp_us']-a['timestamp_us'])/1e6
    dt2=(c['timestamp_us']-b['timestamp_us'])/1e6
    vin=np.array([b['x']-a['x'],b['y']-a['y']])/dt1
    vout=np.array([c['x']-b['x'],c['y']-b['y']])/dt2
    delta=np.linalg.norm(vout-vin)
    ratio=delta/max(np.linalg.norm(vin),np.linalg.norm(vout),1)
    if delta < 150 or ratio < .35: continue
    t=b['timestamp_us']
    wrists=[]
    for p in players:
        if abs(p['timestamp_us']-t)>40000: continue
        for k in [9,10]:
            if p['keypoints_confidence'][k] < .3: continue
            distance=math.hypot(p['keypoints_x'][k]-b['x'],p['keypoints_y'][k]-b['y'])
            wrists.append((distance,p['player_id']))
    candidates.append({'i':i,'t':t/1e6,'x':b['x'],'y':b['y'],'delta':float(delta),'ratio':float(ratio),'vin':vin.tolist(),'vout':vout.tolist(),'wrist':min(wrists,default=None)})
peaks=[]
for c in sorted(candidates,key=lambda c:-c['delta']):
    if not any(abs(c['t']-p['t']) < .24 for p in peaks): peaks.append(c)
peaks.sort(key=lambda c:c['t'])
print(json.dumps(peaks,indent=1))
(root/'runtime/evidence/impact-candidates.json').write_text(json.dumps(peaks,indent=2))
cap=cv2.VideoCapture(str(root/'runtime/elshorbagy-farag-25s.mp4'))
tiles=[]
for p in peaks:
    row=balls[p['i']]
    cap.set(cv2.CAP_PROP_POS_FRAMES,row['source_frame_index'])
    ok,frame=cap.read()
    if not ok: continue
    for j,color in [(-2,(220,120,100)),(0,(70,240,255)),(2,(120,120,255))]:
        r=balls[p['i']+j]
        cv2.circle(frame,(round(r['x']),round(r['y'])),7,color,2)
    tile=cv2.resize(frame,(512,288))
    cv2.rectangle(tile,(0,0),(512,30),(20,20,20),-1)
    cv2.putText(tile,f"{p['t']:.2f}s  delta {p['delta']:.0f}  wrist {p['wrist']}",(8,20),cv2.FONT_HERSHEY_SIMPLEX,.43,(235,235,235),1)
    tiles.append(tile)
cap.release()
while len(tiles)%3: tiles.append(np.zeros_like(tiles[0]))
sheet=np.vstack([np.hstack(tiles[i:i+3]) for i in range(0,len(tiles),3)])
cv2.imwrite(str(root/'runtime/evidence/impact-candidates.jpg'),sheet)
