import type { ReactNode } from "react";
import { AlertCircleIcon, MoreHorizontalIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

export function CollectionPageHeader({
  title,
  description,
  actions,
  className,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("flex flex-wrap items-start justify-between gap-4", className)}>
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description ? <p className="mt-1 text-sm text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </header>
  );
}

export function CollectionToolbar({
  children,
  className,
  label,
}: {
  children: ReactNode;
  className?: string;
  label?: string;
}) {
  const { t } = useTranslation("common");
  return (
    <div
      role="toolbar"
      aria-label={label ?? t("collection.controls")}
      className={cn("flex flex-wrap items-center justify-between gap-2", className)}
    >
      {children}
    </div>
  );
}

const statusToneClasses = {
  neutral: "border-border bg-muted text-muted-foreground",
  info: "border-primary/20 bg-primary/10 text-primary",
  success: "border-success/20 bg-success/10 text-success",
  warning: "border-warning/20 bg-warning/10 text-warning",
  danger: "border-destructive/20 bg-destructive/10 text-destructive",
} as const;

export type StatusTone = keyof typeof statusToneClasses;

export function StatusBadge({
  children,
  tone = "neutral",
  className,
}: {
  children: ReactNode;
  tone?: StatusTone;
  className?: string;
}) {
  return (
    <Badge variant="outline" data-tone={tone} className={cn(statusToneClasses[tone], className)}>
      {children}
    </Badge>
  );
}

export interface SegmentedFilterOption<T extends string> {
  value: T;
  label: string;
  count?: number;
}

export function SegmentedFilter<T extends string>({
  label,
  value,
  options,
  onValueChange,
  className,
}: {
  label: string;
  value: T;
  options: readonly SegmentedFilterOption<T>[];
  onValueChange: (value: T) => void;
  className?: string;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className={cn("inline-flex items-center rounded-lg bg-muted p-0.5", className)}
    >
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={selected}
            aria-label={
              option.count === undefined ? option.label : `${option.label}, ${option.count}`
            }
            className={cn(
              "inline-flex h-7 items-center gap-1 rounded-md px-2.5 text-xs font-medium transition-colors",
              selected
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
            onClick={() => onValueChange(option.value)}
          >
            {option.label}
            {option.count === undefined ? null : (
              <span className="text-[10px] tabular-nums text-muted-foreground">{option.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export interface EntityTableColumn {
  key: string;
  label: ReactNode;
  className?: string;
}

export function EntityTable({
  columns,
  children,
  caption,
  className,
}: {
  columns: readonly EntityTableColumn[];
  children: ReactNode;
  caption: string;
  className?: string;
}) {
  return (
    <div className={cn("overflow-x-auto rounded-xl border border-border", className)}>
      <table className="w-full min-w-[640px] border-collapse text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="border-b border-border bg-muted/40 text-xs text-muted-foreground">
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={cn("h-9 px-3 font-medium", column.className)}
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">{children}</tbody>
      </table>
    </div>
  );
}

export type CollectionStateKind = "loading" | "empty" | "error";

export function CollectionState({
  state,
  title,
  description,
  action,
  className,
}: {
  state: CollectionStateKind;
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}) {
  const isError = state === "error";
  return (
    <div
      role={isError ? "alert" : "status"}
      className={cn(
        "flex min-h-48 flex-col items-center justify-center rounded-xl border border-dashed border-border px-6 py-10 text-center",
        className,
      )}
    >
      {state === "loading" ? <Spinner className="mb-3 size-5 text-muted-foreground" /> : null}
      {isError ? <AlertCircleIcon className="mb-3 size-5 text-destructive" /> : null}
      <p className="text-sm font-medium">{title}</p>
      {description ? (
        <p className="mt-1 max-w-md text-sm text-muted-foreground">{description}</p>
      ) : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export interface EntityRowAction {
  id: string;
  label: string;
  onSelect: () => void;
  disabled?: boolean;
  destructive?: boolean;
  icon?: ReactNode;
}

export function EntityRowMenu({
  actions,
  label,
}: {
  actions: readonly EntityRowAction[];
  label?: string;
}) {
  const { t } = useTranslation("common");
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          aria-label={label ?? t("collection.rowActions")}
        >
          <MoreHorizontalIcon />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {actions.map((action) => (
          <DropdownMenuItem
            key={action.id}
            disabled={action.disabled}
            variant={action.destructive ? "destructive" : "default"}
            onSelect={action.onSelect}
          >
            {action.icon}
            {action.label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
