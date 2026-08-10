export const APP_ROUTES = {
  chat: "/",
  inbox: "/inbox",
  automations: "/automations",
  settings: "/settings",
} as const;

export type GlobalNavigationId = keyof typeof APP_ROUTES;

export interface GlobalNavigationItem {
  id: GlobalNavigationId;
  label: string;
  href: (typeof APP_ROUTES)[GlobalNavigationId];
}

export const GLOBAL_NAVIGATION: readonly GlobalNavigationItem[] = [
  { id: "chat", label: "Chat", href: APP_ROUTES.chat },
  { id: "inbox", label: "Inbox", href: APP_ROUTES.inbox },
  { id: "automations", label: "Automations", href: APP_ROUTES.automations },
  { id: "settings", label: "Settings", href: APP_ROUTES.settings },
];

export function getGlobalNavigationItem(id: GlobalNavigationId): GlobalNavigationItem {
  const item = GLOBAL_NAVIGATION.find((candidate) => candidate.id === id);
  if (!item) throw new Error(`Missing global navigation item: ${id}`);
  return item;
}
