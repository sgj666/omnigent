import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useFeishuInstall, useFeishuInstallStatus } from "@/hooks/useFeishuInstall";
import type { FeishuInstallSession } from "@/lib/feishuApi";

interface FeishuPairingPanelProps {
  pairing?: Record<string, unknown>;
  onChange?: (pairing: Record<string, unknown>) => void;
}

export function FeishuPairingPanel({ pairing, onChange }: FeishuPairingPanelProps) {
  const [session, setSession] = useState<FeishuInstallSession | null>(null);
  const notifiedSession = useRef<string | null>(null);
  const begin = useFeishuInstall();
  const status = useFeishuInstallStatus(session, session?.status === "pending");
  const current = status.data ?? session;

  useEffect(() => {
    if (status.data) {
      setSession(status.data);
      if (status.data.status === "active" && notifiedSession.current !== status.data.session) {
        notifiedSession.current = status.data.session;
        onChange?.({ ...(pairing ?? {}), installation: status.data });
      }
    }
  }, [onChange, pairing, status.data]);

  async function connect() {
    const next = await begin.mutateAsync();
    setSession(next);
  }

  return (
    <section className="space-y-3 rounded-xl border p-4" aria-labelledby="feishu-pairing-title">
      <div className="flex items-center justify-between">
        <div>
          <h2 id="feishu-pairing-title" className="font-medium">
            Agent Pairing
          </h2>
          <p className="text-sm text-muted-foreground">
            Connect a Feishu identity for notifications and display.
          </p>
        </div>
        <Badge variant="outline">{current?.status ?? "not connected"}</Badge>
      </div>
      {current?.verification_uri_complete && current.status === "pending" && (
        <div className="space-y-2">
          <p className="text-sm font-medium">扫码绑定飞书智能体/机器人</p>
          <img
            className="size-48 rounded border bg-white p-2"
            alt="Feishu QR code"
            src={`https://api.qrserver.com/v1/create-qr-code/?size=240x240&data=${encodeURIComponent(current.verification_uri_complete)}`}
          />
          <a
            className="text-sm text-primary hover:underline"
            href={current.verification_uri_complete}
            target="_blank"
            rel="noreferrer"
          >
            Open verification link
          </a>
          <p className="text-xs text-muted-foreground">Waiting for scan…</p>
        </div>
      )}
      {current?.status === "active" && (
        <p className="text-sm">
          Connected
          {typeof current.bot === "object" && current.bot !== null && "name" in current.bot
            ? ` as ${(current.bot as { name?: string }).name ?? "Feishu bot"}`
            : " to Feishu"}
          .
        </p>
      )}
      {current?.status === "expired" && (
        <p role="alert" className="text-sm text-destructive">
          This pairing session expired. Start a new one.
        </p>
      )}
      {begin.isError && (
        <p role="alert" className="text-sm text-destructive">
          {begin.error.message}
        </p>
      )}
      <Button type="button" onClick={connect} disabled={begin.isPending}>
        {begin.isPending ? "Connecting…" : "连接飞书"}
      </Button>
    </section>
  );
}
