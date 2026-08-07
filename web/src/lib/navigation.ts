export const APP_ROUTES = {
  chat: "/",
  tasks: "/tasks",
  automations: "/automations",
  inbox: "/inbox",
  projects: "/projects",
  usage: "/usage",
  runtime: "/runtime",
  multiAgents: "/multi-agents",
  skills: "/skills",
  settings: "/settings",
} as const;

export type GlobalNavigationId = keyof typeof APP_ROUTES;

export interface GlobalNavigationItem {
  id: GlobalNavigationId;
  labelKey: `shell.${string}`;
  href: (typeof APP_ROUTES)[GlobalNavigationId];
}

export const GLOBAL_NAVIGATION: readonly GlobalNavigationItem[] = [
  { id: "chat", labelKey: "shell.newSession", href: APP_ROUTES.chat },
  { id: "tasks", labelKey: "shell.tasks", href: APP_ROUTES.tasks },
  {
    id: "automations",
    labelKey: "shell.automations",
    href: APP_ROUTES.automations,
  },
  { id: "inbox", labelKey: "shell.inbox", href: APP_ROUTES.inbox },
  { id: "projects", labelKey: "shell.projects", href: APP_ROUTES.projects },
  {
    id: "multiAgents",
    labelKey: "shell.multiAgents",
    href: APP_ROUTES.multiAgents,
  },
  { id: "skills", labelKey: "shell.skills", href: APP_ROUTES.skills },
  { id: "runtime", labelKey: "shell.runtime", href: APP_ROUTES.runtime },
  { id: "usage", labelKey: "shell.usage", href: APP_ROUTES.usage },
  { id: "settings", labelKey: "shell.settings", href: APP_ROUTES.settings },
];

export function getGlobalNavigationItem(id: GlobalNavigationId): GlobalNavigationItem {
  const item = GLOBAL_NAVIGATION.find((candidate) => candidate.id === id);
  if (!item) throw new Error(`Missing global navigation item: ${id}`);
  return item;
}
