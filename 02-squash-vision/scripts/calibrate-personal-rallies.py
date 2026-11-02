"""Apply reviewed visible floor landmarks to the personal practice excerpt."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from personal_rally_demo import client, checked
from squashvision.calibration import CourtCorrespondence, CourtKeypoints, CourtPoint, ImagePoint, Size, fit_calibration

OUT = ROOT / 'runtime/personal-rally'
MATCH = '6396ff4c-fa54-4c77-a342-d7027853e029'
# Reviewed against clip0s and29s frames. All metric points are visible court
# landmarks; the image-edge floor-mask vertices below are not court corners.
LANDMARKS = [
    ('front_left_floor', 315, 407, 0, 0),
    ('front_right_floor', 816, 410, 6.4, 0),
    ('short_line_left_center', 203, 492, 0, 5.465),
    ('left_service_inner_front', 447, 491, 1.625, 5.465),
    ('short_line_T_center', 668.5, 490, 3.2, 5.465),
    ('right_service_inner_front', 871, 488, 4.775, 5.465),
    ('short_line_right_center', 1063, 486, 6.4, 5.465),
    ('left_service_back_wall_center', 121, 555.5, 0, 7.115),
    ('left_service_inner_back', 447, 550.5, 1.625, 7.115),
    ('right_service_inner_back', 985, 538.5, 4.775, 7.115),
    ('right_service_back_wall_center', 1222, 535, 6.4, 7.115),
]
points = tuple(CourtCorrespondence(label, ImagePoint(x,y), CourtPoint(cx,cy)) for label,x,y,cx,cy in LANDMARKS)
fit = fit_calibration(CourtKeypoints(points), Size(1280,720))
if not fit.calibrated or sum(fit.inlier_mask) < 8 or fit.rms_error_px > 2:
    raise RuntimeError(f'Landmark fit requires review: {fit}')
with client('inprocess') as session:
    current = session.get(f'/api/v1/matches/{MATCH}/calibration')
    revision = current.json()['revision'] if current.is_success else 0
    if current.status_code not in (200,404):
        checked(current)
    calibration = checked(session.put(f'/api/v1/matches/{MATCH}/calibration',json={
        'expectedRevision':revision, 'frameSize':{'width':1280,'height':720},
        'keypoints':[{'label':label,'image':{'x':x,'y':y},'court':{'xM':cx,'yM':cy}} for label,x,y,cx,cy in LANDMARKS]}))
    roi = checked(session.get(f'/api/v1/matches/{MATCH}/player-roi'))
    roi = checked(session.put(f'/api/v1/matches/{MATCH}/player-roi',json={
        'expectedRevision':roi['revision'],'sourceSha256':roi['sourceSha256'],'frameSize':roi['frameSize'],
        'points':[{'x':x,'y':y} for x,y in [(315,405),(817,409),(1279,553),(1279,719),(0,719),(0,655)]]}))
evidence = {'matchId':MATCH,'calibration':calibration,'playerRoi':roi,
    'sourceFrames':['calibration-frame.jpg','calibration-frame-29s.jpg'],
    'method':'Manual visible floor-line centers, front-floor corners and service-box intersections',
    'coordinateOrigin':'Front-left floor; X rightward, Y toward back wall; metres',
    'limitations':['Manual pixels and glass/lens distortion limit metric accuracy.',
                   'RANSAC may reject an edge landmark; the complete input and inlier mask are retained.',
                   'Fitting residual measures internal geometric consistency, not ground-truth accuracy.',
                   'Calibration is valid for this fixed camera excerpt; rear court corners extend outside the image.']}
(OUT/'manual-calibration.json').write_text(json.dumps(evidence,indent=2)+'\n')
print(json.dumps({'matchId':MATCH,'calibrationRevision':calibration['revision'],'rmsErrorPx':fit.rms_error_px,'inliers':fit.inlier_mask,'roiRevision':roi['revision']}))
