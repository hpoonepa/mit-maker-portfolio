/** Shared by the signup UI, callback and API. Invalid settings fail closed. */
export function betaGateEnabled(value: string | undefined): boolean {
  const flag = value?.trim().toLowerCase() ?? '';
  if (['', 'false', 'off', '0'].includes(flag)) return false;
  if (['true', 'on', '1'].includes(flag)) return true;
  throw new Error('NEXT_PUBLIC_BETA_GATE must be true or false (on/off and 1/0 are also accepted).');
}
