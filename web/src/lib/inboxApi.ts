import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { authenticatedFetch } from "./identity";

export type PersistentInboxKind =
  | "approval_required"
  | "session_completed"
  | "session_failed"
  | "task_waiting"
  | "task_succeeded"
  | "task_failed"
  | "task_cancelled"
  | "task_completed";

export interface PersistentInboxItem {
  id: string;
  object: "inbox_item";
  kind: PersistentInboxKind;
  work_item_id: string | null;
  work_item_run_id: string | null;
  session_id: string | null;
  source_id: string | null;
  message: string | null;
  target_url: string;
  action_required: boolean;
  created_at: number;
  updated_at: number | null;
  read_at: number | null;
  resolved_at: number | null;
}

export interface PersistentInboxList {
  object: "list";
  data: PersistentInboxItem[];
  unread_count: number;
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  const response = await authenticatedFetch(path, init);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response;
}

export async function listPersistentInboxItems(): Promise<PersistentInboxList> {
  return (await (await request("/v1/inbox-items")).json()) as PersistentInboxList;
}

export async function setPersistentInboxItemRead(
  itemId: string,
  read: boolean,
): Promise<PersistentInboxItem> {
  return (await (
    await request(`/v1/inbox-items/${encodeURIComponent(itemId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ read }),
    })
  ).json()) as PersistentInboxItem;
}

export async function markAllPersistentInboxItemsRead(): Promise<{ updated: number }> {
  return (await (await request("/v1/inbox-items/read-all", { method: "POST" })).json()) as {
    updated: number;
  };
}

export function usePersistentInboxItems() {
  return useQuery({
    queryKey: ["inbox-items"],
    queryFn: listPersistentInboxItems,
    refetchInterval: 30_000,
  });
}

export function useSetPersistentInboxItemRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ itemId, read }: { itemId: string; read: boolean }) =>
      setPersistentInboxItemRead(itemId, read),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["inbox-items"] }),
  });
}

export function useMarkAllPersistentInboxItemsRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: markAllPersistentInboxItemsRead,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["inbox-items"] }),
  });
}
