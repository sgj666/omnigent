import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export interface BotSurfaceState {
  status?: "ready" | "partial" | "pending" | "failed" | string;
  reasons?: string[];
  top_entries?: string[];
  quick_commands?: string[];
}

interface BotSurfacePanelProps {
  surface?: BotSurfaceState | Record<string, unknown>;
  onReinitialize?: () => void | Promise<void>;
}

export function BotSurfacePanel({ surface = {}, onReinitialize }: BotSurfacePanelProps) {
  const [pending, setPending] = useState(false);
  const state = surface as BotSurfaceState;
  async function reinitialize() {
    if (!onReinitialize) return;
    setPending(true);
    try { await onReinitialize(); } finally { setPending(false); }
  }
  return (
    <section className="space-y-3 rounded-xl border p-4" aria-labelledby="bot-surface-title">
      <div className="flex items-center justify-between"><div><h2 id="bot-surface-title" className="font-medium">Bot Surface</h2><p className="text-sm text-muted-foreground">Fixed Feishu workspace entries and run actions.</p></div><Badge variant={state.status === "partial" ? "secondary" : "outline"}>{state.status ?? "not initialized"}</Badge></div>
      {state.status === "partial" && <div role="status" className="rounded-md bg-muted p-2 text-sm">Surface is partially initialized. {state.reasons?.join(" ") || "Some menu entries are unavailable; the interactive card fallback is active."}</div>}
      {state.status === "failed" && <div role="alert" className="text-sm text-destructive">Surface initialization failed.</div>}
      {state.top_entries && state.top_entries.length > 0 && <div><h3 className="text-xs font-medium uppercase text-muted-foreground">Top entries</h3><p className="text-sm">{state.top_entries.join(" · ")}</p></div>}
      {state.quick_commands && state.quick_commands.length > 0 && <div><h3 className="text-xs font-medium uppercase text-muted-foreground">Quick commands</h3><p className="text-sm">{state.quick_commands.join(" · ")}</p></div>}
      <Button type="button" variant="outline" onClick={reinitialize} disabled={pending}>{pending ? "Reinitializing…" : "Reinitialize workspace"}</Button>
    </section>
  );
}
