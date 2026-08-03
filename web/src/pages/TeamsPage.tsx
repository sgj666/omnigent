import { PlusIcon, UsersIcon } from "lucide-react";
import { Link } from "@/lib/routing";
import { PageScroll } from "@/components/PageScroll";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useTeams } from "@/hooks/useTeams";

export function TeamsPage() {
  const teams = useTeams();
  if (teams.isLoading) return <div className="flex min-h-full items-center justify-center text-sm text-muted-foreground">Loading teams…</div>;
  if (teams.isError) return <div role="alert" className="p-8 text-sm text-destructive">Could not load teams: {teams.error.message}</div>;
  return (
    <PageScroll contentClassName="mx-auto w-full max-w-5xl px-6 py-8" extraBottom="2.5rem">
      <div className="mb-6 flex items-center justify-between"><div><h1 className="text-2xl font-semibold">Teams</h1><p className="text-sm text-muted-foreground">Build coordinator-led agent teams and connect their Feishu surfaces.</p></div><Button asChild><Link to="/teams/new"><PlusIcon /> New team</Link></Button></div>
      {teams.data?.length ? <div className="grid gap-4 md:grid-cols-2">{teams.data.map((team) => <Link key={team.id} to={`/teams/${team.id}`} className="block"><Card className="h-full transition-colors hover:bg-muted/30"><CardHeader><CardTitle className="flex items-center justify-between gap-2"><span className="flex items-center gap-2"><UsersIcon className="size-4" />{team.name}</span><Badge variant="outline">{team.status}</Badge></CardTitle></CardHeader><CardContent><p className="text-sm text-muted-foreground">Coordinator: {team.coordinator.name}</p><p className="text-sm text-muted-foreground">{team.workers.length} worker{team.workers.length === 1 ? "" : "s"}</p></CardContent></Card></Link>)}</div> : <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">No teams yet. Create one to get started.</CardContent></Card>}
    </PageScroll>
  );
}
