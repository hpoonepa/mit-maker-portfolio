import {
  decryptModalSecret,
  isEncryptedModalSecret,
  type PrismaClient,
} from '@papercrane/db';

export interface OrgModalCredentials {
  tokenId: string;
  tokenSecret: string;
  workspace?: string;
  environment?: string;
}

type RawCredentialRow = {
  token_id: string;
  token_secret: string;
  workspace: string | null;
  environment: string | null;
};

export async function loadOrgModalCredentials(
  prisma: PrismaClient,
  orgId: string,
): Promise<OrgModalCredentials | null> {
  const rows = await prisma.$queryRaw<RawCredentialRow[]>`
    SELECT token_id, token_secret, workspace, environment
    FROM modal_credentials
    WHERE org_id = ${orgId}::uuid
    LIMIT 1
  `;
  const row = rows[0];
  if (!row) return null;
  if (!isEncryptedModalSecret(row.token_secret)) {
    throw new Error(
      'Modal credentials for this organization are still plaintext; run pnpm modal:encrypt-credentials before processing jobs.',
    );
  }
  return {
    tokenId: row.token_id,
    tokenSecret: decryptModalSecret(row.token_secret),
    workspace: row.workspace || undefined,
    environment: row.environment || undefined,
  };
}
