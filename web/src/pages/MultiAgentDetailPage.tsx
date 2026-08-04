import { ArrowLeftIcon } from "lucide-react";
import { PageScroll } from "@/components/PageScroll";
import { Button } from "@/components/ui/button";
import { Link, useParams } from "@/lib/routing";

export function MultiAgentDetailPage() {
  const { agentId } = useParams<{ agentId: string }>();
  const isNew = agentId == null || agentId === "new";

  return (
    <PageScroll contentClassName="px-6 py-8" extraBottom="2.5rem" maxWidthClassName="max-w-5xl">
      <div className="space-y-4">
        <Button asChild variant="ghost" size="sm" className="-ml-3">
          <Link to="/multi-agents" aria-label="Back to Multi-Agent">
            <ArrowLeftIcon />
            Back to Multi-Agent
          </Link>
        </Button>
        <div>
          <h1 className="text-2xl font-semibold">{isNew ? "New Multi-Agent" : "Multi-Agent"}</h1>
          {!isNew && <p className="mt-1 font-mono text-sm text-muted-foreground">{agentId}</p>}
        </div>
      </div>
    </PageScroll>
  );
}
