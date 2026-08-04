# Omnigent Feishu

Standalone Feishu PersonalAgent integration. It owns provider registration,
credentials, webhook idempotency, cards, surfaces, and delivery retries. It
creates and observes work only through authenticated Omnigent HTTP APIs; the
Omnigent server remains authoritative for Agent Bundles, Workspaces, Runs,
Tasks, Sessions, logs, and approvals.

Install with `uv sync --extra feishu`, copy `.env.example` into your secret
manager or shell environment, then run:

```bash
python -m omnigent_feishu
# or
omni integration feishu --background
```

The database contains provider state and opaque Core IDs only. Provider app
secrets and delegated bearer values are encrypted at rest. A Feishu sender ID
is retained as provider metadata and is never sent to Core as an actor ID.

The permanent bot surface offers workspace selection, Run creation/status,
task and log inspection, necessary approval decisions, Run stop, and help.
Approval buttons are shown only when Core reports a pending policy decision;
normal tasks execute autonomously.
