import { promises as fs } from 'node:fs';
import * as path from 'node:path';
import type {
  ContainerSpawnConfig,
  DesignRequest,
  PreparedJob,
  RunInContainerOptions,
  ToolManifest,
} from './types';

/**
 * Stage inputs into `workdir` and return a `ContainerSpawnConfig` the worker
 * layer uses to actually spawn the container. This function is pure w.r.t.
 * network and container runtimes — it only touches the filesystem under
 * `workdir` — so it's safe to call from test environments.
 *
 * Layout produced under `workdir`:
 *   inputs/
 *     request.json        (normalized DesignRequest)
 *     target.pdb          (caller stages this — we only ensure the dir)
 *   outputs/              (created empty, mounted writable)
 *
 * The actual spawn (exec → stream → sync) is the worker's responsibility;
 * this module stays SDK-pure so tool authors can unit-test adapters.
 */
export async function runInContainer(
  manifest: ToolManifest,
  request: DesignRequest,
  opts: RunInContainerOptions = {},
  workdir: string,
): Promise<ContainerSpawnConfig> {
  if (!workdir || path.isAbsolute(workdir) === false) {
    throw new Error(`runInContainer: workdir must be an absolute path (got "${workdir}")`);
  }

  const inputsDir = path.join(workdir, 'inputs');
  const outputsDir = path.join(workdir, 'outputs');
  const requestPath = path.join(inputsDir, 'request.json');
  const targetPath = path.join(inputsDir, 'target.pdb');

  await fs.mkdir(inputsDir, { recursive: true });
  await fs.mkdir(outputsDir, { recursive: true });
  await fs.writeFile(requestPath, JSON.stringify(request, null, 2));

  const runtime = opts.runtime ?? 'docker';
  const env: Record<string, string> = { ...(opts.env ?? {}) };

  // Prefer the pinned digest — falls back to the tag only if digest is missing.
  const imageRef = manifest.imageDigest
    ? `${manifest.image.split('@')[0]?.split(':')[0]}@${manifest.imageDigest}`
    : manifest.image;

  const args: string[] = ['run', '--rm'];

  if (opts.gpuDevices) {
    args.push('--gpus', opts.gpuDevices);
  } else if (manifest.compute.gpuCount > 0) {
    args.push('--gpus', 'all');
  }

  args.push('--cpus', String(manifest.compute.cpuCores));
  args.push('--memory', `${manifest.compute.memoryGb}g`);
  args.push('-v', `${inputsDir}:/inputs:ro`);
  args.push('-v', `${outputsDir}:/outputs`);

  for (const [k, v] of Object.entries(env)) {
    args.push('-e', `${k}=${v}`);
  }

  args.push(imageRef);

  const preparedJob: PreparedJob = {
    workdir,
    inputsDir,
    outputsDir,
    requestPath,
    targetPath,
    toolArtifacts: {},
  };

  const timeoutSeconds =
    opts.timeoutSeconds ?? Math.ceil(manifest.compute.estSecondsPerDesign * 1.5);

  return {
    runtime,
    args,
    env,
    cwd: workdir,
    timeoutSeconds,
    preparedJob,
    image: manifest.image,
    imageDigest: manifest.imageDigest,
  };
}
