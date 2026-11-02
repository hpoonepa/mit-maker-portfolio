"""Independent fixed-camera dark-ball experiment. Never modifies saved reports."""
from pathlib import Path
from collections import Counter
import json, math
import cv2
import numpy as np
import pyarrow.parquet as pq

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'cv-experiment'
OUT.mkdir(exist_ok=True)
VIDEO=ROOT/'practice-rallies-176-241.mp4'
CHECKPOINT=ROOT.parent/'demo-data/storage/checkpoints/971f099e-94b6-4387-8d4b-25a697cf20e3/players/0-60000000.payload.parquet'
START,END=90,660
players={}
for row in pq.read_table(CHECKPOINT).to_pylist():
    if row['evidence']=='observed':players.setdefault(row['source_frame_index'],[]).append(row)

def frames():
    cap=cv2.VideoCapture(str(VIDEO))
    index=0
    while index<=END+1:
        ok,image=cap.read()
        if not ok:break
        yield index,image
        index+=1
    cap.release()

samples=[cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) for i,image in frames() if START<=i<=END and i%15==0]
background=np.median(np.stack(samples),axis=0).astype(np.uint8)
cv2.imwrite(str(OUT/'background.jpg'),background)
del samples
edge=cv2.Canny(background,70,140)
glass_mask=np.ones(background.shape,dtype=np.uint8)
lines=cv2.HoughLinesP(edge,1,np.pi/180,100,minLineLength=220,maxLineGap=30)
if lines is not None:
    for line in lines.reshape(-1,4):
        x1,y1,x2,y2=map(int,line)
        if abs(x2-x1)<=10 and abs(y2-y1)>=220:
            slope=(x2-x1)/(y2-y1)
            top=round(x1-y1*slope);bottom=round(x1+(719-y1)*slope)
            cv2.line(glass_mask,(top,0),(bottom,719),0,64)
cv2.imwrite(str(OUT/'static-edge-mask.png'),glass_mask*255)

def candidates(index,image,previous,following):
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    residual=background.astype(np.int16)-gray.astype(np.int16)
    local=cv2.GaussianBlur(gray,(0,0),3).astype(np.int16)-gray.astype(np.int16)
    motion=np.maximum(cv2.absdiff(gray,previous),cv2.absdiff(gray,following))
    mask=((residual>=20)&(local>=10)&(motion>=12)&(gray<170)).astype(np.uint8)
    # Motion-blurred ball pixels can form two lobes within one exposure.
    mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))*glass_mask
    # Player/shadow pixels are unavailable; they are not extrapolated as a ball.
    for row in players.get(index,[]):
        x1,y1,x2,y2=[int(row['box_'+k]) for k in ('x1','y1','x2','y2')]
        cv2.rectangle(mask,(max(0,x1-10),max(0,y1-6)),(min(1279,x2+10),min(719,y2+10)),0,-1)
        cv2.ellipse(mask,(int(row['feet_x']),int(row['feet_y'])+4),
                    (max(8,int((x2-x1)*.65)),10),0,0,360,0,-1)
        cv2.rectangle(mask,(max(0,x1-20),max(0,y2-8)),(min(1279,x2+20),min(719,y2+45)),0,-1)
        xs,ys,cs=(row[k] for k in ('keypoints_x','keypoints_y','keypoints_confidence'))
        for elbow,wrist in ((7,9),(8,10)):
            if cs[wrist]>=.5:
                # Conservative racket reach: contact neighborhoods remain gaps.
                cv2.circle(mask,(int(xs[wrist]),int(ys[wrist])),max(60,min(180,int((y2-y1)*.9))),0,-1)
            if min(cs[elbow],cs[wrist])>=.5:
                a=np.array([xs[wrist],ys[wrist]]);b=a+2*(a-np.array([xs[elbow],ys[elbow]]))
                cv2.line(mask,tuple(a.astype(int)),tuple(b.astype(int)),0,20)
    count,labels,stats,centers=cv2.connectedComponentsWithStats(mask,8)
    result=[]
    for label in range(1,count):
        x,y,w,h,area=map(int,stats[label])
        if not 5<=area<=600 or max(w,h)>50 or min(w,h)>24 or max(w,h)/max(1,min(w,h))>6:continue
        pixels=labels[y:y+h,x:x+w]==label
        weights=np.maximum(1,residual[y:y+h,x:x+w][pixels]).astype(float)
        if weights.mean()<25 or weights.max()<35:continue
        yy,xx=np.nonzero(pixels)
        cx=float(x+np.average(xx,weights=weights));cy=float(y+np.average(yy,weights=weights))
        # Image bounds exclude outside-glass ground; actual court/wall play remains.
        if cy<80 or cy>680:continue
        result.append({'x':cx,'y':cy,'area':area,'width':w,'height':h,
                       'darkResidual':float(weights.mean()),'localContrast':float(local[y:y+h,x:x+w][pixels].mean()),
                       'motion':float(motion[y:y+h,x:x+w][pixels].mean())})
    return result

it=iter(frames());previous_index,previous_image=next(it);current_index,current_image=next(it)
records=[]
for next_index,next_image in it:
    if START<=current_index<END:
        cs=candidates(current_index,current_image,cv2.cvtColor(previous_image,cv2.COLOR_BGR2GRAY),cv2.cvtColor(next_image,cv2.COLOR_BGR2GRAY))
        records.append({'sourceFrameIndex':current_index,'timestampUs':round(current_index*1001/30000*1e6),'candidates':cs})
    previous_image,current_image=current_image,next_image
    current_index=next_index

(OUT/'candidates.json').write_text(json.dumps({'method':'dark residual + local contrast + adjacent-frame motion, player masks; unvalidated candidates','startFrame':START,'endFrame':END,'items':records},indent=2)+'\n')
counts=Counter(len(row['candidates']) for row in records)
print('Frame candidate counts',dict(sorted(counts.items())))
print('total',sum(len(row['candidates']) for row in records),'nonempty',sum(bool(row['candidates']) for row in records),'frames',len(records))

# A contact sheet displays actual measurements before any trajectory selection.
wanted=[120,165,210,255,300,345,390,435,480,525,570,615]
byframe={row['sourceFrameIndex']:row for row in records};tiles=[]
for i,image in frames():
    if i not in wanted:continue
    cs=byframe[i]['candidates']
    for j,c in enumerate(cs):
        pos=(round(c['x']),round(c['y']))
        cv2.circle(image,pos,7,(0,0,255),1)
        cv2.putText(image,str(j), (pos[0]+8,pos[1]),cv2.FONT_HERSHEY_SIMPLEX,.4,(0,0,255),1)
    tile=np.zeros((395,640,3),np.uint8);tile[35:]=cv2.resize(image,(640,360))
    cv2.putText(tile,f'{i*1001/30000:.3f}s f{i}: {len(cs)} candidates',(8,25),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,255,255),1)
    tiles.append(tile)
cv2.imwrite(str(OUT/'raw-candidate-sheet.jpg'),np.vstack([np.hstack(tiles[i:i+3]) for i in range(0,len(tiles),3)]))
