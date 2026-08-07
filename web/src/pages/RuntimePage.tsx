import { useMemo } from "react";
import { ChevronRightIcon, LaptopIcon, SearchIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { PageScroll } from "@/components/PageScroll";
import { RuntimeMark } from "@/components/RuntimeMark";
import {
  CollectionPageHeader,
  CollectionState,
  CollectionToolbar,
  SegmentedFilter,
  StatusBadge,
} from "@/components/collection";
import { Input } from "@/components/ui/input";
import { useHosts } from "@/hooks/useHosts";
import { isPermissionDenied } from "@/lib/httpErrors";
import { installedRuntimes } from "@/lib/runtimeHarnesses";
import { Link, useSearchParams } from "@/lib/routing";

type RuntimeFilter = "all" | "online" | "offline";

export function RuntimePage() {
  const { t, i18n } = useTranslation("management");
  const { t: commonT } = useTranslation("common");
  const [params, setParams] = useSearchParams();
  const hosts = useHosts({ includeSandbox: true });
  const search = params.get("q") ?? "";
  const rawFilter = params.get("status");
  const filter: RuntimeFilter =
    rawFilter === "online" || rawFilter === "offline" ? rawFilter : "all";

  function updateParam(key: string, value: string, defaultValue = "") {
    const next = new URLSearchParams(params);
    if (!value || value === defaultValue) next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
  }

  const machines = useMemo(() => hosts.data ?? [], [hosts.data]);
  const runtimesByHost = useMemo(
    () =>
      new Map(machines.map((host) => [host.host_id, installedRuntimes(host.configured_harnesses)])),
    [machines],
  );
  const filtered = useMemo(() => {
    const query = search.trim().toLocaleLowerCase(i18n.language);
    return machines.filter((host) => {
      if (filter !== "all" && host.status !== filter) return false;
      const installed = runtimesByHost.get(host.host_id) ?? [];
      const haystack = [
        host.name,
        host.host_id,
        host.sandbox_provider ?? "",
        ...installed.flatMap((runtime) => [runtime.id, runtime.displayName]),
      ]
        .join(" ")
        .toLocaleLowerCase(i18n.language);
      return !query || haystack.includes(query);
    });
  }, [filter, i18n.language, machines, runtimesByHost, search]);
  const availableRuntimeCount = new Set(
    machines.flatMap((host) =>
      (runtimesByHost.get(host.host_id) ?? []).map((runtime) => runtime.id),
    ),
  ).size;
  const onlineMachineCount = machines.filter((host) => host.status === "online").length;
  const loading = hosts.isLoading;
  const failed = hosts.isError;
  const permissionDenied = isPermissionDenied(hosts.error);

  return (
    <PageScroll contentClassName="px-6" maxWidthClassName="max-w-6xl" data-testid="runtime-page">
      <CollectionPageHeader
        title={t("runtime.title")}
        description={t("runtime.description")}
        actions={
          <div className="text-right">
            <StatusBadge tone={onlineMachineCount > 0 ? "success" : "neutral"}>
              {t("runtime.onlineMachines", { count: onlineMachineCount })}
            </StatusBadge>
            <p className="mt-1 text-xs text-muted-foreground">
              {t("runtime.availableRuntimeCount", { count: availableRuntimeCount })}
            </p>
          </div>
        }
      />
      <CollectionToolbar className="mt-6">
        <div className="relative min-w-56 flex-1 sm:max-w-sm">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            aria-label={t("common.search")}
            value={search}
            onChange={(event) => updateParam("q", event.target.value)}
            placeholder={t("runtime.searchPlaceholder")}
            className="pl-9"
          />
        </div>
        <SegmentedFilter<RuntimeFilter>
          label={t("runtime.filterLabel")}
          value={filter}
          onValueChange={(value) => updateParam("status", value, "all")}
          options={[
            { value: "all", label: t("runtime.filters.all"), count: machines.length },
            {
              value: "online",
              label: t("runtime.filters.online"),
              count: machines.filter((host) => host.status === "online").length,
            },
            {
              value: "offline",
              label: t("runtime.filters.offline"),
              count: machines.filter((host) => host.status === "offline").length,
            },
          ]}
        />
      </CollectionToolbar>
      <div className="mt-4">
        {loading ? (
          <CollectionState state="loading" title={t("runtime.loading")} />
        ) : failed ? (
          <CollectionState
            state="error"
            title={permissionDenied ? commonT("collection.permissionDenied") : t("runtime.error")}
            description={
              permissionDenied ? commonT("collection.permissionDeniedDescription") : undefined
            }
            action={
              <button
                type="button"
                className="text-sm font-medium text-primary"
                onClick={() => void hosts.refetch()}
              >
                {t("common.retry")}
              </button>
            }
          />
        ) : machines.length === 0 ? (
          <CollectionState
            state="empty"
            title={t("runtime.empty")}
            description={t("runtime.emptyDescription")}
          />
        ) : filtered.length === 0 ? (
          <CollectionState state="empty" title={t("runtime.noMatches")} />
        ) : (
          <div className="space-y-3">
            {filtered.map((host) => {
              const installed = runtimesByHost.get(host.host_id) ?? [];
              return (
                <Link
                  key={host.host_id}
                  to={`/runtime/${encodeURIComponent(host.host_id)}`}
                  aria-label={t("runtime.openDetails", { name: host.name })}
                  className="group grid gap-4 rounded-2xl border bg-card p-4 transition-[border-color,background-color,box-shadow] hover:border-border-strong hover:bg-muted/20 hover:shadow-sm md:grid-cols-[minmax(240px,1fr)_auto_minmax(280px,1.2fr)_auto] md:items-center"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="relative flex size-11 shrink-0 items-center justify-center rounded-xl border bg-background">
                      <LaptopIcon className="size-5 text-muted-foreground" />
                      <span
                        className={`absolute right-0.5 bottom-0.5 size-2.5 rounded-full border-2 border-background ${host.status === "online" ? "bg-chart-3" : "bg-muted-foreground"}`}
                      />
                    </span>
                    <div className="min-w-0">
                      <div className="flex min-w-0 items-center gap-2">
                        <h2 className="truncate font-semibold">{host.name}</h2>
                        <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                          {t(
                            host.sandbox_provider ? "runtime.types.managed" : "runtime.types.local",
                          )}
                        </span>
                      </div>
                      <p className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground">
                        {host.host_id}
                      </p>
                    </div>
                  </div>

                  <StatusBadge tone={host.status === "online" ? "success" : "neutral"}>
                    {t(`runtime.status.${host.status}`)}
                  </StatusBadge>

                  <div className="min-w-0">
                    <p className="text-xs text-muted-foreground">
                      {t("runtime.installedCount", { count: installed.length })}
                    </p>
                    {installed.length === 0 ? (
                      <p className="mt-1 text-sm text-muted-foreground">
                        {t("runtime.noInstalledRuntimes")}
                      </p>
                    ) : (
                      <div className="mt-2 flex min-w-0 items-center gap-3">
                        <div className="flex shrink-0 -space-x-2">
                          {installed.slice(0, 5).map((runtime) => (
                            <RuntimeMark
                              key={runtime.id}
                              runtimeId={runtime.id}
                              className="size-8 rounded-lg [&_svg]:size-4"
                            />
                          ))}
                          {installed.length > 5 ? (
                            <span className="relative flex size-8 items-center justify-center rounded-lg border bg-muted text-[10px] font-medium">
                              +{installed.length - 5}
                            </span>
                          ) : null}
                        </div>
                        <p className="truncate text-sm">
                          {installed
                            .slice(0, 3)
                            .map((runtime) => runtime.displayName)
                            .join("、")}
                          {installed.length > 3 ? ` +${installed.length - 3}` : ""}
                        </p>
                      </div>
                    )}
                  </div>

                  <ChevronRightIcon className="hidden size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5 md:block" />
                </Link>
              );
            })}
          </div>
        )}
      </div>
    </PageScroll>
  );
}
