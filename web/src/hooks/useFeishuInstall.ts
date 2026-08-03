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
      void queryClient.invalidateQueries({ queryKey: feishuInstallQueryKey });
    },
  });
}

/** Poll an installation session. Disabled until a session id is available. */
export function useFeishuInstallStatus(session: string | null, enabled = true) {
  return useQuery({
    queryKey: session === null ? feishuInstallQueryKey : [...feishuInstallQueryKey, session],
    queryFn: () => pollFeishuInstall(session as string),
    enabled: enabled && session !== null,
    refetchInterval: (query) => (query.state.data?.status === "pending" ? 2_000 : false),
  });
}

