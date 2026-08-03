// Static "Suggestions" shown below the scheduled-tasks list.
//
// Selecting a suggestion prefills the manual create dialog. The schedule is
// left at the form default for the user to confirm.

import type { LucideIcon } from "lucide-react";
import { CalendarClockIcon, GitPullRequestIcon, NewspaperIcon } from "lucide-react";

export interface ScheduledTaskSuggestion {
  id: string;
  icon: LucideIcon;
  iconClassName: string;
  /** Translation key for the short chip label (1–2 words) shown on the pill. */
  titleKey: string;
  /** Translation keys for the editable name and prompt seeded by the chip. */
  prefill: { nameKey: string; promptKey: string };
}

export const SCHEDULED_TASK_SUGGESTIONS: ScheduledTaskSuggestion[] = [
  {
    id: "follow-up-monitor",
    icon: CalendarClockIcon,
    iconClassName: "text-blue-600 dark:text-blue-400",
    titleKey: "suggestionItems.followUpMonitor.title",
    prefill: {
      nameKey: "suggestionItems.followUpMonitor.name",
      promptKey: "suggestionItems.followUpMonitor.prompt",
    },
  },
  {
    id: "pr-sweep",
    icon: GitPullRequestIcon,
    iconClassName: "text-emerald-600 dark:text-emerald-500",
    titleKey: "suggestionItems.prSweep.title",
    prefill: {
      nameKey: "suggestionItems.prSweep.name",
      promptKey: "suggestionItems.prSweep.prompt",
    },
  },
  {
    id: "news-digest",
    icon: NewspaperIcon,
    iconClassName: "text-amber-600 dark:text-amber-500",
    titleKey: "suggestionItems.newsDigest.title",
    prefill: {
      nameKey: "suggestionItems.newsDigest.name",
      promptKey: "suggestionItems.newsDigest.prompt",
    },
  },
];
