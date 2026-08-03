import accountEn from "./locales/en/account.json";
import adminEn from "./locales/en/admin.json";
import agentsEn from "./locales/en/agents.json";
import chatEn from "./locales/en/chat.json";
import commonEn from "./locales/en/common.json";
import modelsEn from "./locales/en/models.json";
import settingsEn from "./locales/en/settings.json";
import tasksEn from "./locales/en/tasks.json";
import toolsEn from "./locales/en/tools.json";
import updatesEn from "./locales/en/updates.json";
import workspaceEn from "./locales/en/workspace.json";
import accountZhCn from "./locales/zh-CN/account.json";
import adminZhCn from "./locales/zh-CN/admin.json";
import agentsZhCn from "./locales/zh-CN/agents.json";
import chatZhCn from "./locales/zh-CN/chat.json";
import commonZhCn from "./locales/zh-CN/common.json";
import modelsZhCn from "./locales/zh-CN/models.json";
import settingsZhCn from "./locales/zh-CN/settings.json";
import tasksZhCn from "./locales/zh-CN/tasks.json";
import toolsZhCn from "./locales/zh-CN/tools.json";
import updatesZhCn from "./locales/zh-CN/updates.json";
import workspaceZhCn from "./locales/zh-CN/workspace.json";

export const namespaceKeys = [
  "common",
  "chat",
  "agents",
  "models",
  "tools",
  "workspace",
  "tasks",
  "settings",
  "account",
  "admin",
  "updates",
] as const;

export const resources = {
  en: {
    common: commonEn,
    chat: chatEn,
    agents: agentsEn,
    models: modelsEn,
    tools: toolsEn,
    workspace: workspaceEn,
    tasks: tasksEn,
    settings: settingsEn,
    account: accountEn,
    admin: adminEn,
    updates: updatesEn,
  },
  "zh-CN": {
    common: commonZhCn,
    chat: chatZhCn,
    agents: agentsZhCn,
    models: modelsZhCn,
    tools: toolsZhCn,
    workspace: workspaceZhCn,
    tasks: tasksZhCn,
    settings: settingsZhCn,
    account: accountZhCn,
    admin: adminZhCn,
    updates: updatesZhCn,
  },
} as const;
