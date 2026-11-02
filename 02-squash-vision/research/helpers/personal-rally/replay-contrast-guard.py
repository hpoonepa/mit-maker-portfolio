from pathlib import Path
from dataclasses import fields,asdict
from collections import Counter
import cv2,json,numpy as np,pyarrow.parquet as pq
from squashvision.observations import BallCandidate,BallObservation,Frame
from squashvision.vision.ball.contrast_support import DarkBallSupport,CONTRAST_SUPPORT_POLICY_VERSION
from squashvision.vision.ball.tracker import uniform_sample_indices
from squashvision.tracking_stats import FloorProjection
from squashvision.playback_impacts import derive_playback_impacts
from squashvision.tracking_timeline import attribute_shot_impacts

ROOT=Path(__file__).resolve().parent
VIDEO=ROOT/'practice-rallies-176-241.mp4'
OUTPUT=ROOT/'cv-experiment'
median_path=OUTPUT/'production-median.png'
if median_path.exists():
    background=cv2.imread(str(median_path))
else:
    indices=set(uniform_sample_indices(900,201))
    background=np.empty((720,1280,3),np.uint8)
    for channel in range(3):
        samples=np.empty((201,720,1280),np.uint8)
        cap=cv2.VideoCapture(str(VIDEO));j=0
        for i in range(900):
            ok,image=cap.read()
            if not ok:raise RuntimeError('source ended before median window')
            if i in indices:samples[j]=image[...,channel];j+=1
        cap.release()
        # Odd201 sample median is exact; one channel bounds temporary memory.
        samples.partition(100,axis=0)
        background[...,channel]=samples[100]
        del samples
    cv2.imwrite(str(median_path),background)

players=pq.read_table(ROOT.parent/'demo-data/storage/checkpoints/971f099e-94b6-4387-8d4b-25a697cf20e3/players/0-60000000.payload.parquet').to_pylist()
raw=json.load(open(ROOT/'photometry-wide/comparison.json'))['variants']['inverted']['rows']
keys={f.name for f in fields(BallObservation)}
rows=[]
for source in raw:
    data={k:v for k,v in source.items() if k in keys}
    data['candidates']=tuple(BallCandidate(**candidate) for candidate in data['candidates'])
    rows.append(BallObservation(**data))
def frames():
    cap=cv2.VideoCapture(str(VIDEO))
    for i in range(900):
        ok,image=cap.read()
        if not ok:break
        yield Frame(round(i*1001/30000*1e6),i,image)
    cap.release()
filtered=DarkBallSupport(background,players).filter_rows(rows,frames())
selected=[asdict(row) for row in filtered if row.visible]
cal=json.load(open(ROOT/'manual-calibration.json'))['calibration']
projection=FloorProjection(tuple(tuple(row) for row in cal['result']['imageToCourt']),1,1)
impacts=derive_playback_impacts(players,selected,projection,calibration_revision=1)
impacts=attribute_shot_impacts(impacts,selected)
result={'diagnosticOnly':True,'method':CONTRAST_SUPPORT_POLICY_VERSION,'background':'Exact201 uniform BGR samples from0–30s','inputRows':len(rows),'invertedVisible':sum(row.visible for row in rows),'supportedVisible':len(selected),'rows':selected,'events':impacts}
(OUTPUT/'production-guard-replay.json').write_text(json.dumps(result,indent=2)+'\n')
print('supported',len(selected),'events',dict(Counter(e['kind'] for e in impacts)))
print('floor owners',[(e['timestamp_us']/1e6,e.get('shot_hitter'),e['floor_position']) for e in impacts if e['kind']=='floor'])
print('badframes262266',[(row.source_frame_index,row.visible) for row in filtered if row.source_frame_index in(262,266)])
