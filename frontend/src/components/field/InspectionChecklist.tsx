import { Modal } from "@/components/ui/Modal";
import { Notice } from "@/components/ui/State";
import type { Anomaly, Risk } from "@/api/types";
import { Info } from "lucide-react";

interface InspectionChecklistProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  anomaly: Anomaly | null;
  risk: Risk | undefined;
}

/** Что проверить при выезде.
 *
 *  Список собирается из факторов, которые сервис действительно зафиксировал:
 *  каждый пункт привязан к найденному признаку. Общие рекомендации без
 *  основания сюда не попадают — иначе список превратился бы в шум. */
export function InspectionChecklist({
  open,
  onOpenChange,
  anomaly,
  risk,
}: InspectionChecklistProps) {
  const items = buildChecklist(anomaly, risk);

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title="Что проверить при выезде"
      description="Список составлен по признакам, которые нашёл анализ"
      className="w-[min(560px,calc(100vw-32px))]"
    >
      <ol className="space-y-3">
        {items.map((item, index) => (
          <li key={item.title} className="flex gap-3.5">
            <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-[13px] font-semibold text-brand-800">
              {index + 1}
            </span>
            <div className="min-w-0">
              <p className="text-[15px] font-medium text-ink">{item.title}</p>
              <p className="mt-0.5 text-[13.5px] leading-relaxed text-ink-soft">{item.reason}</p>
            </div>
          </li>
        ))}
      </ol>

      <Notice icon={<Info size={16} />} className="mt-5">
        Сервис фиксирует отклонение вегетационной динамики, но не ставит диагноз.
        Причину подтверждает осмотр на месте.
      </Notice>
    </Modal>
  );
}

interface ChecklistItem {
  title: string;
  reason: string;
}

function buildChecklist(anomaly: Anomaly | null, risk: Risk | undefined): ChecklistItem[] {
  const items: ChecklistItem[] = [];
  const factors = (anomaly?.factors ?? {}) as Record<string, unknown>;

  if (anomaly) {
    items.push({
      title: "Осмотреть участок в границах аномального периода",
      reason: `Отклонение держалось ${anomaly.duration_days} дн., максимум z-score ${anomaly.max_zscore.toFixed(2)}. Начните с той части поля, где снижение видно на снимке.`,
    });
  }

  if (isTruthy(factors.precipitation_deficit) || isTruthy(factors.dry)) {
    items.push({
      title: "Проверить влажность почвы на глубине корневого слоя",
      reason: "В аномальном периоде зафиксирован дефицит осадков — влагообеспеченность стоит подтвердить замером.",
    });
  }

  if (isTruthy(factors.heat) || isTruthy(factors.high_temperature)) {
    items.push({
      title: "Оценить признаки температурного стресса на растениях",
      reason: "Период совпал с повышенной температурой: скручивание листа и потеря тургора видны только на месте.",
    });
  }

  if (isTruthy(factors.ndmi_drop)) {
    items.push({
      title: "Сверить состояние с показателем влажности NDMI",
      reason: "Вместе с NDVI снижался NDMI — это указывает скорее на водный стресс, чем на смену фазы развития.",
    });
  }

  if (isTruthy(factors.phase_mismatch) || isTruthy(factors.crop_rotation)) {
    items.push({
      title: "Уточнить культуру и фактическую дату уборки",
      reason: "Форма сезонной кривой отличается от нормы поля — возможна смена культуры в севообороте или плановая уборка.",
    });
  }

  if ((anomaly?.restored_fraction ?? 0) > 0.3) {
    items.push({
      title: "Учитывать, что часть периода восстановлена моделью",
      reason: "Внутри аномального периода много облачных дат: вывод опирается на восстановленные значения и требует подтверждения.",
    });
  }

  if (risk?.insufficient_reason) {
    items.push({
      title: "Собрать наблюдения на месте",
      reason: risk.insufficient_reason,
    });
  }

  if (items.length === 0) {
    items.push({
      title: "Плановый осмотр",
      reason: "Явных отклонений от ожидаемой динамики анализ не нашёл — достаточно обычной проверки состояния посевов.",
    });
  }

  return items;
}

function isTruthy(value: unknown): boolean {
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value !== 0;
  if (typeof value === "string") return value.length > 0 && value !== "false";
  return false;
}
