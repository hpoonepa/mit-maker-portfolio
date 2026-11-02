import csv
import os
import sys
import tempfile
import unittest
from pathlib import Path
from common import classify, sequence_id, sequence_clusters, write, read
from pilot import collect, compare, bounded
from prepare import mapping


class PilotTests(unittest.TestCase):
    def test_mapping_handles_signal_peptide_offset_and_internal_gap(self):
        reference = 'MKLVACDEFGHIKLMNPQRSTVWY'
        observed = reference[4:11] + reference[12:]
        m = mapping(reference, observed)
        self.assertEqual(m[0], 5)
        self.assertEqual(m[7], 13)
        self.assertEqual(m[len(observed)-1], len(reference))

    def test_sequence_format(self):
        for seq in ['ABC', 'A'*251, 'A'*20+':'+ 'G'*20, 'A'*20+'/GG']:
            with self.assertRaises(ValueError):
                sequence_id(seq)

    def test_clusters_do_not_count_near_duplicates(self):
        self.assertEqual(sequence_clusters(['A'*90, 'A'*89+'G', 'W'*90]), 2)

    def valid(self):
        runs = [dict(seed=i, status='ok', iptm=.8, binder_plddt=.9,
                     interface_pae=5, hotspot_contact=True) for i in range(3)]
        return {'monomer': {'plddt': .9}, 'human': [r.copy() for r in runs], 'mouse': [r.copy() for r in runs]}

    def test_gate_requires_both_species_and_replicates(self):
        r = self.valid()
        self.assertTrue(classify(r, 3))
        r['mouse'][0]['status'] = 'error'; r['mouse'][1]['iptm'] = .1
        self.assertFalse(classify(r, 3))

    def test_gate_rejects_missing_or_duplicate_seeds_and_missing_monomer(self):
        r = self.valid(); r['human'][1]['seed'] = 0
        self.assertFalse(classify(r, 3))
        r = self.valid(); r['mouse'].pop()
        self.assertFalse(classify(r, 3))
        r = self.valid(); del r['monomer']
        self.assertFalse(classify(r, 3))

    def test_collect_deduplicates_within_not_across_engines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); table = root/'bindcraft2/2_Refolded/!_Refolded.csv'
            table.parent.mkdir(parents=True)
            table.write_text('Binder_Sequence,design,outcome\n'+ 'A'*90+',one,rejected\n'+'A'*90+',two,passed\n')
            write(root/'mosaic/proposals/0.json', {'status':'ok','sequence':'A'*90})
            rows = collect(root)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]['id'], rows[1]['id'])

    def test_unknown_bc2_schema_is_not_silent_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); p = root/'bindcraft2/2_Refolded/!_Refolded.csv'
            p.parent.mkdir(parents=True); p.write_text('unexpected\nfoo\n')
            with self.assertRaises(ValueError): collect(root)

    def test_empty_and_partial_report_never_claims_winner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); compare(root)
            r = read(root/'comparison.json')
            self.assertIn('Inconclusive', r['decision'])
            self.assertIsNone(r['experimental_winner'])

    def test_timeout_stops_process_and_keeps_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = bounded([sys.executable, '-c', 'import time;time.sleep(30)'], tmp,
                        .1, Path(tmp)/'log', os.environ.copy())
            self.assertEqual(r['status'], 'budget_exhausted')
            self.assertLess(r['seconds'], 5)

    def test_nonzero_exit_is_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = bounded([sys.executable, '-c', 'raise SystemExit(7)'], tmp,
                        5, Path(tmp)/'log', os.environ.copy())
            self.assertEqual(r['status'], 'failed')
            self.assertEqual(r['returncode'], 7)

    def test_comparison_refuses_leader_when_evaluation_is_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            table = root/'bindcraft2/2_Refolded/!_Refolded.csv'
            table.parent.mkdir(parents=True)
            table.write_text('Binder_Sequence,design,outcome\n' +
                             '\n'.join(aa*60+f',design{i},passed' for i, aa in enumerate('ACDEFG'))+'\n')
            for i, aa in enumerate('HIKLMN'):
                write(root/f'mosaic/proposals/{i}.json', {'status':'ok','sequence':aa*60})
            for engine in ['bindcraft2', 'mosaic']:
                write(root/f'{engine}-receipt.json', {'status':'completed','seconds':3600})
            candidates = collect(root)
            for c in candidates:
                r = self.valid()
                r.update(complete=True, seconds=60, structure_gate=c['engine']=='bindcraft2')
                write(root/f'evaluation/{c["id"]}.json', r)
            compare(root)
            self.assertIn('leader: bindcraft2', read(root/'comparison.json')['decision'])
            c = candidates[-1]
            r = read(root/f'evaluation/{c["id"]}.json'); r['complete'] = False
            write(root/f'evaluation/{c["id"]}.json', r)
            compare(root)
            self.assertIn('Inconclusive', read(root/'comparison.json')['decision'])


if __name__ == '__main__':
    unittest.main()
