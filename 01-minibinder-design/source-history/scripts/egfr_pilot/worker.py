"""Run inside the pinned Mosaic environment; imports models only in worker jobs."""
import argparse
import time
from pathlib import Path
from common import read, write, sequence_id, numeric, classify


def target_chain(info):
    import gemmi
    from mosaic.structure_prediction import TargetChain
    st = gemmi.read_structure(info['path'])
    chain = st[0][info['chain']].clone()
    return TargetChain(info['sequence'], use_msa=False, template_chain=chain)


def generate(args):
    import importlib.resources
    import mosaic
    import jax
    import jax.numpy as jnp
    import numpy as np
    from mosaic.common import TOKENS
    from mosaic.models.protenix import Protenix2025
    from mosaic.optimizers import simplex_APGM
    import mosaic.losses.structure_prediction as sp
    from mosaic.losses.protein_mpnn import InverseFoldingSequenceRecovery
    from mosaic.proteinmpnn.mpnn import ProteinMPNN
    assert jax.default_backend() == 'gpu', 'A CUDA GPU is required'
    manifest = read(Path(args.work) / 'targets.json')
    out = Path(args.work) / 'mosaic' / 'proposals'
    out.mkdir(parents=True, exist_ok=True)
    model = Protenix2025()
    mpnn = ProteinMPNN.from_pretrained(importlib.resources.files(mosaic) /
                                     'proteinmpnn/weights/soluble_v_48_020.pt')
    terms = []
    for info in manifest['targets'].values():
        features, _ = model.binder_features(args.length, [target_chain(info)])
        objective = (sp.BinderTargetContact()
                     + .5 * sp.BinderTargetContact(epitope_idx=[info['hotspot_index']],
                                                  paratope_size=6, contact_distance=8.)
                     + sp.WithinBinderContact() + .05 * sp.TargetBinderPAE()
                     + .05 * sp.BinderTargetPAE() + .025 * sp.IPTMLoss()
                     + .4 * sp.WithinBinderPAE() + .1 * sp.PLDDTLoss()
                     + 10 * InverseFoldingSequenceRecovery(mpnn, temp=jnp.array(.001)))
        terms.append(model.build_multisample_loss(loss=objective, features=features,
                     recycling_steps=1, sampling_steps=20, num_samples=1))
    loss = .5 * terms[0] + .5 * terms[1]
    for attempt in range(args.attempts):
        start = time.monotonic()
        seed = args.seed + attempt
        try:
            x = jax.nn.softmax(.5 * jax.random.gumbel(jax.random.key(seed), (args.length, 20)))
            _, x = simplex_APGM(loss_function=loss, x=x, n_steps=100,
                 stepsize=.15 * np.sqrt(args.length), momentum=.3, scale=1., max_gradient_norm=1.)
            _, x = simplex_APGM(loss_function=loss, x=jnp.log(x + 1e-5), n_steps=20,
                 stepsize=.5 * np.sqrt(args.length), momentum=0., scale=1.3,
                 logspace=False, max_gradient_norm=1.)
            seq = ''.join(TOKENS[int(i)] for i in np.asarray(x).argmax(-1))
            ident = sequence_id(seq)
            write(out / f'{attempt:04d}.json', {'status': 'ok', 'sequence': seq,
                  'id': ident, 'seed': seed, 'seconds': time.monotonic()-start})
        except Exception as exc:
            write(out / f'{attempt:04d}.json', {'status': 'error', 'seed': seed,
                  'error': f'{type(exc).__name__}: {exc}', 'seconds': time.monotonic()-start})
            raise
        print(f'proposal {attempt}: {ident}', flush=True)


def confidence(values):
    import numpy as np
    a = np.asarray(values).squeeze()
    if a.max() > 1.01:
        a = a / 100
    if not np.isfinite(a).all() or a.min() < 0 or a.max() > 1.01:
        raise ValueError('Invalid pLDDT values')
    return a


def chain_with_sequence(st, sequence, exclude=None):
    import gemmi
    for c in st[0]:
        residues = [r for r in c if r.find_atom('CA', '*')]
        if c.name != exclude and gemmi.one_letter_code([r.name for r in residues]) == sequence:
            return c, residues
    raise ValueError('Cannot map prediction chains to input sequences')


def measure(pred, sequence, info):
    import numpy as np
    binder, br = chain_with_sequence(pred.st, sequence)
    target, tr = chain_with_sequence(pred.st, info['sequence'], exclude=binder.name)
    def ca(residues):
        return np.array([[r.find_atom('CA', '*').pos.x, r.find_atom('CA', '*').pos.y,
                          r.find_atom('CA', '*').pos.z] for r in residues])
    distances = np.linalg.norm(ca(br)[:, None, :] - ca(tr)[None, :, :], axis=-1)
    contacts = distances < 8.
    b = len(sequence)
    pae = np.asarray(pred.pae).squeeze()
    if pae.shape != (b + len(tr), b + len(tr)):
        raise ValueError('Unexpected PAE/token mapping')
    interface = (pae[:b, b:][contacts].tolist() + pae[b:, :b].T[contacts].tolist())
    histidine = tr[info['hotspot_index']]
    hn = [a for a in histidine if a.name in ('ND1', 'NE2')]
    oxygens = [a for r in br if r.name in ('ASP', 'GLU')
               for a in r if a.name in ('OD1', 'OD2', 'OE1', 'OE2')]
    distances_ho = [a.pos.dist(o.pos) for a in hn for o in oxygens]
    return {'iptm': numeric(pred.iptm), 'binder_plddt': numeric(confidence(pred.plddt)[:b].mean()),
            'interface_pae': numeric(np.mean(interface)) if interface else 99.,
            'hotspot_contact': bool(contacts[:, info['hotspot_index']].any()),
            'acidic_O_to_H433_N_angstrom': min(distances_ho) if distances_ho else None,
            'contact_target_indices': np.where(contacts.any(axis=0))[0].tolist(),
            'binder_chain': binder.name, 'target_chain': target.name}


def evaluate(args):
    import jax
    from mosaic.models.boltz2 import Boltz2
    from mosaic.structure_prediction import TargetChain
    assert jax.default_backend() == 'gpu', 'A CUDA GPU is required'
    root = Path(args.work)
    manifest = read(root / 'targets.json')
    candidates = read(root / 'candidates.json')
    unique = {c['id']: c['sequence'] for c in candidates}
    model = Boltz2()
    for ident, seq in sorted(unique.items()):
        dest = root / 'evaluation' / f'{ident}.json'
        if dest.exists() and read(dest).get('complete'):
            continue
        start = time.monotonic()
        result = {'id': ident, 'sequence': seq, 'target_fingerprint': manifest['fingerprint'],
                  'human': [], 'mouse': [], 'seeds': args.seeds}
        (root / 'evaluation' / ident).mkdir(parents=True, exist_ok=True)
        for species, info in manifest['targets'].items():
            try:
                features, writer = model.target_only_features(
                    [TargetChain(seq, use_msa=False), target_chain(info)])
                for seed in range(args.seeds):
                    try:
                        pred = model.predict(features=features, writer=writer, recycling_steps=3,
                                             sampling_steps=50, key=jax.random.key(seed))
                        values = measure(pred, seq, info)
                        path = root / 'evaluation' / ident / f'{species}_{seed}.cif'
                        path.parent.mkdir(parents=True, exist_ok=True)
                        pred.st.make_mmcif_document().write_file(str(path))
                        result[species].append({'seed': seed, 'status': 'ok',
                                                'structure': str(path), **values})
                    except Exception as exc:
                        result[species].append({'seed': seed, 'status': 'error', 'error': str(exc)})
                    write(dest, result)
            except Exception as exc:
                result[species] = [{'seed': seed, 'status': 'error', 'error': str(exc)}
                                    for seed in range(args.seeds)]
        try:
            features, writer = model.target_only_features([TargetChain(seq, use_msa=False)])
            pred = model.predict(features=features, writer=writer, recycling_steps=3,
                                 sampling_steps=50, key=jax.random.key(0))
            result['monomer'] = {'plddt': numeric(confidence(pred.plddt).mean())}
            pred.st.make_mmcif_document().write_file(str(root / 'evaluation' / ident / 'monomer.cif'))
        except Exception as exc:
            result['monomer'] = {'error': str(exc)}
        result.update(complete=True, seconds=time.monotonic()-start,
                      structure_gate=classify(result, args.seeds), ph_selectivity='unmeasured')
        write(dest, result)
        print(f'evaluated {ident}: structural gate {result["structure_gate"]}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['generate', 'evaluate'])
    parser.add_argument('--work', required=True)
    parser.add_argument('--attempts', type=int, default=4)
    parser.add_argument('--length', type=int, default=90)
    parser.add_argument('--seed', type=int, default=20260930)
    parser.add_argument('--seeds', type=int, default=3)
    a = parser.parse_args()
    generate(a) if a.action == 'generate' else evaluate(a)
