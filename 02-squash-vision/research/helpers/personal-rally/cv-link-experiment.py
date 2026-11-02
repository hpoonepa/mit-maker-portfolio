"""Select short supported trajectories from independent measured CV candidates."""
from pathlib import Path
import json, math
from collections import defaultdict,Counter
import numpy as np
import cv2

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'cv-experiment'
data=json.loads((OUT/'candidates.json').read_text())
nodes=[];byframe=defaultdict(list)
for row in data['items']:
    for c in row['candidates']:
        n={**c,'sourceFrameIndex':row['sourceFrameIndex'],'timestampUs':row['timestampUs'],'id':len(nodes)}
        nodes.append(n);byframe[n['sourceFrameIndex']].append(n['id'])

edges={};ending=defaultdict(list)
for b in nodes:
    f=b['sourceFrameIndex'];bp=np.array([b['x'],b['y']])
    for df in (1,2):
        for aid in byframe[f-df]:
            a=nodes[aid];ap=np.array([a['x'],a['y']]);velocity=(bp-ap)/df
            speed=float(np.linalg.norm(velocity))
            if not 1.5<=speed<=140:continue
            best=(2.,None)
            for edge in ending[aid]:
                state=edges[edge]
                error=float(np.linalg.norm(velocity-state['velocity']))
                if error>max(10,.30*speed):continue
                score=state['score']+1-error/max(10,.30*speed)*.4
                if score>best[0]:best=(score,edge)
            key=(aid,b['id']);edges[key]={'score':best[0],'previous':best[1],'velocity':velocity}
            ending[b['id']].append(key)

paths=[];used=set()
for key,state in sorted(edges.items(),key=lambda p:-p[1]['score']):
    if state['score']<4.2:continue
    ids=[key[1],key[0]];previous=state['previous']
    while previous is not None:
        ids.append(previous[0]);previous=edges[previous]['previous']
    ids=list(reversed(ids))
    if len(ids)<5:continue
    first,last=nodes[ids[0]],nodes[ids[-1]]
    span=last['sourceFrameIndex']-first['sourceFrameIndex']
    displacement=math.hypot(last['x']-first['x'],last['y']-first['y'])
    if displacement<30 or displacement/span<3:continue
    fresh=set(ids)-used
    if len(fresh)<3:continue
    used.update(ids)
    paths.append({'id':len(paths),'nodes':ids,'score':state['score'],'displacement':displacement})

support=defaultdict(list)
for path in paths:
    for nodeid in path['nodes']:support[nodeid].append(path['id'])
rows=[]
for row in data['items']:
    candidates=[nodes[n] for n in byframe[row['sourceFrameIndex']] if n in support]
    rows.append({'sourceFrameIndex':row['sourceFrameIndex'],'timestampUs':row['timestampUs'],
        'ambiguous':len(candidates)>1,'selected':candidates[0] if len(candidates)==1 else None,
        'supportedCandidates':candidates})
result={'method':'five-or-more observed dark blobs linked by bounded velocity change; no interpolated centers',
        'limitations':['Contrast and temporal-linking experiment; ball identities require frame review.',
                       'Player/racket/glass masked pixels and multi-path frames are unavailable.',
                       'Impacts may split trajectories and remain unavailable.'],
        'paths':paths,'items':rows}
(OUT/'trajectories.json').write_text(json.dumps(result,indent=2)+'\n')
print('paths',len(paths),'selected',sum(r['selected'] is not None for r in rows),'ambiguous',sum(r['ambiguous'] for r in rows))
selected={r['sourceFrameIndex']:r['selected'] for r in rows if r['selected'] is not None}
print('selectedpersecond',dict(sorted(Counter(f//30 for f in selected).items())))

# Show measured positions at12 evenly spaced selected frames, including blanks.
available=sorted(selected)
times=[available[index] for index in np.linspace(0,len(available)-1,12).astype(int)] if available else []
by={r['sourceFrameIndex']:r for r in rows};tiles=[]
cap=cv2.VideoCapture(str(ROOT/'practice-rallies-176-241.mp4'));i=0
while True:
    ok,image=cap.read()
    if not ok or i>=660:break
    if i in times:
        r=by[i];point=r['selected']
        if point:cv2.circle(image,(round(point['x']),round(point['y'])),8,(0,220,255),2)
        tile=np.zeros((395,640,3),np.uint8);tile[35:]=cv2.resize(image,(640,360))
        status='observed candidate' if point else ('ambiguous' if r['ambiguous'] else 'unavailable')
        cv2.putText(tile,f'{i*1001/30000:.3f}s {status}',(8,25),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,255,255),1)
        tiles.append(tile)
    i+=1
cap.release()
cv2.imwrite(str(OUT/'trajectory-sheet.jpg'),np.vstack([np.hstack(tiles[i:i+3]) for i in range(0,len(tiles),3)]))
