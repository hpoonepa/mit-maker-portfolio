#!/usr/bin/env python3
"""Recover explicit cached-feature identities; remove symmetry-copy candidate rows.

No geometric feature is recomputed or guessed. Unique ordered whole-chain
matching against the cached deposited assembly recovers each row's identity.
Ground-truth labels are regenerated from the manifest's explicit chain:seq:icode
keys, never concatenated display strings. Any ambiguous record aborts release.
"""
from __future__ import annotations
import csv
import gzip
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'src')]
from benchmark.evaluate import _antibody_chains
from benchmark.manifest import format_residue_key, parse_residues
from benchmark.external_bepipred.run import recover_positions
from hotspot_preflight.residue import ResidueKey


def main():
    paths = [ROOT/f'data/eval/features_{s}.jsonl.gz' for s in ('train','test')]
    with (ROOT/'data/benchmark/manifest.csv').open() as stream:
        manifest = {f"{r['pdb_id']}:{'+'.join(_antibody_chains(r))}":r for r in csv.DictReader(stream)}
    corrected, details = [], []
    for source in paths:
        with gzip.open(source,'rt') as stream:
            for line in stream:
                record = json.loads(line)
                if 'res' not in record:
                    raise ValueError(f"Original feature record errored: {record['id']}")
                row = manifest[record['id']]
                positions, _, assembly_error = recover_positions(row, record)
                if len(positions) != len(record['res']):
                    raise ValueError('Recovery changed row count')
                epitope = set(parse_residues(row['epitope_residues']))
                values, seen = [], set()
                changed, removed, copy_positives = 0, 0, 0
                for position, values_old in zip(positions, record['res']):
                    key = ResidueKey(*position['author'])
                    label = int(key in epitope)
                    if not position['declared_chain']:
                        removed += 1
                        copy_positives += int(values_old[5])
                        continue
                    if key in seen:
                        raise ValueError('Duplicate explicit residue identity')
                    seen.add(key)
                    changed += int(label != values_old[5])
                    values.append([format_residue_key(key), *values_old[1:5], label])
                if not values:
                    raise ValueError(f"No declared antigen rows: {record['id']}")
                corrected.append({'id':record['id'],'cluster':record['cluster'],
                    'residue_encoding':'chain:seq[:icode]', 'res':values})
                details.append({'id':record['id'],'original_rows':len(record['res']),
                    'retained_rows':len(values),'removed_copy_rows':removed,
                    'removed_copy_positive_labels':copy_positives,
                    'changed_declared_labels':changed,'assembly_fallback':assembly_error})
    out = ROOT/'data/eval/features_corrected.jsonl.gz'
    with out.open('wb') as stream:
        with gzip.GzipFile(filename='',mode='wb',fileobj=stream,mtime=0) as compressed:
            for record in corrected:
                compressed.write((json.dumps(record,separators=(',',':'))+'\n').encode())
    summary = {'schema_version':1,'status':'all_records_uniquely_recovered',
        'instances':len(corrected), 'method':'unique ordered full-chain identity matching; declared antigen chains only',
        'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        'output_sha256':hashlib.sha256(out.read_bytes()).hexdigest(),
        'removed_copy_rows':sum(d['removed_copy_rows'] for d in details),
        'removed_copy_positive_labels':sum(d['removed_copy_positive_labels'] for d in details),
        'changed_declared_labels':sum(d['changed_declared_labels'] for d in details),
        'retained_rows':sum(d['retained_rows'] for d in details),
        'instances_detail':details}
    (ROOT/'data/eval/feature_identity_repair.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k!='instances_detail'},indent=2))


if __name__ == '__main__':
    main()
