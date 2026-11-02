import { redirect } from "next/navigation";

export default function LegacyKeysPage(): never {
  redirect("/app/settings/api-keys");
}
