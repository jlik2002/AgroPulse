import * as Popover from "@radix-ui/react-popover";
import { CalendarDays, ChevronDown } from "lucide-react";
import { useEffect, useState } from "react";

import { cn } from "@/lib/cn";
import { Button } from "@/components/ui/Button";
import { formatPeriod } from "@/lib/format";

interface DateRangeProps {
  from: string;
  to: string;
  onChange: (range: { from: string; to: string }) => void;
  className?: string;
  min?: string;
  max?: string;
  disabled?: boolean;
}

/** Выбор периода анализа. Период общий для всех полей проекта: иначе
 *  результаты полей нельзя было бы сравнивать при ранжировании. */
export function DateRange({ from, to, onChange, className, min, max, disabled }: DateRangeProps) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState({ from, to });

  useEffect(() => {
    if (open) setDraft({ from, to });
  }, [open, from, to]);

  const days = Math.round(
    (new Date(draft.to).getTime() - new Date(draft.from).getTime()) / 86_400_000,
  );
  // Бэкенд отклоняет период короче 14 дней: ряд был бы непоказательным.
  const error =
    Number.isNaN(days) || days < 0
      ? "Конец периода раньше начала"
      : days < 14
        ? "Период должен быть не короче 14 дней"
        : null;

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger
        disabled={disabled}
        className={cn(
          "flex h-11 w-full items-center gap-2.5 rounded-xl border border-line bg-white px-3.5 text-[14px] text-ink transition-colors hover:border-[#D6DAE0] disabled:opacity-50",
          className,
        )}
      >
        <CalendarDays size={17} className="shrink-0 text-ink-muted" />
        <span className="min-w-0 flex-1 truncate text-left">{formatPeriod(from, to)}</span>
        <ChevronDown size={16} className="shrink-0 text-ink-muted" />
      </Popover.Trigger>

      <Popover.Portal>
        <Popover.Content
          align="start"
          sideOffset={6}
          className="z-[1200] w-[320px] rounded-xl border border-line bg-white p-4 shadow-pop animate-fade-in"
        >
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="mb-1.5 block text-[12.5px] text-ink-muted">Начало</span>
              <input
                type="date"
                value={draft.from}
                min={min}
                max={max}
                onChange={(event) => setDraft((value) => ({ ...value, from: event.target.value }))}
                className="h-10 w-full rounded-lg border border-line px-2.5 text-[13.5px] text-ink"
              />
            </label>
            <label className="block">
              <span className="mb-1.5 block text-[12.5px] text-ink-muted">Конец</span>
              <input
                type="date"
                value={draft.to}
                min={min}
                max={max}
                onChange={(event) => setDraft((value) => ({ ...value, to: event.target.value }))}
                className="h-10 w-full rounded-lg border border-line px-2.5 text-[13.5px] text-ink"
              />
            </label>
          </div>

          {error ? <p className="mt-2.5 text-[12.5px] text-danger-ink">{error}</p> : null}

          <div className="mt-4 flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={() => setOpen(false)}>
              Отмена
            </Button>
            <Button
              size="sm"
              disabled={Boolean(error)}
              onClick={() => {
                onChange(draft);
                setOpen(false);
              }}
            >
              Применить
            </Button>
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
