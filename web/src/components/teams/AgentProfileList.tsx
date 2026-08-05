import { PlusIcon, Trash2Icon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { TeamMember } from "@/lib/teamsApi";

export type DraftMember = TeamMember & {
  id: string;
  pairing: Record<string, unknown>;
  surface: Record<string, unknown>;
};

interface AgentProfileListProps {
  members: DraftMember[];
  onChange: (members: DraftMember[]) => void;
}

export function AgentProfileList({ members, onChange }: AgentProfileListProps) {
  const update = (index: number, patch: Partial<DraftMember>) =>
    onChange(members.map((member, i) => (i === index ? { ...member, ...patch } : member)));
  const remove = (index: number) => onChange(members.filter((_, i) => i !== index));
  const addWorker = () =>
    onChange([
      ...members,
      {
        id: `worker-${members.length + 1}`,
        name: "",
        role: "worker",
        harness: "",
        capabilities: [],
        concurrency: 1,
        pairing: {},
        surface: {},
      },
    ]);

  return (
    <div className="space-y-3" aria-label="Agent profiles">
      {members.map((member, index) => (
        <div key={member.id} className="rounded-lg border p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-medium">
              {member.role === "coordinator" ? "Coordinator" : "Worker"}
            </span>
            {member.role !== "coordinator" && (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Remove ${member.name || "worker"}`}
                onClick={() => remove(index)}
              >
                <Trash2Icon className="size-4" />
              </Button>
            )}
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="text-xs text-muted-foreground">
              Profile id
              <Input
                aria-label="Profile id"
                value={member.id}
                onChange={(event) => update(index, { id: event.target.value })}
              />
            </label>
            <label className="text-xs text-muted-foreground">
              Display name
              <Input
                aria-label="Display name"
                value={member.name}
                onChange={(event) => update(index, { name: event.target.value })}
              />
            </label>
            <label className="text-xs text-muted-foreground">
              Harness
              <Input
                aria-label="Harness"
                value={member.harness ?? ""}
                onChange={(event) => update(index, { harness: event.target.value })}
              />
            </label>
            <label className="text-xs text-muted-foreground">
              Concurrency
              <Input
                aria-label="Concurrency"
                type="number"
                min={1}
                value={member.concurrency ?? 1}
                onChange={(event) => update(index, { concurrency: Number(event.target.value) })}
              />
            </label>
            <label className="text-xs text-muted-foreground sm:col-span-2">
              Capabilities (comma separated)
              <Input
                aria-label="Capabilities"
                value={(member.capabilities ?? []).join(", ")}
                onChange={(event) =>
                  update(index, {
                    capabilities: event.target.value
                      .split(",")
                      .map((value) => value.trim())
                      .filter(Boolean),
                  })
                }
              />
            </label>
          </div>
        </div>
      ))}
      <Button type="button" variant="outline" onClick={addWorker}>
        <PlusIcon /> Add worker
      </Button>
    </div>
  );
}
