/**
 * Command registry for the dashboard Cmd+K palette.
 *
 * Quick actions are registered statically here; remote results (projects,
 * jobs, designs, people) are merged in at search time inside
 * `CommandPalette`. External callers can extend the registry with
 * `registerCommand`: useful for page-scoped actions that only exist
 * while a particular route is mounted.
 */

export type CommandKind = 'action' | 'project' | 'job' | 'design' | 'person';

export interface CommandActionContext {
  router: { push: (href: string) => void };
  signOut: () => void | Promise<void>;
  currentProjectSlug?: string;
}

export interface Command {
  id: string;
  title: string;
  subtitle?: string | null;
  group: 'Actions' | 'Projects' | 'Jobs' | 'Designs' | 'People' | 'Recent';
  kind: CommandKind;
  /** Optional pre-formatted shortcut hint shown on the right (e.g. "G P"). */
  shortcut?: string;
  keywords?: string[];
  action: (ctx: CommandActionContext) => void | Promise<void>;
}

const customCommands: Command[] = [];

export function registerCommand(cmd: Command): () => void {
  customCommands.push(cmd);
  return () => {
    const idx = customCommands.findIndex((c) => c.id === cmd.id);
    if (idx >= 0) customCommands.splice(idx, 1);
  };
}

export function clearCustomCommands(): void {
  customCommands.length = 0;
}

/** Static "quick action" catalog. Sensitive to the active project context. */
export function quickActions(opts: { currentProjectSlug?: string } = {}): Command[] {
  const inProject = Boolean(opts.currentProjectSlug);
  const actions: Command[] = [
    {
      id: 'action.new-project',
      title: 'New project',
      subtitle: 'Create a new design project',
      group: 'Actions',
      kind: 'action',
      shortcut: 'G N',
      keywords: ['create', 'add', 'project'],
      action: ({ router }) => router.push('/projects/new'),
    },
    {
      id: 'action.submit-job',
      title: inProject
        ? `Submit job in ${opts.currentProjectSlug}`
        : 'Submit a new job',
      subtitle: 'Open the job submission form',
      group: 'Actions',
      kind: 'action',
      keywords: ['run', 'job', 'submit', 'design'],
      action: ({ router, currentProjectSlug }) => {
        const slug = currentProjectSlug ?? opts.currentProjectSlug;
        router.push(slug ? `/projects/${slug}/jobs/new` : '/jobs/new');
      },
    },
    {
      id: 'action.switch-org',
      title: 'Switch org',
      subtitle: 'Choose a different organization',
      group: 'Actions',
      kind: 'action',
      keywords: ['organization', 'workspace', 'tenant'],
      action: ({ router }) => router.push('/app/settings/team'),
    },
    {
      id: 'action.settings',
      title: 'Settings',
      group: 'Actions',
      kind: 'action',
      shortcut: 'G S',
      keywords: ['preferences', 'profile', 'settings'],
      action: ({ router }) => router.push('/app/settings'),
    },
    {
      id: 'action.sign-out',
      title: 'Sign out',
      subtitle: 'End the current session',
      group: 'Actions',
      kind: 'action',
      keywords: ['logout', 'leave'],
      action: async ({ signOut }) => {
        if (typeof window !== 'undefined') {
          const ok = window.confirm('Sign out of Paper Crane?');
          if (!ok) return;
        }
        await signOut();
      },
    },
  ];
  return [...actions, ...customCommands];
}

/** Naive substring scorer: good enough for short action lists. */
export function scoreCommand(cmd: Command, query: string): number {
  if (!query) return 0;
  const q = query.toLowerCase();
  const haystack = [
    cmd.title,
    cmd.subtitle ?? '',
    ...(cmd.keywords ?? []),
  ]
    .join(' ')
    .toLowerCase();
  if (haystack.includes(q)) {
    return cmd.title.toLowerCase().startsWith(q) ? 1 : 0.5;
  }
  // Fuzzy fallback: every char of query must appear in order.
  let i = 0;
  for (const ch of haystack) {
    if (ch === q[i]) i++;
    if (i === q.length) return 0.25;
  }
  return -1;
}
