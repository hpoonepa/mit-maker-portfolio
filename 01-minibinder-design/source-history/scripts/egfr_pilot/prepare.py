"""Download public targets, map canonical residues, and preserve raw inputs."""
import argparse
import hashlib
import io
import json
from pathlib import Path
from urllib.request import urlopen, Request

from Bio import Align, SeqIO
from Bio.PDB import PDBParser, PDBIO, Select
from Bio.SeqUtils import seq1
from common import write, read, digest, PINS


def fetch(url, path):
    path = Path(path)
    if not path.exists():
        with urlopen(Request(url, headers={"User-Agent": "egfr-pilot/1.0"}), timeout=90) as r:
            data = r.read()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + '.tmp')
        tmp.write_bytes(data)
        tmp.replace(path)
    return path


def mapping(reference, observed):
    aligner = Align.PairwiseAligner(mode='global', match_score=2, mismatch_score=-3,
                                   open_gap_score=-8, extend_gap_score=-.1)
    a = aligner.align(reference, observed)[0]
    return {int(j): int(i) + 1 for left, right in zip(*a.aligned)
            for i, j in zip(range(*left), range(*right))}


def prepare(root, human_pdb=None, mouse_pdb=None):
    root = Path(root).resolve()
    if (root / 'targets.json').exists():
        raise ValueError('Targets already frozen; use a new work directory to change preparation')
    raw = root / 'targets' / 'raw'
    raw.mkdir(parents=True, exist_ok=True)
    refs, sources = {}, []
    for species, accession in [('human', 'P00533'), ('mouse', 'Q01279')]:
        url = f'https://rest.uniprot.org/uniprotkb/{accession}.fasta'
        p = fetch(url, raw / f'{species}.fasta')
        rec = SeqIO.read(p, 'fasta')
        if accession not in rec.id:
            raise ValueError('Unexpected UniProt identity')
        refs[species] = str(rec.seq)
        sources.append({'url': url, 'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
    positions = mapping(refs['human'], refs['mouse'])
    inverse = {human: mouse + 1 for mouse, human in positions.items()}
    if refs['human'][432] != 'H' or refs['mouse'][inverse[433] - 1] != 'H':
        raise ValueError('H433 identity/conservation check failed')
    outputs = {}
    for species, accession, supplied in [('human', 'P00533', human_pdb), ('mouse', 'Q01279', mouse_pdb)]:
        if supplied:
            source = Path(supplied).resolve()
            url = str(source)
        elif species == 'human':
            url = 'https://files.rcsb.org/download/6ARU.pdb'
            source = fetch(url, raw / '6ARU.pdb')
        else:
            api = f'https://alphafold.ebi.ac.uk/api/prediction/{accession}'
            metadata = fetch(api, raw / 'mouse-alphafold.json')
            entries = read(metadata)
            entry = next(x for x in entries if x['uniprotAccession'] == accession)
            url = entry['pdbUrl']
            source = fetch(url, raw / 'mouse-alphafold.pdb')
        sources.append({'url': url, 'path': str(source), 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()})
        structure = PDBParser(QUIET=True).get_structure(species, str(source))
        chain = structure[0]['A']
        residues = [r for r in chain if r.id[0] == ' ' and 'CA' in r]
        observed = ''.join(seq1(r.resname) for r in residues)
        aligned = mapping(refs[species], observed)
        wanted = list(range(335, 539)) if species == 'human' else [inverse[i] for i in range(335, 539)]
        wanted = sorted(set(wanted))
        selected = [(r, aligned[j]) for j, r in enumerate(residues) if aligned.get(j) in wanted]
        if [n for _, n in selected] != wanted:
            raise ValueError(f'{species}: missing DIII residues; repair/inspect target before running')
        for r, n in selected:
            if seq1(r.resname) != refs[species][n-1]:
                raise ValueError(f'{species}: target mutation at canonical {n}; do not silently rename atoms')
        seq = ''.join(seq1(r.resname) for r, _ in selected)
        hotspot = 433 if species == 'human' else inverse[433]
        # New isolated structure, canonical numbering; originals including glycans remain untouched.
        from Bio.PDB.Structure import Structure
        from Bio.PDB.Model import Model
        from Bio.PDB.Chain import Chain
        out = Structure(species); model = Model(0); newchain = Chain('A')
        out.add(model); model.add(newchain)
        residue_map = []
        for index, (residue, canonical) in enumerate(selected):
            copy = residue.copy(); copy.detach_parent(); copy.id = (' ', canonical, ' ')
            newchain.add(copy)
            residue_map.append({'index': index, 'canonical': canonical,
                                'author_id': list(residue.id), 'aa': seq1(residue.resname)})
        dest = root / 'targets' / f'{species}_d3.pdb'
        writer = PDBIO(); writer.set_structure(out); writer.save(str(dest))
        outputs[species] = {'path': str(dest), 'chain': 'A', 'sequence': seq,
                            'hotspot': hotspot, 'hotspot_index': wanted.index(hotspot),
                            'residue_map': residue_map,
                            'sha256': hashlib.sha256(dest.read_bytes()).hexdigest()}
    manifest = {'targets': outputs, 'sources': sources, 'engine_pins': PINS,
                'limitations': ['DIII-only computational pilot; no experimental pH prediction',
                                'Raw glycans preserved; design crops omit glycans',
                                'Full ectodomain/glycan accessibility review required before submission',
                                'Mouse structure is predicted unless a reviewed override was supplied']}
    manifest['fingerprint'] = digest(manifest)
    write(root / 'targets.json', manifest)
    print(f'Prepared and mapped H433 in both species: {root / "targets.json"}')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--work', required=True)
    p.add_argument('--human-pdb'); p.add_argument('--mouse-pdb')
    args = p.parse_args()
    prepare(args.work, args.human_pdb, args.mouse_pdb)
