import { PlusIcon } from "lucide-react";
import { PageScroll } from "@/components/PageScroll";
import { Button } from "@/components/ui/button";
import { Link } from "@/lib/routing";

export function MultiAgentsPage() {
  return (
    <PageScroll contentClassName="px-6 py-8" extraBottom="2.5rem" maxWidthClassName="max-w-5xl">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">Multi-Agent</h1>
        <Button asChild>
          <Link to="/multi-agents/new">
            <PlusIcon />
            New Multi-Agent
          </Link>
        </Button>
      </div>
    </PageScroll>
  );
}
