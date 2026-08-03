import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { beginFeishuInstall, pollFeishuInstall, type FeishuInstallSession } from "@/lib/feishuApi";

export const feishuInstallQueryKey = ["feishu-install"] as const;

/** Begin a QR/device-flow installation. */
export function useFeishuInstall() {
  const queryClient = useQueryClient();
  return useMutation<FeishuInstallSession, Error, void>({
    mutationKey: feishuInstallQueryKey,
    mutationFn: beginFeishuInstall,
    onSuccess: (session) => {
      queryClient.setQueryData([...feishuInstallQueryKey, session.session], session);
    },
  });
}

/** Poll an installation session. Disabled until a session id is available. */
export function useFeishuInstallStatus(session: FeishuInstallSession | null, enabled = true) {
  const intervalMs = Math.max(session?.interval ?? 5, 1) * 1_000;
  return useQuery({
    queryKey:
      session === null ? feishuInstallQueryKey : [...feishuInstallQueryKey, session.session],
    queryFn: async () => ({
      ...(session as FeishuInstallSession),
      ...(await pollFeishuInstall((session as FeishuInstallSession).session)),
    }),
    enabled: enabled && session !== null,
    initialData: session ?? undefined,
    staleTime: intervalMs,
    refetchInterval: (query) => {
      if (query.state.data?.status !== "pending") return false;
      const interval = query.state.data.interval ?? session?.interval;
      return typeof interval === "number" && interval > 0 ? interval * 1_000 : intervalMs;
    },
  });
}
