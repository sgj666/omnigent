import { Link, useParams } from "@/lib/routing";
import { useTranslation } from "react-i18next";
import { PageScroll } from "@/components/PageScroll";
import { RunInspector } from "@/components/runs/RunInspector";
import { useRefreshRunEvaluation, useRun, useRunEvaluation } from "@/hooks/useRuns";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function RunInspectorPage() {
  const { t } = useTranslation("agents", { keyPrefix: "multiAgent.runInspector" });
  const { runId } = useParams<{ runId: string }>();
  const run = useRun(runId ?? null);
  const evaluation = useRunEvaluation(runId ?? null, Boolean(run.data));
  const refreshEvaluation = useRefreshRunEvaluation();

  if (!runId)
    return (
      <div role="alert" className="p-8 text-sm text-destructive">
        {t("idRequired")}
      </div>
    );
  if (run.isLoading)
    return (
      <div className="flex min-h-full items-center justify-center text-sm text-muted-foreground">
        {t("loading")}
      </div>
    );
  if (run.isError)
    return (
      <div role="alert" className="p-8 text-sm text-destructive">
        {t("loadError", { message: errorMessage(run.error) })}
      </div>
    );
  if (!run.data)
    return (
      <div role="alert" className="p-8 text-sm text-destructive">
        {t("notFound")}
      </div>
    );

  return (
    <PageScroll contentClassName="mx-auto w-full max-w-6xl px-6 py-8" extraBottom="2.5rem">
      <div className="mb-6 flex items-center gap-3">
        <Link to="/multi-agents" className="text-sm text-muted-foreground hover:underline">
          {t("back")}
        </Link>
        <h1 className="text-2xl font-semibold">{t("runTitle", { id: run.data.run.id })}</h1>
      </div>
      <RunInspector
        inspector={run.data}
        evaluation={evaluation.data}
        evaluationError={
          refreshEvaluation.isError
            ? errorMessage(refreshEvaluation.error)
            : evaluation.isError
              ? errorMessage(evaluation.error)
              : null
        }
        evaluationRefreshing={refreshEvaluation.isPending}
        onRefreshEvaluation={() => refreshEvaluation.mutate(run.data.run.id)}
      />
    </PageScroll>
  );
}

export default RunInspectorPage;
