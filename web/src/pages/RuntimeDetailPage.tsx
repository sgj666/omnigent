import { useQuery } from "@tanstack/react-query";
import { LaptopIcon, ServerIcon, UserIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { iconForAgent } from "@/components/AgentCard";
import { PageBackButton } from "@/components/PageBackButton";
import { PageScroll } from "@/components/PageScroll";
import { RuntimeMark } from "@/components/RuntimeMark";
import { CollectionState, StatusBadge } from "@/components/collection";
import { useAvailableAgents } from "@/hooks/useAvailableAgents";
import { getHost } from "@/hooks/useHosts";
import { installedRuntimes, runtimeIdForHarness } from "@/lib/runtimeHarnesses";
import { useParams } from "@/lib/routing";

export function RuntimeDetailPage() {
  const { t } = useTranslation("management");
  const { hostId } = useParams<{ hostId: string }>();
  const host = useQuery({
    queryKey: ["hosts", "detail", hostId],
    queryFn: () => getHost(hostId as string),
    enabled: Boolean(hostId),
    retry: false,
    refetchInterval: 30_000,
  });
  const agents = useAvailableAgents();

  if (host.isLoading) {
    return (
      <PageScroll contentClassName="px-6" maxWidthClassName="max-w-6xl">
        <CollectionState state="loading" title={t("runtime.detail.loading")} />
      </PageScroll>
    );
  }

  if (host.isError || !host.data) {
    return (
      <PageScroll contentClassName="px-6" maxWidthClassName="max-w-6xl">
        <PageBackButton fallbackTo="/runtime" className="mb-4">
          {t("runtime.detail.back")}
        </PageBackButton>
        <CollectionState state="error" title={t("runtime.detail.notFound")} />
      </PageScroll>
    );
  }

  const value = host.data;
  const runtimes = installedRuntimes(value.configured_harnesses);

  return (
    <PageScroll
      contentClassName="px-6"
      maxWidthClassName="max-w-6xl"
      data-testid="runtime-detail-page"
    >
      <PageBackButton fallbackTo="/runtime" className="mb-4">
        {t("runtime.detail.back")}
      </PageBackButton>

      <div className="flex min-w-0 items-start gap-3">
        <span className="flex size-11 shrink-0 items-center justify-center rounded-xl border bg-card">
          <LaptopIcon className="size-5 text-muted-foreground" />
        </span>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="truncate text-2xl font-semibold tracking-tight">{value.name}</h1>
            <StatusBadge tone={value.status === "online" ? "success" : "neutral"}>
              {t(`runtime.status.${value.status}`)}
            </StatusBadge>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("runtime.detail.installedSummary", { count: runtimes.length })}
          </p>
        </div>
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <section className="min-w-0 rounded-xl border bg-card">
          <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
            <div>
              <h2 className="text-sm font-semibold">{t("runtime.detail.installedTitle")}</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                {t("runtime.detail.installedDescription")}
              </p>
            </div>
            <StatusBadge tone={runtimes.length > 0 ? "success" : "neutral"}>
              {t("runtime.installedCount", { count: runtimes.length })}
            </StatusBadge>
          </div>
          {runtimes.length === 0 ? (
            <CollectionState
              state="empty"
              title={t("runtime.noInstalledRuntimes")}
              description={t("runtime.detail.noInstalledDescription")}
              className="m-4"
            />
          ) : (
            <div className="divide-y">
              {runtimes.map((runtime) => {
                const linkedAgents = (agents.data ?? []).filter(
                  (agent) => runtimeIdForHarness(agent.harness) === runtime.id,
                );
                return (
                  <div
                    key={runtime.id}
                    className="grid gap-3 px-4 py-3 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center"
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <RuntimeMark runtimeId={runtime.id} />
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold">{runtime.displayName}</p>
                        <p className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground">
                          {runtime.id}
                        </p>
                      </div>
                    </div>

                    <div className="flex min-w-0 items-center gap-2">
                      {linkedAgents.length > 0 ? (
                        <>
                          <div className="flex -space-x-1.5">
                            {linkedAgents.slice(0, 4).map((agent) => {
                              const Icon = iconForAgent(agent);
                              return (
                                <span
                                  key={agent.id}
                                  title={agent.display_name}
                                  className="flex size-7 items-center justify-center rounded-full border bg-background"
                                >
                                  <Icon className="size-3.5" />
                                </span>
                              );
                            })}
                          </div>
                          <span className="truncate text-xs text-muted-foreground">
                            {t("runtime.detail.agentCount", { count: linkedAgents.length })}
                          </span>
                        </>
                      ) : (
                        <span className="text-xs text-muted-foreground">
                          {t("runtime.detail.noAgents")}
                        </span>
                      )}
                    </div>

                    <div className="flex items-center gap-2 sm:justify-end">
                      <StatusBadge tone="neutral">
                        {t(`runtime.detail.kinds.${runtime.kind}`)}
                      </StatusBadge>
                      <StatusBadge tone="success">{t("runtime.status.ready")}</StatusBadge>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        <aside className="space-y-4">
          <section className="rounded-xl border bg-card">
            <div className="border-b px-4 py-3">
              <h2 className="text-sm font-semibold">{t("runtime.detail.machineTitle")}</h2>
            </div>
            <dl className="divide-y text-sm">
              <Fact
                icon={<ServerIcon />}
                label={t("runtime.detail.type")}
                value={t(value.sandbox_provider ? "runtime.types.managed" : "runtime.types.local")}
              />
              <Fact icon={<UserIcon />} label={t("runtime.detail.owner")} value={value.owner} />
              <Fact
                icon={<LaptopIcon />}
                label={t("runtime.detail.provider")}
                value={value.sandbox_provider ?? t("runtime.detail.localHost")}
              />
            </dl>
          </section>
          <section className="rounded-xl border bg-card p-4">
            <h2 className="text-sm font-semibold">{t("runtime.detail.technicalTitle")}</h2>
            <dl className="mt-3">
              <dt className="text-xs text-muted-foreground">{t("runtime.detail.hostId")}</dt>
              <dd className="mt-1 break-all font-mono text-xs">{value.host_id}</dd>
            </dl>
          </section>
        </aside>
      </div>
    </PageScroll>
  );
}

function Fact({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex gap-3 px-4 py-3">
      <span className="mt-0.5 text-muted-foreground [&_svg]:size-4">{icon}</span>
      <div className="min-w-0">
        <dt className="text-xs text-muted-foreground">{label}</dt>
        <dd className="mt-0.5 truncate">{value}</dd>
      </div>
    </div>
  );
}
