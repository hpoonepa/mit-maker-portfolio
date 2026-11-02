# @papercrane/tools-sdk

The Tool SDK: a single contract every wrapped tool — open-source or frontier — implements. The platform never knows whether it is calling RFdiffusion in a local container or a licensed HTTPS endpoint. See `docs/plans/02-tool-integration.md` for the full design.

## The contract

```ts
abstract class Adapter {
  abstract manifest: ToolManifest;
  validate(req: DesignRequest): ValidationError[];      // default rules provided
  abstract prepare(req: DesignRequest, workdir: string): Promise<PreparedJob>;
  abstract run(job: PreparedJob): Promise<RawOutput>;
  abstract parse(raw: RawOutput): Promise<DesignResult>;
}
```

Four responsibilities, in order:

1. `validate(req)` — catch bad requests before spending GPU time. The default validator checks `targetPdb`, `seeds` (uint32), `numDesigns`, hotspots, and `lengthRange`. Override and compose with `defaultValidate` if you have tool-specific rules.
2. `prepare(req, workdir)` — stage inputs under `workdir`, write `inputs/request.json`, and return a `PreparedJob`. MUST be pure (no network, no container spawn). Runs in the same process as the orchestrator.
3. `run(job)` — actually execute the tool. For local adapters this spawns a container (use `runInContainer` to build the spawn config). For remote adapters this hits an HTTPS endpoint.
4. `parse(raw)` — normalize tool-native outputs into `DesignResult { designs[], runMetadata }`.

## Subclassing `Adapter` (local container tool)

```ts
import { Adapter, runInContainer } from '@papercrane/tools-sdk';
import type { DesignRequest, PreparedJob, RawOutput, DesignResult } from '@papercrane/tools-sdk';
import manifestJson from './manifest.json';

export class BindCraftAdapter extends Adapter {
  manifest = manifestJson;

  async prepare(req: DesignRequest, workdir: string): Promise<PreparedJob> {
    const spawn = await runInContainer(this.manifest, req, {}, workdir);
    // Write any extra tool config files into spawn.preparedJob.inputsDir here.
    return spawn.preparedJob;
  }

  async run(job: PreparedJob): Promise<RawOutput> {
    // The worker layer consumes the ContainerSpawnConfig; for local testing
    // you can shell out to `docker run ...` directly.
    throw new Error('run() is handled by the worker for local tools');
  }

  async parse(raw: RawOutput): Promise<DesignResult> {
    // Read files from raw.outputDir/designs, pair .pdb + .json, emit designs.
    return { designs: [], runMetadata: { tool: this.manifest.id } };
  }
}
```

## Subclassing `RemoteAdapter` (closed-weight HTTPS tool)

```ts
import { RemoteAdapter } from '@papercrane/tools-sdk';
import type { DesignRequest, PreparedJob, RawOutput, DesignResult } from '@papercrane/tools-sdk';

export class AlphaFold3Adapter extends RemoteAdapter {
  manifest = /* ... tier: 'frontier' ... */;

  async prepare(req: DesignRequest, workdir: string): Promise<PreparedJob> {
    // Build the request payload to send to the API.
  }

  async run(job: PreparedJob): Promise<RawOutput> {
    const res = await this.httpClient.request({
      url: this.endpoint,
      method: 'POST',
      body: /* ... */,
      timeoutMs: 600_000,
    });
    return { outputDir: job.outputsDir, exitCode: 0, stdout: '', stderr: '', payload: res.data };
  }

  async parse(raw: RawOutput): Promise<DesignResult> { /* ... */ }
}
```

Instantiate with the endpoint and API key:

```ts
const af3 = new AlphaFold3Adapter({
  endpoint: 'https://api.deepmind.example/af3/v1/predict',
  apiKey: process.env.AF3_API_KEY,
});
```

## Composition

Two adapters A → B can be composed into a single adapter with `compose(A, B)`. A's `parse()` output is fed as `upstreamDesigns` into B's `prepare`. The canonical case is RFdiffusion → ProteinMPNN.

```ts
import { compose } from '@papercrane/tools-sdk';
const chain = compose(new RFdiffusionAdapter(), new ProteinMPNNAdapter());
```

The composed adapter's `manifest.category` is `composite`; its `composes` field lists the constituent tool ids.

## Manifests

Every tool ships a `manifest.json`. The SDK ships a Zod schema you can parse at build time:

```ts
import { loadManifest } from '@papercrane/tools-sdk';
const manifest = await loadManifest('./tools/bindcraft/manifest.json');
```

`loadManifest` throws a descriptive error if the file is missing or fails validation — use it in CI to catch manifest drift.

## Testing

```
npm test          # run once
npm run test:watch
npm run typecheck
```

Tests live under `tests/`; see `tests/adapter.test.ts` for the minimum subclass shape.
