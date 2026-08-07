export function isPermissionDenied(error: unknown): boolean {
  if (typeof error === "object" && error !== null && "status" in error) {
    const status = (error as { status?: unknown }).status;
    if (status === 401 || status === 403) return true;
  }
  return (
    error instanceof Error &&
    /(^|\s)(401|403)(\s|$)|forbidden|permission denied|not authorized/i.test(error.message)
  );
}
