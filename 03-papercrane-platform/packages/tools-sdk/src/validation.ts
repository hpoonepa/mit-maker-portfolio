import type { DesignRequest, ValidationError } from './types';

const UINT32_MAX = 0xffffffff;

/**
 * Default validator shared by every `Adapter`. Subclasses may override
 * `Adapter.validate()` to add tool-specific rules, but should still call
 * this first.
 */
export function defaultValidate(req: DesignRequest): ValidationError[] {
  const errors: ValidationError[] = [];

  if (!req.targetPdb || typeof req.targetPdb !== 'string' || req.targetPdb.trim() === '') {
    errors.push({ field: 'targetPdb', message: 'targetPdb is required' });
  }

  if (!Array.isArray(req.seeds) || req.seeds.length === 0) {
    errors.push({ field: 'seeds', message: 'seeds must be a non-empty array' });
  } else {
    for (const [idx, s] of req.seeds.entries()) {
      if (typeof s !== 'number' || !Number.isInteger(s) || s < 0 || s > UINT32_MAX) {
        errors.push({
          field: 'seeds',
          message: `seeds[${idx}] (${s}) must be an integer in [0, 2^32)`,
        });
      }
    }
    if (new Set(req.seeds).size !== req.seeds.length) {
      errors.push({ field: 'seeds', message: 'seeds must be unique' });
    }
  }

  if (typeof req.numDesigns !== 'number' || !Number.isInteger(req.numDesigns) || req.numDesigns <= 0) {
    errors.push({ field: 'numDesigns', message: 'numDesigns must be a positive integer' });
  } else if (Array.isArray(req.seeds) && req.numDesigns !== req.seeds.length) {
    errors.push({
      field: 'numDesigns',
      message: 'numDesigns must match the number of seeds',
    });
  }

  if (req.hotspots !== undefined) {
    if (!Array.isArray(req.hotspots)) {
      errors.push({ field: 'hotspots', message: 'hotspots must be an array' });
    } else {
      for (const [idx, h] of req.hotspots.entries()) {
        if (!h || typeof h !== 'object') {
          errors.push({ field: `hotspots[${idx}]`, message: 'hotspot must be an object' });
          continue;
        }
        if (typeof h.chain !== 'string' || h.chain.length !== 1) {
          errors.push({
            field: `hotspots[${idx}].chain`,
            message: 'chain must be a single-letter string',
          });
        }
        if (typeof h.resi !== 'number' || !Number.isInteger(h.resi) || h.resi < 1) {
          errors.push({
            field: `hotspots[${idx}].resi`,
            message: 'resi must be a positive integer',
          });
        }
      }
    }
  }

  if (req.constraints?.lengthRange) {
    const [lo, hi] = req.constraints.lengthRange;
    if (
      typeof lo !== 'number' ||
      typeof hi !== 'number' ||
      !Number.isInteger(lo) ||
      !Number.isInteger(hi) ||
      lo < 1 ||
      hi < lo
    ) {
      errors.push({
        field: 'constraints.lengthRange',
        message: `lengthRange must be [min, max] with 1 <= min <= max, got [${lo}, ${hi}]`,
      });
    }
  }

  return errors;
}
