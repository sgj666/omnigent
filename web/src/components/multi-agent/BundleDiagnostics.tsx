import { useTranslation } from "react-i18next";
import { CircleAlertIcon } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import type { BundleDiagnostic } from "@/lib/multiAgentApi";

export function BundleDiagnostics({ diagnostics }: { diagnostics: BundleDiagnostic[] }) {
  const { t } = useTranslation("agents", { keyPrefix: "multiAgent" });
  if (diagnostics.length === 0) return null;
  return (
    <section className="space-y-2" aria-label={t("diagnostics.title")}>
      {diagnostics.map((diagnostic) => {
        const location = [
          diagnostic.file,
          diagnostic.line == null ? null : `${diagnostic.line}:${diagnostic.column ?? 1}`,
        ]
          .filter(Boolean)
          .join(":");
        return (
          <Alert
            key={JSON.stringify(diagnostic)}
            variant={diagnostic.severity === "error" ? "destructive" : "default"}
          >
            <CircleAlertIcon />
            <AlertTitle>
              {location}
              {diagnostic.path ? ` · ${diagnostic.path}` : ""}
            </AlertTitle>
            <AlertDescription>{diagnostic.message}</AlertDescription>
          </Alert>
        );
      })}
    </section>
  );
}
