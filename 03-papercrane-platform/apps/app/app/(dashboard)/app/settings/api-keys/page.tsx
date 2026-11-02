import { KeyList } from "@/components/keys/KeyList";

/**
 * `/app/settings/api-keys`: API key management surface.
 *
 * Wave 7 already shipped the `<KeyList />` client component which owns the
 * full lifecycle (list query, create modal, rotate dialog with 24h grace
 * explainer, revoke confirm with optional reason, scope chips, last-used
 * time, and the show-once secret reveal modal).
 *
 * This page is intentionally a thin shell: a settings-shaped header above
 * the existing list, so the URL `/app/settings/api-keys` mirrors the rest
 * of the settings tree without duplicating the heavy client logic.
 */
export default function ApiKeysSettingsPage() {
  return (
    <div className="space-y-8">
      <KeyList />
    </div>
  );
}
