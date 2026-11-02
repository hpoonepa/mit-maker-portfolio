import {
  encryptModalSecret,
  isEncryptedModalSecret,
  prisma,
} from "../src/index";

async function main(): Promise<void> {
  const rows = await prisma.modalCredential.findMany({
    select: { orgId: true, tokenSecret: true },
  });
  let encrypted = 0;

  for (const row of rows) {
    if (isEncryptedModalSecret(row.tokenSecret)) continue;
    await prisma.modalCredential.update({
      where: { orgId: row.orgId },
      data: { tokenSecret: encryptModalSecret(row.tokenSecret) },
    });
    encrypted += 1;
  }

  console.log(
    `Modal credential migration complete: ${encrypted} encrypted, ${rows.length - encrypted} already encrypted.`,
  );
}

main()
  .catch((error: unknown) => {
    console.error(
      error instanceof Error
        ? `Modal credential migration failed: ${error.message}`
        : "Modal credential migration failed",
    );
    process.exitCode = 1;
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
