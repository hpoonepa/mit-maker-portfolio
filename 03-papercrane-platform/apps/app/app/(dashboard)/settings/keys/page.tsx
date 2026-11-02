import { KeyList } from "@/components/keys/KeyList";

/**
 * `/settings/keys`: API key management surface.
 *
 * Thin server shell; the `<KeyList />` client component owns all tRPC state
 * (list query + create / rotate / revoke mutations + modal orchestration).
 *
 * Route rationale:
 *   The dashboard migration groups account-settings-style screens under
 *   `/settings/...` (webhooks, members, billing, keys). A legacy `/app/keys`
 *   stub still exists: it will be removed once apps/web is fully retired.
 */
export default function KeysPage() {
  return (
    <div className="space-y-6">
      <header className="border-b border-graphite-soft/15 pb-5">
        <p className="font-sans text-[12px] text-graphite-soft">
          Developers
        </p>
        <h1 className=".5 font-sans text-[22px] font-medium tracking-tight text-ink">
          API keys
        </h1>
        <p className="mt-1.5 max-w-xl font-sans text-[13.5px] leading-relaxed text-graphite">
          Create, rotate, and revoke API keys. Secrets are shown once at
          creation: store them in a secrets manager. Rotate quarterly or on
          any suspected exposure.
        </p>
      </header>
      <KeyList />
    </div>
  );
}
