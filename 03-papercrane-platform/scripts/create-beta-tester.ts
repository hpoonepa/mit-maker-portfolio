#!/usr/bin/env tsx
import { readFileSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { createClient } from "@supabase/supabase-js";

type Env = Record<string, string>;
let prismaForDisconnect: { $disconnect: () => Promise<void> } | null = null;

function loadEnv(): Env {
  const env: Env = { ...process.env } as Env;
  let dir = process.cwd();
  let path = resolve(dir, ".env.local");
  while (!existsSync(path) && dirname(dir) !== dir) {
    dir = dirname(dir);
    path = resolve(dir, ".env.local");
  }
  if (!existsSync(path)) return env;
  const raw = readFileSync(path, "utf8");
  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq < 0) continue;
    const key = trimmed.slice(0, eq).trim();
    let value = trimmed.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (!(key in env)) env[key] = value;
  }
  return env;
}

function arg(name: string): string | undefined {
  const prefix = `--${name}=`;
  return process.argv.find((v) => v.startsWith(prefix))?.slice(prefix.length);
}

function requiredArg(name: string): string {
  const value = arg(name);
  if (!value) {
    throw new Error(`missing --${name}=...`);
  }
  return value;
}

function randomPassword(): string {
  const alphabet =
    "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@$%";
  let out = "";
  for (let i = 0; i < 24; i++) {
    out += alphabet[Math.floor(Math.random() * alphabet.length)];
  }
  return out;
}

function slugify(input: string): string {
  const slug = input
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
  return slug || "beta-org";
}

async function main() {
  const env = loadEnv();
  for (const [key, value] of Object.entries(env)) {
    process.env[key] = value;
  }
  const email = requiredArg("email").toLowerCase();
  const { prisma } = await import("@papercrane/db");
  prismaForDisconnect = prisma;
  const name = arg("name") ?? "Dr. Abedi";
  const orgName = arg("org") ?? "Abedi Lab";
  const orgSlug = slugify(arg("slug") ?? orgName);
  const password = arg("password") ?? randomPassword();
  const seedsQuota = Number(arg("seeds") ?? "125000");
  const modalBudgetUsd = Number(arg("modal-budget-usd") ?? "50");
  const storeModal = arg("store-modal") !== "false";

  const supabaseUrl =
    env.NEXT_PUBLIC_SUPABASE_URL ?? env.SUPABASE_URL;
  const serviceRole = env.SUPABASE_SERVICE_ROLE_KEY;
  if (!supabaseUrl || !serviceRole) {
    throw new Error(
      "NEXT_PUBLIC_SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required",
    );
  }

  const admin = createClient(supabaseUrl, serviceRole, {
    auth: { persistSession: false },
  });

  const created = await admin.auth.admin.createUser({
    email,
    password,
    email_confirm: true,
    user_metadata: {
      full_name: name,
      pending_org_name: orgName,
      beta_tester: true,
    },
  });

  let userId = created.data.user?.id;
  if (created.error && /already/i.test(created.error.message)) {
    const listed = await admin.auth.admin.listUsers();
    if (listed.error) throw listed.error;
    const existing = listed.data.users.find(
      (user) => user.email?.toLowerCase() === email,
    );
    if (!existing) throw created.error;
    userId = existing.id;
    const updated = await admin.auth.admin.updateUserById(userId, {
      password,
      email_confirm: true,
      user_metadata: {
        ...existing.user_metadata,
        full_name: name,
        pending_org_name: orgName,
        beta_tester: true,
      },
    });
    if (updated.error) throw updated.error;
  } else if (created.error) {
    throw created.error;
  }

  if (!userId) throw new Error("Supabase did not return a user id");

  await prisma.user.upsert({
    where: { id: userId },
    update: { email, name },
    create: { id: userId, email, name },
  });

  const org = await prisma.organization.upsert({
    where: { slug: orgSlug },
    update: {
      tier: "pro",
      seedsQuota,
      retentionDays: 30,
    },
    create: {
      slug: orgSlug,
      tier: "pro",
      seedsQuota,
      seedsUsed: 0,
      retentionDays: 30,
    },
  });

  await prisma.orgMember.upsert({
    where: { orgId_userId: { orgId: org.id, userId } },
    update: { role: "owner" },
    create: { orgId: org.id, userId, role: "owner" },
  });

  await prisma.user.update({
    where: { id: userId },
    data: { defaultOrgId: org.id },
  });

  await prisma.featureFlag.upsert({
    where: { orgId: org.id },
    update: {
      retentionDays: 30,
      maxConcurrent: 1,
      byocRequired: false,
      onCap: "block",
      notes: `Beta tester org. Paper Crane pays compute. Modal budget target: $${modalBudgetUsd}.`,
    },
    create: {
      orgId: org.id,
      retentionDays: 30,
      maxConcurrent: 1,
      vpcEnabled: false,
      closedWeightsAllowed: false,
      byocRequired: false,
      onCap: "block",
      notes: `Beta tester org. Paper Crane pays compute. Modal budget target: $${modalBudgetUsd}.`,
    },
  });

  if (storeModal && env.MODAL_TOKEN_ID && env.MODAL_TOKEN_SECRET) {
    await prisma.modalCredential.upsert({
      where: { orgId: org.id },
      update: {
        tokenId: env.MODAL_TOKEN_ID,
        tokenSecret: env.MODAL_TOKEN_SECRET,
        workspace: env.MODAL_WORKSPACE ?? "",
        lastValidatedAt: new Date(),
        lastError: null,
      },
      create: {
        orgId: org.id,
        tokenId: env.MODAL_TOKEN_ID,
        tokenSecret: env.MODAL_TOKEN_SECRET,
        workspace: env.MODAL_WORKSPACE ?? "",
        lastValidatedAt: new Date(),
        lastError: null,
      },
    });
  }

  console.log(
    JSON.stringify(
      {
        ok: true,
        email,
        password,
        userId,
        orgId: org.id,
        orgSlug: org.slug,
        seedsQuota,
        modalBudgetUsd,
        modalCredentialStored:
          storeModal && Boolean(env.MODAL_TOKEN_ID && env.MODAL_TOKEN_SECRET),
      },
      null,
      2,
    ),
  );
}

main()
  .catch((err) => {
    console.error(err instanceof Error ? err.message : err);
    process.exitCode = 1;
  })
  .finally(async () => {
    if (prismaForDisconnect) await prismaForDisconnect.$disconnect();
  });
