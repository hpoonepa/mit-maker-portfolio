"""Optional fixed-microstate MD on an explicitly prepared PDB; NOT constant-pH MD.

Example: python md_microstate.py --pdb reviewed.pdb --variants variants.json --out md/hip_r1
variants.json maps chain:author_residue_id to HID/HIE/HIP, e.g. {"B:99": "HIP"}.
Use actual output residue IDs, not assumed UniProt numbering.
"""
import argparse
import json
import math
from pathlib import Path


def run(a):
    from openmm import LangevinMiddleIntegrator, MonteCarloBarostat, Platform
    from openmm.app import (PDBFile, Modeller, ForceField, PME, HBonds, Simulation,
                            DCDReporter, StateDataReporter, CheckpointReporter)
    from openmm.unit import nanometer, molar, kelvin, bar, picosecond, picoseconds
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=False)
    variants = json.loads(Path(a.variants).read_text())
    if not variants or not all(v in ('HID', 'HIE', 'HIP') for v in variants.values()):
        raise ValueError('Provide explicit histidine variants')
    pdb = PDBFile(a.pdb)
    ff = ForceField('amber14-all.xml', 'amber14/tip3pfb.xml')
    modeller = Modeller(pdb.topology, pdb.positions)
    residues = list(modeller.topology.residues())
    lookup = {f'{r.chain.id}:{r.id}{r.insertionCode}': r for r in residues}
    for key in variants:
        if key not in lookup or lookup[key].name not in ('HIS', 'HID', 'HIE', 'HIP'):
            raise ValueError(f'Variant must address an existing histidine: {key}')
    # Strip existing hydrogens so explicit variants are not defeated by input H atoms.
    modeller.delete([atom for atom in modeller.topology.atoms() if atom.element and atom.element.symbol == 'H'])
    specified = [variants.get(f'{r.chain.id}:{r.id}{r.insertionCode}') for r in modeller.topology.residues()]
    selected = modeller.addHydrogens(ff, pH=7.0, variants=specified)
    protonation_record = [{'chain': r.chain.id, 'residue': r.id, 'insertion_code': r.insertionCode,
                          'name': r.name, 'variant': v} for r, v in zip(modeller.topology.residues(), selected)]
    modeller.addSolvent(ff, padding=1.2*nanometer, ionicStrength=.15*molar)
    system = ff.createSystem(modeller.topology, nonbondedMethod=PME,
                            nonbondedCutoff=1.*nanometer, constraints=HBonds)
    system.addForce(MonteCarloBarostat(1*bar, 298*kelvin, 25))
    integrator = LangevinMiddleIntegrator(298*kelvin, 1/picosecond, .002*picoseconds)
    integrator.setRandomNumberSeed(a.seed)
    sim = Simulation(modeller.topology, system, integrator, Platform.getPlatformByName('CUDA'))
    sim.context.setPositions(modeller.positions)
    sim.minimizeEnergy(maxIterations=2000)
    sim.context.setVelocitiesToTemperature(298*kelvin, a.seed)
    # 1 ns unrestrained equilibration; inspect before interpreting production.
    sim.reporters.append(StateDataReporter(str(out/'equilibration.csv'), 5000, step=True,
        potentialEnergy=True, temperature=True, density=True, speed=True))
    sim.step(500000)
    sim.reporters.clear()
    with (out/'system.pdb').open('w') as f:
        PDBFile.writeFile(modeller.topology, sim.context.getState(getPositions=True).getPositions(), f)
    sim.reporters.append(DCDReporter(str(out/'trajectory.dcd'), 5000))
    sim.reporters.append(StateDataReporter(str(out/'production.csv'), 5000, step=True,
        potentialEnergy=True, temperature=True, density=True, speed=True))
    sim.reporters.append(CheckpointReporter(str(out/'checkpoint.chk'), 50000))
    (out/'manifest.json').write_text(json.dumps({'variants': variants, 'resolved_variants': protonation_record,
        'seed':a.seed, 'production_ns':a.ns, 'equilibration_ns':1,
        'pH':'not defined: fixed microstate', 'input':str(Path(a.pdb).resolve()),
        'caution':'Protein-only pilot. Missing atoms/residues or unsupported glycans must be repaired explicitly.'}, indent=2))
    sim.step(round(a.ns*500000))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pdb', required=True); p.add_argument('--variants', required=True)
    p.add_argument('--out', required=True); p.add_argument('--seed', type=int, default=1)
    p.add_argument('--ns', type=float, default=10)
    a = p.parse_args()
    if not math.isfinite(a.ns) or not 0 < a.ns <= 100: p.error('ns must be in (0, 100]')
    run(a)
