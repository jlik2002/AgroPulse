import { Check, CircleHelp, Minus } from "lucide-react";

import { Card, CardHeader } from "@/components/ui/Card";
import { Chip } from "@/components/ui/Chip";
import { cn } from "@/lib/cn";
import type { CorroborationView } from "@/lib/corroboration";

const TONE_CHIP: Record<CorroborationView["tone"], string> = {
  good: "bg-ok-soft text-ok-ink",
  warn: "bg-warn-soft text-warn-ink",
  danger: "bg-danger-soft text-danger-ink",
  muted: "bg-[#F1F2F4] text-ink-soft",
};

/** Разбор подтверждённости события: из каких независимых свидетельств
 *  она сложилась.
 *
 *  Это прямой ответ на вопрос «почему я должен этому верить», и отвечать
 *  на него числом нельзя: балл без расшифровки — ещё один непонятный
 *  показатель на экране. Поэтому здесь перечень со знаками, как в разборе
 *  вклада факторов риска, а само число вынесено на второй план. */
export function EvidencePanel({ trust }: { trust: CorroborationView }) {
  return (
    <Card>
      <CardHeader
        title="Насколько этому можно верить"
        action={
          <Chip className={TONE_CHIP[trust.tone]} size="sm">
            {trust.title}
          </Chip>
        }
      />
      <div className="px-5 pb-5 pt-3">
        {trust.evidence.length > 0 ? (
          <ul className="space-y-1.5">
            {trust.evidence.map((item) => {
              const supports = item.weight > 0;
              return (
                <li key={item.label} className="flex items-center gap-2.5 text-[14.5px]">
                  <span
                    className={cn(
                      "flex h-5 w-5 shrink-0 items-center justify-center rounded-full",
                      supports ? "bg-ok-soft text-ok-ink" : "bg-warn-soft text-warn-ink",
                    )}
                  >
                    {supports ? <Check size={13} strokeWidth={3} /> : <Minus size={13} strokeWidth={3} />}
                  </span>
                  <span className={supports ? "text-ink" : "text-ink-soft"}>{item.label}</span>
                  <span
                    className={cn(
                      "ml-auto tnum text-[14px] tabular-nums",
                      supports ? "text-ink-soft" : "text-warn-ink",
                    )}
                  >
                    {supports ? "+" : "−"}
                    {Math.abs(item.weight)}
                  </span>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="flex items-start gap-2.5 text-[14.5px] leading-relaxed text-ink-soft">
            <CircleHelp size={17} className="mt-0.5 shrink-0 text-ink-muted" />
            {trust.detail}
          </p>
        )}

        {/* Пояснение обязательно: иначе перечень читается как штрафы,
            а не как разбор источников. */}
        <p className="mt-4 border-t border-line pt-3 text-[13.5px] leading-relaxed text-ink-muted">
          Оценка складывается из независимых источников: оптический снимок, радар
          и погода. Совпадение сразу в нескольких надёжнее, чем сильный сигнал
          в одном — оптику закрывают облака, а радар не видит цвет растений.
          {trust.score !== null ? ` Итог — ${trust.score} из 100.` : ""}
        </p>
      </div>
    </Card>
  );
}
