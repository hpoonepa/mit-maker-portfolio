/**
 * Turns a `jobs.submit` failure into a sentence a non-scientist can act on.
 *
 * The server messages are precise but written for engineers ("tool 'germinal'
 * is not yet runnable", "seed allocation exhausted: need 8,
 * available 2"). A first-time viewer must never be shown one of those raw, so
 * every known shape is rewritten here and anything unrecognised falls back to
 * a plain apology plus the original text, which is still better than a stack
 * trace.
 */
import { friendlyStructureRuntimeError } from "@/lib/pdb/structureSuitability";

export function friendlySubmitError(err: unknown, toolName?: string): string {
  const raw =
    err instanceof Error
      ? err.message
      : typeof err === "string"
        ? err
        : "Something went wrong.";
  const lower = raw.toLowerCase();
  const tool = toolName ?? "that tool";

  if (lower.includes("not allowed for tier")) {
    return `Your plan doesn't include ${tool}. Pick a different tool or contact support.`;
  }
  if (lower.includes("not yet runnable")) {
    return `${tool} doesn't have a complete execution backend yet. Choose a runnable tool instead.`;
  }
  if (lower.includes("gpu spend cap")) {
    // The server's cap message already carries the exact dollar figures and is
    // written in plain English: keep it verbatim rather than losing detail.
    return raw;
  }
  if (lower.includes("seed allocation exhausted")) {
    return "You've used the seeds included in this billing period. Lower the number of designs, or wait for the period to reset.";
  }
  if (lower.includes("exceeds the current per-job limit")) {
    return "That's more designs than a single job can run right now. Try a smaller number and submit again.";
  }
  if (lower.includes("targetpdb") || lower.includes("invalid targetid")) {
    return "We couldn't read that target. Check the PDB ID (four characters, e.g. 5O45) and try again.";
  }
  if (lower.includes("unauthorized") || lower.includes("forbidden")) {
    return "You don't have permission to run this. Try signing in again.";
  }
  if (lower.includes("fetch") || lower.includes("network")) {
    return "We couldn't reach the server. Check your connection and try again.";
  }

  // A tool that crashed inside its own mmCIF reader surfaces here as a Python
  // traceback. Rewrite it before it reaches the user.
  const structural = friendlyStructureRuntimeError(raw);
  if (structural) return structural;

  return `We couldn't submit the job. ${raw}`;
}
