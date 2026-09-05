import { Check, CircleHelp, TriangleAlert } from "lucide-react";

import { Card, CardHeader } from "@/components/ui/Card";
import { Chip } from "@/components/ui/Chip";
import { cn } from "@/lib/cn";
import type { TrustView } from "@/lib/trust";

const TONE_CHIP: Record<TrustView["tone"], string> = {
  good: "bg-ok-soft text-ok-ink",
  warn: "bg-warn-soft text-warn-ink",
  muted: "bg-[#F1F2F4] text-ink-soft",
};

/** На чём основан вывод о поле: перечень независимых свидетельств.
 *
 *  Прямой ответ на вопрос «почему я должен этому верить». Отвечать на него
 *  числом нельзя — прежние «35 из 100» выглядели измерением, будучи суммой
 *  назначенных весов. Здесь перечень фактов, каждый из которых можно
 *  проверить: сколько было пригодных снимков, что сказал радар, объясняет
 *  ли механизм погода. */
export function EvidencePanel({ trust }: { trust: TrustView }) {
  const icon =
    trust.tone === "good" ? (
      <Check size={13} strokeWidth={3} />
    ) : trust.tone === "warn" ? (
      <TriangleAlert size={12} />
    ) : (
      <CircleHelp size={12} />
    );

  return (
    <Card>
      <CardHeader
        title="На чём основан вывод"
        action={
          <Chip className={TONE_CHIP[trust.tone]} size="sm">
            {trust.title}
          </Chip>
        }
      />
      <div className="px-5 pb-5 pt-3">
        {trust.reasons.length > 0 ? (
          <ul className="space-y-2">
            {trust.reasons.map((reason) => (
              <li key={reason} className="flex items-start gap-2.5 text-[14.5px] leading-relaxed">
                <span
                  className={cn(
                    "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full",
                    TONE_CHIP[trust.tone],
                  )}
                >
                  {icon}
                </span>
                <span className="text-ink">{reason}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[14.5px] leading-relaxed text-ink-soft">{trust.detail}</p>
        )}

        {/* Пояснение обязательно: без него перечень читается как оправдание,
            а не как разбор источников. */}
        <p className="mt-4 border-t border-line pt-3 text-[13.5px] leading-relaxed text-ink-muted">
          Оптический снимок показывает спектральное состояние растений, радар —
          структуру полога, и облака ему не мешают. Источники независимы, поэтому
          совпадение в обоих значит больше, чем сильный сигнал в одном.
        </p>
      </div>
    </Card>
  );
}
