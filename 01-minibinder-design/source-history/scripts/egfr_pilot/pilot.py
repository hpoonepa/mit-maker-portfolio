#!/usr/bin/env python3
"""Bounded, sequential, same-device comparison. No cloud provisioning."""
import argparse
import csv
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from common import PINS, read, write, digest, sequence_id, sequence_clusters

HERE = Path(__file__).resolve().parent


def bounded(command, cwd, seconds, log, env):
    """Wall-clock cap includes compilation/downloads; terminate the process group."""
    start = time.monotonic()
    with Path(log).open('w') as output:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=output,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        status = 'completed'
        try:
            code = process.wait(timeout=seconds)
            if code:
                status = 'failed'
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
            status = 'budget_exhausted' if isinstance(exc, subprocess.TimeoutExpired) else 'interrupted'
            os.killpg(process.pid, signal.SIGTERM)
            try:
                code = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                code = process.wait()
        return {'status': status, 'returncode': code, 'seconds': time.monotonic()-start,
                'command': command, 'cwd': str(cwd), 'log': str(log)}


def collect(root):
    proposals, issues = {}, []
    bc = root / 'bindcraft2'
    tables = [bc / '1_Trajectories' / '!_Trajectories.csv',
              bc / '2_Refolded' / '!_Refolded.csv']
    for table in tables:
        if not table.exists():
            continue
        with table.open(newline='') as f:
            reader = csv.DictReader(f)
            if 'Binder_Sequence' not in (reader.fieldnames or []):
                raise ValueError(f'Unsupported BC2 output schema: {table}')
            for row in reader:
                if row.get('terminated'):
                    continue
                seq = (row.get('Binder_Sequence') or '').strip()
                try:
                    ident = sequence_id(seq)
                except ValueError:
                    issues.append({'source': str(table), 'design': row.get('design'), 'reason': 'invalid sequence'})
                    continue
                proposals[('bindcraft2', ident)] = {'engine': 'bindcraft2', 'id': ident,
                   'sequence': seq, 'source': str(table), 'native_outcome': row.get('outcome')}
    for path in sorted((root / 'mosaic' / 'proposals').glob('*.json')):
        data = read(path)
        if data['status'] != 'ok':
            issues.append({'source': str(path), 'reason': data.get('error')})
            continue
        seq = data['sequence']; ident = sequence_id(seq)
        proposals[('mosaic', ident)] = {'engine': 'mosaic', 'id': ident, 'sequence': seq, 'source': str(path)}
    values = sorted(proposals.values(), key=lambda x: (x['engine'], x['id']))
    write(root / 'candidates.json', values)
    write(root / 'collection_issues.json', issues)
    return values


def compare(root):
    candidates = collect(root)
    summaries = {}
    for engine in PINS:
        members = [c for c in candidates if c['engine'] == engine]
        receipt_path = root / f'{engine}-receipt.json'
        receipt = read(receipt_path) if receipt_path.exists() else {'status': 'not_run', 'seconds': 0}
        complete, passes, inference_errors, validation_seconds = [], [], 0, 0.
        for c in members:
            path = root / 'evaluation' / f'{c["id"]}.json'
            if not path.exists():
                continue
            r = read(path)
            if not r.get('complete'):
                continue
            complete.append(c)
            validation_seconds += r['seconds']
            if any(x.get('status') == 'error' for species in ['human', 'mouse'] for x in r[species]) or 'error' in r.get('monomer', {}):
                inference_errors += 1
            if r.get('structure_gate'):
                passes.append(c)
        hours = receipt['seconds'] / 3600
        families = sequence_clusters([c['sequence'] for c in passes])
        summaries[engine] = {'run_status': receipt['status'], 'generation_hours': hours,
           'unique_proposals': len(members), 'fully_evaluated': len(complete),
           'inference_error_candidates': inference_errors, 'structure_gate_passes': len(passes),
           'sequence_clusters_70pct': families,
           'clusters_per_generation_hour': families / hours if hours > 0 else 0,
           'allocated_evaluation_hours': validation_seconds/3600,
           'clusters_per_total_hour': families / (hours + validation_seconds/3600) if hours + validation_seconds > 0 else 0,
           'passing_ids': [c['id'] for c in passes]}
    reliable = all(s['run_status'] in ('completed', 'budget_exhausted')
                   and s['fully_evaluated'] == s['unique_proposals']
                   and s['fully_evaluated'] >= 6 and not s['inference_error_candidates'] for s in summaries.values())
    leader = None
    if reliable:
        ordered = sorted(summaries, key=lambda x: summaries[x]['clusters_per_total_hour'], reverse=True)
        a, b = (summaries[x] for x in ordered)
        if a['sequence_clusters_70pct'] >= 3 and a['clusters_per_total_hour'] > 1.5*b['clusters_per_total_hour']:
            leader = ordered[0]
    decision = (f'Provisional computational efficiency leader: {leader}. Repeat with independent seeds before reallocating heavily.'
                if leader else 'Inconclusive: no sufficiently supported computational efficiency leader.')
    result = {'decision': decision, 'engines': summaries, 'experimental_winner': None,
              'ph_selectivity': 'unmeasured', 'limitations': [
              'Thresholds are exploratory and uncalibrated for EGFR switching.',
              'DIII-only, protein-only prediction; full target and glycan review remain required.',
              'Common evaluator is Boltz2; model-family bias remains.',
              'Single pilot; sequence clusters are not structural families.',
              'Generation time includes model loading, compilation and any weight downloads.',
              'No laboratory affinity, pH, expression or novelty validation.']}
    write(root / 'comparison.json', result)
    lines = ['# EGFR engine pilot', '', decision, '',
             '| Engine | Hours | Proposals | Evaluated | Structural passes | Sequence clusters |',
             '|---|---:|---:|---:|---:|---:|']
    for name, s in summaries.items():
        lines.append(f'| {name} | {s["generation_hours"]:.2f} | {s["unique_proposals"]} | {s["fully_evaluated"]} | {s["structure_gate_passes"]} | {s["sequence_clusters_70pct"]} |')
    lines += ['', '**Experimental winner and pH selectivity remain unknown.**', ''] + ['- '+x for x in result['limitations']]
    (root / 'comparison.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines))


def run(args):
    root, deps = Path(args.work).resolve(), Path(args.deps).resolve()
    manifest = read(root / 'targets.json')
    unsigned = dict(manifest)
    if unsigned.pop('fingerprint') != digest(unsigned):
        raise ValueError('Target manifest changed after preparation')
    for t in manifest['targets'].values():
        if hashlib.sha256(Path(t['path']).read_bytes()).hexdigest() != t['sha256']:
            raise ValueError('Prepared target changed after mapping')
    settings = {'pins': PINS, 'target': manifest['fingerprint'], 'attempts': args.attempts,
                'length': args.length, 'hours_per_engine': args.hours, 'evaluation_hours': args.evaluation_hours,
                'seed': args.seed, 'evaluation_seeds': args.seeds, 'gpu': args.gpu,
                'code': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob('*.py')}}
    print(json.dumps(settings, indent=2))
    print(f'Maximum scheduled GPU wall time: {2*args.hours + args.evaluation_hours:g} hours (+termination grace).')
    if args.action == 'plan':
        return
    frozen = root / 'pilot-settings.json'
    if frozen.exists() and read(frozen) != settings:
        raise ValueError('Settings/code changed. Use a fresh work directory to avoid mixing experiments.')
    write(frozen, settings)
    repos = {k: deps / ('BindCraft2' if k == 'bindcraft2' else 'mosaic') for k in PINS}
    for engine, repo in repos.items():
        sha = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
        if sha != PINS[engine] or not (repo / '.venv/bin/python').exists():
            raise ValueError(f'{engine}: expected pinned checkout and .venv; run setup.sh')
        subprocess.run(['git', '-C', str(repo), 'diff', '--exit-code', 'HEAD', '--'], check=True, stdout=subprocess.DEVNULL)
    env = os.environ.copy()
    env.update(CUDA_VISIBLE_DEVICES=args.gpu, XLA_PYTHON_CLIENT_PREALLOCATE='false', PYTHONUNBUFFERED='1')
    hardware = subprocess.check_output(['nvidia-smi', '--query-gpu=uuid,name,memory.total', '--format=csv'], text=True)
    write(root / 'hardware.json', {'nvidia_smi': hardware, 'selected_gpu': args.gpu})
    bcsettings = {'campaign_name': 'egfr_pilot', 'project_folder': str(root/'bindcraft2'),
        'modality': 'binder', 'binder_lengths': [args.length, args.length],
        'max_trajectories': args.attempts, 'number_of_final_designs': 100000,
        'sequence_candidates': 2, 'kept_sequences': 1, 'campaign_seed': args.seed,
        'auto_multi_gpu': False, 'design_workers': 1,
        'targets': [{'name': species, 'target_path': t['path'], 'chains': 'A',
                     'hotspots': str(t['hotspot']), 'weight': 1.0} for species, t in manifest['targets'].items()]}
    write(root/'bc2.json', bcsettings)
    commands = {
      'bindcraft2': [str(repos['bindcraft2']/'.venv/bin/python'), '-m', 'bindcraft.cli', 'design', str(root/'bc2.json')],
      'mosaic': [str(repos['mosaic']/'.venv/bin/python'), str(HERE/'worker.py'), 'generate', '--work', str(root),
                '--attempts', str(args.attempts), '--length', str(args.length), '--seed', str(args.seed)]}
    for engine, cmd in commands.items():
        receipt = root / f'{engine}-receipt.json'
        if receipt.exists():
            print(f'{engine}: preserving previous bounded attempt; new budgets require a new work directory.')
            continue
        print(f'Starting {engine}; log {root / (engine+".log")}', flush=True)
        write(receipt, {'status': 'running', 'seconds': 0})
        finished = bounded(cmd, repos[engine], args.hours*3600, root/(engine+'.log'), env)
        write(receipt, finished)
        if finished['status'] == 'interrupted':
            compare(root)
            return
    candidates = collect(root)
    receipt = root/'evaluation-receipt.json'
    if candidates and not receipt.exists():
        cmd = [str(repos['mosaic']/'.venv/bin/python'), str(HERE/'worker.py'), 'evaluate',
               '--work', str(root), '--seeds', str(args.seeds)]
        write(receipt, {'status': 'running', 'seconds': 0})
        write(receipt, bounded(cmd, repos['mosaic'], args.evaluation_hours*3600, root/'evaluation.log', env))
    compare(root)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['plan', 'run', 'compare'])
    p.add_argument('--work', required=True); p.add_argument('--deps', default='artifacts/egfr-engines')
    p.add_argument('--hours', type=float, default=1.)
    p.add_argument('--evaluation-hours', type=float, default=2.)
    p.add_argument('--attempts', type=int, default=12); p.add_argument('--length', type=int, default=90)
    p.add_argument('--seed', type=int, default=20260930); p.add_argument('--seeds', type=int, default=3)
    p.add_argument('--gpu', default='0')
    a = p.parse_args()
    if not (0 < a.hours <= 24 and 0 < a.evaluation_hours <= 48 and 1 <= a.attempts <= 1000
            and 40 <= a.length <= 200 and 1 <= a.seeds <= 10):
        p.error('Invalid budget/count/length; see --help')
    if ',' in a.gpu:
        p.error('This comparison must use one GPU at a time')
    compare(Path(a.work).resolve()) if a.action == 'compare' else run(a)
