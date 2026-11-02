/**
 * Provider registry — resolves `gpu_backend` strings on a job row to the
 * right `Provider` implementation.
 *
 * Vast.ai and RunPod are declared but left as TODO stubs because the
 * worker happy-path only hits Modal today.
 */

import type { Logger } from '@papercrane/observability';
import type { WorkerConfig } from '../config';
import type { Provider, ProviderRegistry } from './types';
import { ModalProvider } from './modal';
import type { R2Handle } from '@papercrane/storage';

export class InMemoryProviderRegistry implements ProviderRegistry {
  private readonly providers = new Map<string, Provider>();

  register(provider: Provider): void {
    this.providers.set(provider.name, provider);
  }

  get(name: string): Provider {
    const p = this.providers.get(name);
    if (!p) throw new Error(`unknown provider: ${name}`);
    return p;
  }

  list(): string[] {
    return [...this.providers.keys()];
  }
}

export function buildProviderRegistry(
  config: WorkerConfig,
  logger: Logger,
  storage?: R2Handle,
): ProviderRegistry {
  const registry = new InMemoryProviderRegistry();

  registry.register(
    new ModalProvider({
      tokenId: config.providers.modal.tokenId,
      tokenSecret: config.providers.modal.tokenSecret,
      workspace: config.providers.modal.workspace,
      environment: config.providers.modal.environment,
      logger: logger.child({ component: 'modal-provider' }),
      storage,
    }),
  );

  // TODO(plan-03 §3.2): VastAiProvider — spot-priced A100s via their REST API
  // TODO(plan-03 §3.3): RunPodProvider — burst capacity when Modal quota hits ceiling

  return registry;
}

export type { Provider, ProviderRegistry } from './types';
