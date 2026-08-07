export const projectQueryKeys = {
  all: ["projects"] as const,
  archivedNames: ["archived-project-names"] as const,
  sessionsRoot: ["project-sessions"] as const,
  sessions: (name: string) => ["project-sessions", name] as const,
  configRoot: ["project-config"] as const,
  config: (id: string | null) => ["project-config", id] as const,
};
