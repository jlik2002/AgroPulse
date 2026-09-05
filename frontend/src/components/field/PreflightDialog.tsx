import { CalendarDays, CheckCircle2, Clock, CloudSun, Leaf, Pentagon, Satellite, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { Field, Project } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { Chip } from "@/components/ui/Chip";
import { FieldBadge } from "@/components/ui/FieldBadge";
import { Modal } from "@/components/ui/Modal";
import { formatArea, formatPeriod, fieldsWord } from "@/lib/format";
import { statusOf } from "@/lib/status";

interface PreflightDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  project: Project;
  fields: Field[];
  /** Идентификаторы полей, которые нужно посчитать. */
  onConfirm: (fieldIds: string[]) => void;
  starting?: boolean;
}

/** Финальная проверка перед длительным расчётом.
 *
 *  Поля выбираются флажками: сбор по одному полю занимает минуты и расходует
 *  квоту Earth Engine, поэтому, добавив одно поле к десяти уже посчитанным,
 *  пользователь должен иметь возможность посчитать только его.
 *
 *  Поле без культуры запуск блокирует. Такие поля остались от времени, когда
 *  культура была необязательной: сейчас она указывается при добавлении поля,
 *  и молча считать участок, про который неизвестно, что на нём растёт,
 *  значит выпустить отчёт, который нечем защитить. */
export function PreflightDialog({
  open,
  onOpenChange,
  project,
  fields,
  onConfirm,
  starting,
}: PreflightDialogProps) {
  // Выбор храним только после явного действия пользователя: список полей
  // приезжает запросом, и вычисленное один раз начальное значение осталось бы
  // пустым навсегда. По умолчанию отмечено то, что ещё не считалось, а если
  // посчитано всё — весь список: пересчёт целиком тоже осмысленное действие.
  const [chosen, setChosen] = useState<Set<string> | null>(null);

  const pending = useMemo(
    () => fields.filter((field) => field.status === "pending" || field.status === "failed"),
    [fields],
  );
  const selected = useMemo(
    () => chosen ?? new Set((pending.length > 0 ? pending : fields).map((field) => field.id)),
    [chosen, pending, fields],
  );

  // Закрыли и открыли заново — выбор считается заново от текущих статусов.
  useEffect(() => {
    if (!open) setChosen(null);
  }, [open]);

  const toggle = (fieldId: string, checked: boolean) => {
    const next = new Set(selected);
    if (checked) next.add(fieldId);
    else next.delete(fieldId);
    setChosen(next);
  };

  const chosenFields = fields.filter((field) => selected.has(field.id));
  const totalArea = chosenFields.reduce((sum, field) => sum + (field.area_ha ?? 0), 0);
  const withoutCrop = chosenFields.filter((field) => !field.crop);
  const blocked = withoutCrop.length > 0;

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
          <Button
            size="lg"
            onClick={() => onConfirm([...selected])}
            disabled={starting || selected.size === 0 || blocked}
          >
            {starting ? "Запускаем…" : `Начать анализ · ${selected.size}`}
          </Button>
        </div>
      }
    >
      <div className="space-y-5">
        <div className="flex items-stretch rounded-xl border border-line bg-[#FAFBFB]">
          <Metric
            icon={<Pentagon size={20} />}
            value={String(selected.size)}
            unit={fieldsWord(selected.size)}
          />
          <span className="my-3 w-px bg-line" />
          <Metric
            icon={<Leaf size={20} />}
            value={Math.round(totalArea).toLocaleString("ru-RU")}
            unit="га"
          />
        </div>

        <section>
          <div className="mb-2.5 flex items-center justify-between">
            <h3 className="text-[13px] font-medium text-ink-soft">Какие поля считать</h3>
            <button
              type="button"
              onClick={() =>
                setChosen(
                  selected.size === fields.length
                    ? new Set()
                    : new Set(fields.map((field) => field.id)),
                )
              }
              className="text-[13px] font-medium text-brand-700 hover:underline"
            >
              {selected.size === fields.length ? "Снять все" : "Выбрать все"}
            </button>
          </div>
          <ul className="space-y-2">
            {fields.map((field, index) => {
              const style = statusOf(field.status);
              const done = field.status !== "pending" && field.status !== "failed";
              return (
                <li key={field.id} className="flex items-center gap-2.5 text-[14px] text-ink">
                  <Checkbox
                    checked={selected.has(field.id)}
                    onChange={(checked) => toggle(field.id, checked)}
                    ariaLabel={`Считать поле «${field.name}»`}
                  />
                  <FieldBadge index={index + 1} size="sm" />
                  <span className="min-w-0 flex-1 truncate font-medium">{field.name}</span>
                  <span className="shrink-0 text-ink-soft">{formatArea(field.area_ha)}</span>
                  {/* Посчитанные поля видно сразу: их обычно и снимают,
                      чтобы не гонять сбор второй раз. */}
                  {done ? (
                    <Chip size="sm" className={style.chip}>
                      {style.title}
                    </Chip>
                  ) : null}
                </li>
              );
            })}
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

        {blocked ? (
          <div className="flex items-start gap-3 rounded-xl border border-warn-line bg-warn-soft px-4 py-3.5">
            <TriangleAlert size={18} className="mt-0.5 shrink-0 text-warn" />
            <p className="text-[13.5px] leading-relaxed text-ink-soft">
              {withoutCrop.length === 1
                ? `У поля «${withoutCrop[0].name}» не указана культура.`
                : `У ${withoutCrop.length} ${fieldsWord(withoutCrop.length)} не указана культура.`}
              <br />
              Укажите её в карточке поля или снимите отметку — без культуры расхождение
              с нормой не отличить от севооборота.
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
