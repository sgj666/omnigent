import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { AgentProfileList, type DraftMember } from "./AgentProfileList";
import type { TeamMember } from "@/lib/teamsApi";

export interface TeamFormValues {
  name: string;
  members: DraftMember[];
  workspaceId: string;
  executionMode: "auto" | "cautious" | "readonly";
}

export function validateTeamForm(values: Pick<TeamFormValues, "name" | "members">): string[] {
  const errors: string[] = [];
  if (!values.name.trim()) errors.push("Team name is required");
  if (values.members.filter((member) => member.role === "coordinator").length !== 1) {
    errors.push("A team must have exactly one coordinator");
  }
  const ids = values.members.map((member) => member.id.trim());
  if (ids.some((id) => !id) || new Set(ids).size !== ids.length) errors.push("Profile ids must be unique");
  if (values.members.some((member) => !Number.isInteger(member.concurrency) || (member.concurrency ?? 0) <= 0)) {
    errors.push("Concurrency must be a positive integer");
  }
  return errors;
}

interface TeamFormProps {
  initial?: Partial<TeamFormValues>;
  workspaces?: { id: string; root_path: string }[];
  onSubmit: (values: TeamFormValues) => void | Promise<void>;
  submitting?: boolean;
}

const defaultMember = (role: TeamMember["role"], id: string): DraftMember => ({
  id,
  name: role === "coordinator" ? "Coordinator" : "Worker",
  role,
  harness: "",
  capabilities: [],
  concurrency: 1,
  pairing: {},
  surface: {},
});

export function TeamForm({ initial, workspaces = [], onSubmit, submitting = false }: TeamFormProps) {
  const [name, setName] = useState(initial?.name ?? "");
  const [members, setMembers] = useState<DraftMember[]>(initial?.members ?? [defaultMember("coordinator", "coordinator")]);
  const [workspaceId, setWorkspaceId] = useState(initial?.workspaceId ?? "");
  const [executionMode, setExecutionMode] = useState<TeamFormValues["executionMode"]>(initial?.executionMode ?? "auto");
  const [errors, setErrors] = useState<string[]>([]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const values = { name, members, workspaceId, executionMode };
    const nextErrors = validateTeamForm(values);
    setErrors(nextErrors);
    if (nextErrors.length === 0) await onSubmit(values);
  }

  return (
    <form className="space-y-5" onSubmit={submit}>
      {errors.length > 0 && <div role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">{errors.map((error) => <div key={error}>{error}</div>)}</div>}
      <label className="block text-sm font-medium">Team name
        <Input aria-label="Team name" value={name} onChange={(event) => setName(event.target.value)} />
      </label>
      <label className="block text-sm font-medium">Coordinator
        <select
          aria-label="Coordinator"
          className="mt-1 h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm"
          value={members.find((member) => member.role === "coordinator")?.id ?? ""}
          onChange={(event) => setMembers(members.map((member) => ({ ...member, role: member.id === event.target.value ? "coordinator" : "worker" })))}
        >
          {members.map((member) => <option key={member.id} value={member.id}>{member.name || member.id}</option>)}
        </select>
      </label>
      <AgentProfileList members={members} onChange={setMembers} />
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm font-medium">Workspace
          <Select value={workspaceId || "none"} onValueChange={(value) => setWorkspaceId(value === "none" ? "" : value)}>
            <SelectTrigger aria-label="Workspace"><SelectValue placeholder="Select workspace" /></SelectTrigger>
            <SelectContent><SelectItem value="none">No workspace selected</SelectItem>{workspaces.map((workspace) => <SelectItem key={workspace.id} value={workspace.id}>{workspace.id}</SelectItem>)}</SelectContent>
          </Select>
        </label>
        <label className="text-sm font-medium">Execution mode
          <Select value={executionMode} onValueChange={(value) => setExecutionMode(value as TeamFormValues["executionMode"])}>
            <SelectTrigger aria-label="Execution mode"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="auto">Auto</SelectItem><SelectItem value="cautious">Cautious</SelectItem><SelectItem value="readonly">Read-only analysis</SelectItem></SelectContent>
          </Select>
        </label>
      </div>
      <Button type="submit" disabled={submitting}>{submitting ? "Saving…" : "Save team"}</Button>
    </form>
  );
}
