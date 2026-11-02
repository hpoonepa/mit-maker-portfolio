"""Prepare real personal footage and use the existing worker through app APIs.

No model loading or Worker instance is created here. The in-process transport is
for environments that restrict loopback networking; it uses the same persistent
API/database contract and leaves inference to the already-running worker.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parent
SOURCE = Path('/Users/harsha/Downloads/Sports_Squash/squashanalysisvideo/IMG_1314.mov')
OUT = ROOT / 'personal-rally'
STATE = OUT / 'manifest.json'
CLIP = OUT / 'practice-rallies-176-241.mp4'

def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()

def save(state):
    OUT.mkdir(exist_ok=True)
    temporary = STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2) + '\n')
    temporary.replace(STATE)

def checked(response):
    if not response.is_success:
        raise RuntimeError(f'{response.request.method} {response.request.url}: {response.status_code}: {response.text[:2000]}')
    return response.json()

@contextmanager
def client(transport):
    if transport == 'inprocess':
        from fastapi.testclient import TestClient
        from squashvision.app import create_app
        from squashvision.settings import Settings
        with TestClient(create_app(Settings(data_dir=ROOT / 'demo-data'))) as session:
            yield session
    else:
        import httpx
        with httpx.Client(base_url='http://127.0.0.1:8950', timeout=600) as session:
            yield session

def prepare(state):
    from squashvision.media import probe_video, resolve_ffmpeg_binary
    import av
    OUT.mkdir(exist_ok=True)
    if not CLIP.exists():
        temporary = CLIP.with_name('.preparing-practice-rallies.mp4')
        subprocess.run([str(resolve_ffmpeg_binary()), '-hide_banner', '-loglevel', 'error',
            '-ss', '176.0', '-i', str(SOURCE), '-t', '65.0', '-map', '0:v:0', '-map', '0:a:0?',
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-movflags', '+faststart', '-metadata',
            'comment=Personal local IMG_1314.mov excerpt; source176.0-241.0seconds; no synthetic frames',
            '-y', str(temporary)], check=True, timeout=300)
        temporary.replace(CLIP)
    if 'source' not in state:
        state['source'] = {'path': str(SOURCE), 'sha256': digest(SOURCE),
            'bytes': SOURCE.stat().st_size, 'probe': probe_video(SOURCE).model_dump(mode='json', by_alias=True)}
    state['clip'] = {'path': str(CLIP), 'sha256': digest(CLIP), 'bytes': CLIP.stat().st_size,
        'sourceStartSeconds': 176.0, 'sourceEndSeconds': 241.0,
        'probe': probe_video(CLIP).model_dump(mode='json', by_alias=True)}
    state.update(title='Practice rallies · IMG_1314', profile='maximum',
                 provenance='Actual local personal squash recording, extracted without generated motion or observations.',
                 identities='Unverified A/B track labels; navy/yellow player-name mapping not assigned.')
    with av.open(str(CLIP)) as container:
        frame = next(container.decode(video=0))
        frame.to_image().save(OUT / 'calibration-frame.jpg', quality=95)
        state['calibrationFrame'] = {'path': str(OUT / 'calibration-frame.jpg'),
            'clipTimestampSeconds': float(frame.time or 0), 'width': frame.width, 'height': frame.height}
    save(state)

def run(action, transport, ball_input_mode='original'):
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if action in {'prepare', 'import'}:
        prepare(state)
    if action == 'prepare':
        return
    with client(transport) as session:
        if action == 'import':
            if 'matchId' not in state:
                with CLIP.open('rb') as video:
                    match = checked(session.post('/api/v1/matches', data={'title': state['title']},
                        files={'video': (CLIP.name, video, 'video/mp4')}))
                state['matchId'] = match['id']
                (OUT / 'match-upload.json').write_text(json.dumps(match, indent=2) + '\n')
                save(state)
            print(json.dumps({'matchId': state['matchId'], 'clip': state['clip'],
                              'calibrationFrame': state['calibrationFrame']}, indent=2), flush=True)
            return
        match_id = state['matchId']
        if action in {'enqueue', 'reanalyze'}:
            if action == 'enqueue' and 'jobId' in state:
                raise RuntimeError('A job is already recorded; inspect it before creating another revision')
            if action == 'reanalyze':
                previous = checked(session.get(f"/api/v1/jobs/{state['jobId']}"))
                if previous['state'] != 'completed':
                    raise RuntimeError('Reanalysis requires the prior run to complete first')
                revision = state['reportRevision']
                for source, target in [('report.json', f'report-r{revision}.json'),
                                       ('practice-report.zip', f'practice-report-r{revision}.zip')]:
                    if not (OUT / target).exists():
                        (OUT / target).write_bytes((OUT / source).read_bytes())
                state.setdefault('previousRuns', []).append({k: state.get(k) for k in
                    ('jobId', 'reportRevision', 'ballInputMode', 'analysisStartedAtEpochSeconds', 'analysisWallSeconds', 'export')})
            roi = checked(session.get(f'/api/v1/matches/{match_id}/player-roi'))
            if not roi.get('points'):
                raise RuntimeError('Save the manually reviewed playing area before processing this demo')
            state['playerRoi'] = roi
            endpoint = 'reanalyze' if action == 'reanalyze' else 'jobs'
            job = checked(session.post(f'/api/v1/matches/{match_id}/{endpoint}', json={
                'profile': 'maximum', 'ballInputMode': ball_input_mode}))
            state.update(jobId=job['id'], job=job, ballInputMode=ball_input_mode,
                         analysisStartedAtEpochSeconds=time.time())
            save(state)
            print(json.dumps(job), flush=True)
            return
        if action == 'watch':
            while True:
                job = checked(session.get(f"/api/v1/jobs/{state['jobId']}"))
                state.update(job=job, analysisWallSeconds=time.time()-state['analysisStartedAtEpochSeconds'])
                save(state)
                print(json.dumps(job), flush=True)
                if job['state'] in {'completed', 'failed', 'cancelled', 'paused'}:
                    break
                time.sleep(15)
            if job['state'] != 'completed':
                return
        report = checked(session.get(f'/api/v1/matches/{match_id}/reports/latest'))
        (OUT / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        state['reportRevision'] = report['revision']
        export = checked(session.post(f'/api/v1/matches/{match_id}/exports', json={
            'revision': report['revision'], 'selection': {'formats': ['html', 'json', 'csv']}}))
        response = session.get(f"/api/v1/matches/{match_id}/exports/{export['id']}/download")
        response.raise_for_status()
        assert hashlib.sha256(response.content).hexdigest() == export['sha256']
        (OUT / 'practice-report.zip').write_bytes(response.content)
        state.update(export=export, exportChecksumVerified=True)
        save(state)
        print('Personal recording report and export verified', flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'import', 'enqueue', 'reanalyze', 'watch', 'verify'])
    parser.add_argument('--transport', choices=['http', 'inprocess'], default='http')
    parser.add_argument('--ball-input-mode', choices=['original', 'inverted'], default='original')
    arguments = parser.parse_args()
    run(arguments.action, arguments.transport, arguments.ball_input_mode)
