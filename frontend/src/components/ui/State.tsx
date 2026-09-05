import { Loader2 } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("animate-spin text-brand-700", className)} size={18} />;
}

interface LoadingProps {
  text?: string;
  className?: string;
}

export function Loading({ text = "Загрузка данных", className }: LoadingProps) {
  return (
    <div className={cn("flex items-center justify-center gap-2.5 py-12 text-ink-muted", className)}>
      <Spinner />
      <span className="text-[14px]">{text}</span>
    </div>
  );
}

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({ icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div className={cn("flex flex-col items-center px-6 py-12 text-center", className)}>
      {icon ? (
        <div className="mb-3.5 flex h-12 w-12 items-center justify-center rounded-full bg-[#F3F4F6] text-ink-muted">
          {icon}
        </div>
      ) : null}
      <p className="text-[15px] font-medium text-ink">{title}</p>
      {description ? (
        <p className="mt-1.5 max-w-md text-[13.5px] leading-relaxed text-ink-muted">{description}</p>
      ) : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

interface ErrorStateProps {
  title?: string;
  error: unknown;
  action?: ReactNode;
  className?: string;
}

export function ErrorState({ title = "Не удалось загрузить данные", error, action, className }: ErrorStateProps) {
  const message = error instanceof Error ? error.message : String(error ?? "");
  return (
    <div className={cn("rounded-xl border border-danger-line bg-danger-tint px-5 py-4", className)}>
      <p className="text-[14px] font-medium text-danger-ink">{title}</p>
      {message ? <p className="mt-1 text-[13px] text-ink-soft">{message}</p> : null}
      {action ? <div className="mt-3">{action}</div> : null}
    </div>
  );
}

interface NoticeProps {
  tone?: "info" | "warn" | "danger" | "ok";
  icon?: ReactNode;
  children: ReactNode;
  className?: string;
}

/** Плашка с пояснением. Используется для предупреждений о недостающих
 *  параметрах и для оговорок об ограничениях анализа. */
export function Notice({ tone = "info", icon, children, className }: NoticeProps) {
  const tones = {
    info: "border-line bg-[#F7F8F9] text-ink-soft",
    warn: "border-warn-line bg-warn-soft text-ink-soft",
    danger: "border-danger-line bg-danger-tint text-ink-soft",
    ok: "border-ok-line bg-ok-soft text-ink-soft",
  } as const;
  const iconTone = {
    info: "text-ink-muted",
    warn: "text-warn",
    danger: "text-danger",
    ok: "text-ok",
  } as const;

  return (
    <div className={cn("flex items-start gap-3 rounded-xl border px-4 py-3", tones[tone], className)}>
      {icon ? <span className={cn("mt-0.5 shrink-0", iconTone[tone])}>{icon}</span> : null}
      <div className="min-w-0 text-[13.5px] leading-relaxed">{children}</div>
    </div>
  );
}
