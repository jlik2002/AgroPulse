import { CalendarDays, CheckCircle2, Clock, CloudSun, Leaf, Pentagon, Satellite, TriangleAlert } from "lucide-react";

import type { Field, Project } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { FieldBadge } from "@/components/ui/FieldBadge";
import { Modal } from "@/components/ui/Modal";
import { formatArea, formatPeriod, fieldsWord } from "@/lib/format";

interface PreflightDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  project: Project;
  fields: Field[];
  onConfirm: () => void;
  starting?: boolean;
}

/** Финальная проверка перед длительным расчётом.
 *
 *  Отсутствие культуры показывается предупреждением, но запуск не блокирует:
 *  анализ в этом случае опирается на собственную историю поля. */
export function PreflightDialog({
  open,
  onOpenChange,
  project,
  fields,
  onConfirm,
  starting,
}: PreflightDialogProps) {
  const totalArea = fields.reduce((sum, field) => sum + (field.area_ha ?? 0), 0);
  const withoutCrop = fields.filter((field) => !field.crop);

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title="Проверьте параметры анализа"
      description="Перед запуском убедитесь, что всё указано верно"
      footer={
        <div className="grid grid-cols-2 gap-3">
          <Button variant="outline" size="lg" onClick={() => onOpenChange(false)}>
            Назад
          </Button>
          <Button size="lg" onClick={onConfirm} disabled={starting || fields.length === 0}>
            {starting ? "Запускаем…" : "Начать анализ"}
          </Button>
        </div>
      }
    >
      <div className="space-y-5">
        <div className="flex items-stretch rounded-xl border border-line bg-[#FAFBFB]">
          <Metric icon={<Pentagon size={20} />} value={String(fields.length)} unit={fieldsWord(fields.length)} />
          <span className="my-3 w-px bg-line" />
          <Metric
            icon={<Leaf size={20} />}
            value={Math.round(totalArea).toLocaleString("ru-RU")}
            unit="га"
          />
        </div>

        <section>
          <h3 className="mb-2.5 text-[13px] font-medium text-ink-soft">Выбранные поля</h3>
          <ul className="space-y-2">
            {fields.map((field, index) => (
              <li key={field.id} className="flex items-center gap-2.5 text-[14px] text-ink">
                <FieldBadge index={index + 1} size="sm" />
                <span className="truncate font-medium">{field.name}</span>
                <span className="text-ink-muted">·</span>
                <span className="text-ink-soft">{formatArea(field.area_ha)}</span>
                <span className="text-ink-muted">·</span>
                <span className="truncate text-ink-soft">{field.crop ?? "Культура не указана"}</span>
              </li>
            ))}
          </ul>
        </section>

        <div className="space-y-2.5 border-t border-line-soft pt-4">
          <div className="flex items-center gap-2.5 text-[14px]">
            <CalendarDays size={17} className="shrink-0 text-ink-muted" />
            <span className="text-ink">Период анализа</span>
            <span className="ml-auto font-medium text-ink">
              {formatPeriod(project.period_from, project.period_to)}
            </span>
          </div>
          <div className="flex items-center gap-2.5 text-[14px] text-ink-soft">
            <Clock size={17} className="shrink-0 text-ink-muted" />
            Также загрузим доступную историю полей для сравнения
          </div>
        </div>

        <section className="border-t border-line-soft pt-4">
          <h3 className="mb-2.5 text-[13px] font-medium text-ink-soft">Источники данных</h3>
          <ul className="space-y-2.5">
            <SourceRow
              icon={<Satellite size={18} />}
              name="Sentinel-2"
              detail="спутниковые снимки"
            />
            <SourceRow icon={<CloudSun size={18} />} name="Погода" detail="температура и осадки" />
          </ul>
        </section>

        {withoutCrop.length > 0 ? (
          <div className="flex items-start gap-3 rounded-xl border border-warn-line bg-warn-soft px-4 py-3.5">
            <TriangleAlert size={18} className="mt-0.5 shrink-0 text-warn" />
            <p className="text-[13.5px] leading-relaxed text-ink-soft">
              {withoutCrop.length === 1
                ? `У поля «${withoutCrop[0].name}» не указана культура.`
                : `У ${withoutCrop.length} ${fieldsWord(withoutCrop.length)} не указана культура.`}
              <br />
              Анализ будет основан на собственной истории поля.
            </p>
          </div>
        ) : null}

        <p className="flex items-center gap-2.5 text-[13.5px] text-ink-muted">
          <Clock size={16} />
          Обычно занимает 2–4 минуты
        </p>
      </div>
    </Modal>
  );
}

function Metric({ icon, value, unit }: { icon: React.ReactNode; value: string; unit: string }) {
  return (
    <div className="flex flex-1 items-center gap-3 px-5 py-4">
      <span className="text-brand-600">{icon}</span>
      <span className="flex items-baseline gap-1.5">
        <span className="text-[22px] font-semibold text-ink tnum">{value}</span>
        <span className="text-[14px] text-ink-soft">{unit}</span>
      </span>
    </div>
  );
}

function SourceRow({ icon, name, detail }: { icon: React.ReactNode; name: string; detail: string }) {
  return (
    <li className="flex items-center gap-3 text-[14px]">
      <span className="shrink-0 text-ink-soft">{icon}</span>
      <span className="font-medium text-ink">{name}</span>
      <span className="text-ink-muted">·</span>
      <span className="text-ink-soft">{detail}</span>
      <CheckCircle2 size={19} className="ml-auto shrink-0 text-ok" />
    </li>
  );
}
