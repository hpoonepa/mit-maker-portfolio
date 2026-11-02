"""Bootstrap complete saved site outcomes, without recomputing or sampling interfaces."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def interval(values: np.ndarray) -> list[float]:
    """Same component-resampling convention as train_ranker.py: seed 0, B=2000."""
    rng = np.random.default_rng(0)
    boot = [values[rng.integers(len(values), size=len(values))].mean() for _ in range(2000)]
    return np.quantile(boot, [.025, .975]).tolist()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT/'data/eval/prince_connected_sites.json')
    parser.add_argument('--out', type=Path, default=ROOT/'data/eval/prince_connected_sites_uncertainty.json')
    args = parser.parse_args()
    data = json.loads(args.input.read_text())
    rows = data['instances']
    if data['errors'] or not (len(rows) == data['requested_instances'] == data['evaluated_instances']):
        raise ValueError('Complete site evaluation required: errors or missing interfaces remain')
    if len({row['id'] for row in rows}) != len(rows):
        raise ValueError('Duplicate site evaluation interfaces')
    for name, expected in data['source_sha256'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != expected:
            raise ValueError(f'Site evaluation input/protocol changed: {name}')
    cluster_ids = sorted({row['cluster'] for row in rows})
    summary, vectors = {}, {}
    for arm, metrics in data['summary'].items():
        summary[arm] = {}
        for metric, ranks in metrics.items():
            summary[arm][metric] = {}
            for rank, original in ranks.items():
                by_cluster = defaultdict(list)
                for row in rows:
                    by_cluster[row['cluster']].append(int(row['arms'][arm][metric][rank]))
                values = np.array([np.mean(by_cluster[c]) for c in cluster_ids])
                hits = sum(sum(values) for values in by_cluster.values())
                if hits != original['hits'] or original['n'] != len(rows):
                    raise ValueError('Saved per-instance outcomes disagree with aggregate counts')
                if not np.isclose(values.mean(), original['cluster_macro'], rtol=0, atol=1e-15):
                    raise ValueError('Saved per-instance outcomes disagree with component mean')
                summary[arm][metric][rank] = {
                    **original, 'instance_fraction': hits/len(rows),
                    'cluster_macro_ci95': interval(values), 'n_clusters': len(cluster_ids),
                }
                vectors[arm, metric, rank] = values
    paired = {}
    for left, right in [('fitted', 'exposure_only'), ('fitted+filter', 'fitted'),
                        ('exposure_only+filter', 'exposure_only')]:
        pair = f'{left}_minus_{right}'
        paired[pair] = {}
        for metric, ranks in data['summary'][left].items():
            paired[pair][metric] = {}
            for rank in ranks:
                difference = vectors[left, metric, rank] - vectors[right, metric, rank]
                paired[pair][metric][rank] = {
                    'cluster_macro_difference': float(difference.mean()),
                    'paired_cluster_bootstrap_ci95': interval(difference),
                }
    result = {
        'status': 'complete_saved_outcomes_verified', 'requested_instances': len(rows),
        'evaluated_instances': len(rows), 'n_clusters': len(cluster_ids), 'errors': [],
        'bootstrap': {'resampling_unit': 'connected component', 'replicates': 2000, 'seed': 0,
                      'ci': 'percentile 95%; may be degenerate when all components agree'},
        'majority_hit_definition': data['majority_hit_definition'],
        'half_epitope_recovery_definition': data['half_epitope_recovery_definition'],
        'interpretation': 'Each interface contributes a binary success at each k; neither metric is any-positive overlap or mean fraction of epitope residues recovered.',
        'filter_policy': data['filter_policy'], 'candidate_universe': data['candidate_universe'],
        'summary': summary, 'paired_differences': paired,
        'source_sha256': {
            str(args.input.resolve().relative_to(ROOT)): hashlib.sha256(args.input.read_bytes()).hexdigest(),
            str(Path(__file__).resolve().relative_to(ROOT)): hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        'generator_source_sha256': data['source_sha256'],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'output': str(args.out), 'evaluated_instances': len(rows),
                      'n_clusters': len(cluster_ids), 'status': result['status']}, indent=2))


if __name__ == '__main__':
    main()
