import { describe, it, expect } from 'vitest';
import { duplicateInput } from './duplicateInput';

describe('duplicateInput', () => {
  it('restores the saved target, hotspots, constraints and original seeds', () => {
    const result = duplicateInput({ targetPdb: '5O45', targetChain: 'A', seeds: [42], hotspots: [{ chain: 'A', residues: [35] }], constraints: { lengthRange: [60, 150] }, toolParams: { targetId: 'target-1', projectId: 'project-1', contigs: 'A1-100/0 60-150' } }, [{ id: 'target-1', name: 'PD-L1', pdbId: '5O45', chain: 'A', createdAt: new Date() }]);
    expect(result.targetId).toBe('target-1');
    expect(result.projectId).toBe('project-1');
    expect(result.seeds).toEqual([42]);
    expect(result.extras).toMatchObject({ hotspots: [{ chain: 'A', residues: [35] }], constraints: { lengthRange: [60, 150] } });
    expect(result.toolParams.contigs).toBe('A1-100/0 60-150');
  });
  it('restores sequence and ligand input without changing residue order', () => {
    const result = duplicateInput({ toolParams: { sequences: [{ id: 'A', sequence: 'ACDEFG' }], ligand: 'ATP' } }, []);
    expect(result.sequences).toEqual({ raw: '>A\nACDEFG', sequences: [{ id: 'A', sequence: 'ACDEFG' }] });
    expect(result.ligand).toEqual({ mode: 'ccd', ccd: 'ATP' });
  });
  it('restores uploaded backbones as file references, not invalid PDB IDs', () => {
    const result = duplicateInput({ request: { targetPdb: 'orgs/lab/targets/upload.cif', targetChain: 'B' } }, []);
    expect(result.backbone.uploadKey).toBe('orgs/lab/targets/upload.cif');
    expect(result.backbone.chain).toBe('B');
  });
});
