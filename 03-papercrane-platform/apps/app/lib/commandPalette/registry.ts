/**
 * Command registry for the global palette.
 *
 * The registry is split into three layers:
 *   1. `navigationCommands`: static "Go to ..." entries. Always available.
 *   2. `buildActionCommands(context)`: actions that depend on app context
 *      (e.g. "Submit Job" only shows when a project is active).
 *   3. `allStaticCommands(context)`: merged view used for the idle palette
 *      state (no query typed yet).
 *
 * Live/async results (projects/jobs/targets/tools/docs) are NOT stored here -
 * they come from `providers.ts`, which hits tRPC / local catalogs on demand.
 */

export type CommandGroup =
  | "Navigation"
  | "Actions"
  | "Projects"
  | "Jobs"
  | "Targets"
  | "Tools"
  | "Docs"
  | "Recent";

export interface CommandRouter {
  /** Minimal contract; compatible with Next.js `useRouter().push`. */
  push: (path: string) => void;
}

export interface CommandActionContext {
  router?: CommandRouter;
  /** Called by actions that need to surface an inline toast/dialog. */
  notify?: (msg: string) => void;
}

export interface Command {
  id: string;
  title: string;
  subtitle?: string;
  group: CommandGroup;
  icon?: string; // lucide icon name; rendered by CommandItem
  keywords?: string[];
  action: (ctx: CommandActionContext) => void | Promise<void>;
}

export interface BuildContext {
  /** Current project, if any. Enables project-scoped actions. */
  currentProjectId?: string;
}

/**
 * Factory helper: every nav command is a simple router.push.
 */
function navCommand(
  id: string,
  title: string,
  path: string,
  keywords: string[] = [],
  icon?: string,
): Command {
  return {
    id,
    title,
    group: "Navigation",
    keywords: [...keywords, "go", "open", "navigate"],
    icon,
    subtitle: path,
    action: ({ router }) => {
      router?.push(path);
    },
  };
}

export const navigationCommands: Command[] = [
  navCommand("nav.dashboard", "Go to Dashboard", "/home", ["home"], "layout-dashboard"),
  navCommand("nav.projects", "Go to Projects", "/projects", ["workspace"], "folder-open"),
  navCommand("nav.jobs", "Go to Jobs", "/jobs", ["runs", "queue"], "play-circle"),
  navCommand("nav.targets", "Go to Targets", "/targets", ["structures", "pdb"], "target"),
  navCommand("nav.leaderboard", "Go to Leaderboard", "/leaderboard", ["ranking", "top"], "trophy"),
  navCommand("nav.usage", "Go to Usage", "/usage", ["gpu", "billing", "quota"], "activity"),
  navCommand("nav.keys", "Go to API Keys", "/settings/keys", ["api", "token"], "key"),
  navCommand("nav.webhooks", "Go to Webhooks", "/settings/webhooks", ["callbacks", "events"], "webhook"),
  navCommand("nav.billing", "Go to Billing", "/settings/billing", ["invoice", "plan"], "credit-card"),
  navCommand("nav.members", "Go to Members", "/settings/members", ["team", "invite"], "users"),
  navCommand("nav.audit", "Go to Audit Log", "/settings/audit", ["history", "activity", "log"], "file-text"),
];

/**
 * Context-aware actions. Pure factory: no side effects. Each action is a
 * fire-and-forget callback; the palette closes itself after invocation.
 */
export function buildActionCommands(ctx: BuildContext): Command[] {
  const commands: Command[] = [
    {
      id: "action.project.create",
      title: "Create Project",
      group: "Actions",
      icon: "folder-plus",
      keywords: ["new", "add"],
      action: ({ router }) => router?.push("/projects?new=1"),
    },
    {
      id: "action.target.upload",
      title: "Upload Target",
      group: "Actions",
      icon: "upload",
      keywords: ["new", "pdb", "structure", "add"],
      action: ({ router }) => router?.push("/targets?upload=1"),
    },
    {
      id: "action.key.create",
      title: "Create API Key",
      group: "Actions",
      icon: "key-round",
      keywords: ["new", "token", "api"],
      action: ({ router }) => router?.push("/settings/keys?new=1"),
    },
    {
      id: "action.member.invite",
      title: "Invite Member",
      group: "Actions",
      icon: "user-plus",
      keywords: ["team", "add", "invite"],
      action: ({ router }) => router?.push("/settings/members?invite=1"),
    },
  ];

  if (ctx.currentProjectId) {
    commands.push({
      id: "action.job.submit",
      title: "Submit Job",
      group: "Actions",
      icon: "play",
      keywords: ["run", "execute", "new"],
      subtitle: `in project ${ctx.currentProjectId}`,
      action: ({ router }) =>
        router?.push(`/projects/${ctx.currentProjectId}/jobs/new`),
    });
  }

  return commands;
}

/**
 * Convenience: every static command the palette knows about at the moment
 * the palette is opened. Used as the idle list (query === "").
 */
export function allStaticCommands(ctx: BuildContext = {}): Command[] {
  return [...navigationCommands, ...buildActionCommands(ctx)];
}
