/**
 * Hand-rolled fuzzy matcher for the command palette.
 *
 * We intentionally avoid fuse.js to keep zero runtime deps. The scoring model
 * is a simplified Sublime-Text style match:
 *
 *   base score when all letters of `query` appear in `haystack` in order.
 *   + bonus for an exact substring match
 *   + large bonus if the substring is at position 0 (prefix)
 *   + bonus for contiguous runs of matched characters
 *   - tiny penalty for long haystacks (so short labels outrank long ones)
 *
 * Returns 0 when the query letters cannot be found in order. That way
 * `fuzzyRank` can drop non-matches with a falsy check.
 */

export interface FuzzyItem {
  id: string;
  title: string;
  keywords?: string[];
}

/**
 * Score a single label against a query. 0 means "no match".
 * Optional `keywords` are tried as additional match targets; the highest
 * score across title + keywords wins.
 */
export function fuzzyMatch(
  haystack: string,
  query: string,
  keywords: string[] = [],
): number {
  const q = query.trim().toLowerCase();
  if (q.length === 0) return 1; // empty query matches everything equally

  const candidates = [haystack, ...keywords];
  let best = 0;
  for (const candidate of candidates) {
    const score = scoreOne(candidate.toLowerCase(), q);
    if (score > best) best = score;
  }
  return best;
}

function scoreOne(haystack: string, query: string): number {
  // Direct substring: strongest signal.
  const idx = haystack.indexOf(query);
  if (idx !== -1) {
    let score = 1000 - idx; // earlier position = higher score
    if (idx === 0) score += 500; // prefix bonus
    // Short-label preference: shave a little for each extra char beyond query.
    score -= Math.max(0, haystack.length - query.length) * 0.5;
    return score;
  }

  // Scattered-letter match: every query char must appear in order.
  let h = 0;
  let runs = 0;
  let inRun = false;
  let matched = 0;
  for (let q = 0; q < query.length; q++) {
    const qc = query[q];
    let found = false;
    while (h < haystack.length) {
      if (haystack[h] === qc) {
        matched++;
        if (inRun) {
          runs++;
        } else {
          inRun = true;
        }
        h++;
        found = true;
        break;
      } else {
        inRun = false;
        h++;
      }
    }
    if (!found) return 0;
  }
  if (matched < query.length) return 0;

  // Base + contiguity bonus, minus length penalty.
  const base = 100;
  const lengthPenalty = Math.max(0, haystack.length - query.length) * 0.3;
  return base + runs * 10 - lengthPenalty;
}

/**
 * Rank a list of items by fuzzy score. Empty/whitespace queries return the
 * list unchanged (original order preserved), so the palette can show the full
 * catalog as the "idle" state.
 */
export function fuzzyRank<T extends FuzzyItem>(items: T[], query: string): T[] {
  const q = query.trim();
  if (q.length === 0) return items.slice();

  const scored: Array<{ item: T; score: number; originalIndex: number }> = [];
  items.forEach((item, originalIndex) => {
    const score = fuzzyMatch(item.title, q, item.keywords ?? []);
    if (score > 0) {
      scored.push({ item, score, originalIndex });
    }
  });

  scored.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    return a.originalIndex - b.originalIndex; // stable for ties
  });

  return scored.map((entry) => entry.item);
}
