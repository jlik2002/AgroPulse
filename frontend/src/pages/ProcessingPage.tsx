import {
  BarChart3,
  Check,
  CircleAlert,
  Cloud,
  Leaf,
  Satellite,
  ShieldCheck,
  TrendingUp,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useProjectProgress, type FieldProgress } from "@/api/progress";
import { useProjectContext } from "@/app/ProjectContext";
import { groupStages, type GroupState } from "@/components/field/StageGroups";
import { Button } from "@/components/ui/Button";
import { FieldBadge } from "@/components/ui/FieldBadge";
import { Progress } from "@/components/ui/Progress";
import { Spinner } from "@/components/ui/State";
import { cn } from "@/lib/cn";
import { formatArea, formatMinutesLeft, plural } from "@/lib/format";

/** Подпись шага, когда воркер не прислал собственного сообщения. */
const DEFAULT_STAGE_TEXT: Record<GroupState["status"], string> = {
  pending: "Ожидает завершения предыдущего этапа",
  running: "Выполняется",
  done: "Готово",
  failed: "Шаг завершился ошибкой",
};

const ICONS = {
  satellite: Satellite,
  cloud: Cloud,
  leaf: Leaf,
  trend: TrendingUp,
  chart: BarChart3,
} as const;

/** Ход анализа по стадиям. Каждое поле обрабатывается независимо, поэтому
 *  готовый результат можно открыть, не дожидаясь остальных. */
export function ProcessingPage() {
  const navigate = useNavigate();
  const { project, fields, refetchFields } = useProjectContext();
  const progress = useProjectProgress(project.id);
  const [selected, setSelected] = useState<string | null>(null);

  const rows = useMemo(
    () =>
      fields.map((field, index) => ({
        field,
        index: index + 1,
        state: progress.byField[field.id] as FieldProgress | undefined,
        // Поле считается завершённым и по событию шины, и по статусу в базе:
        // событие может быть потеряно, а статус переживает перезагрузку.
        // Ошибка — тоже завершение: иначе прогресс никогда не дойдёт до конца,
        // а «осталось около N минут» будет висеть вечно.
        ready: progress.finished.has(field.id) || field.status !== "pending",
        failed: field.status === "failed" || Boolean(progress.byField[field.id]?.failed),
      })),
    [fields, progress.byField, progress.finished],
  );

  const readyCount = rows.filter((row) => row.ready).length;
  // В счётчике «готово» упавшие поля не считаются готовыми, но опрос
  // статусов останавливает именно завершённость, а не успешность.
  const successCount = rows.filter((row) => row.ready && !row.failed).length;
  const overall = rows.length
    ? Math.round(
        rows.reduce((sum, row) => sum + (row.ready ? 100 : (row.state?.percent ?? 0)), 0) /
          rows.length,
      )
    : 0;

  const activeRow =
    rows.find((row) => row.field.id === selected) ??
    rows.find((row) => !row.ready) ??
    rows[0];

  // Пока идёт расчёт, подтягиваем статусы полей: они меняются в базе,
  // а не только в шине событий.
  useEffect(() => {
    if (readyCount >= rows.length) return;
    const timer = window.setInterval(refetchFields, 5_000);
    return () => window.clearInterval(timer);
  }, [readyCount, rows.length, refetchFields]);

  const remainingMinutes = useMemo(() => {
    const pending = rows.filter((row) => !row.ready);
    if (pending.length === 0) return 0;
    const left = pending.reduce((sum, row) => sum + (100 - (row.state?.percent ?? 0)) / 100, 0);
    // Ориентир — две минуты на поле: столько занимает сбор в типичном сценарии.
    return left * 2;
  }, [rows]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-start justify-between gap-10 px-9 py-7">
        <div>
          <h1 className="text-[30px] font-semibold leading-tight text-ink">Обработка данных</h1>
          <p className="mt-1.5 text-[15px] text-ink-muted">
            Можно не ждать завершения всех полей — готовые результаты откроются сразу
          </p>
        </div>

        <div className="w-[420px] shrink-0">
          <p className="text-[15px] text-ink">
            <span className="tnum font-medium">{successCount}</span> из{" "}
            <span className="tnum font-medium">{rows.length}</span>{" "}
            {plural(rows.length, "поля", "полей", "полей")} готово
          </p>
          <div className="mt-2 flex items-center gap-3">
            <Progress value={overall} className="flex-1" />
            <span className="w-11 text-right text-[15px] font-medium text-ink tnum">{overall}%</span>
          </div>
          <p className="mt-1.5 text-[13.5px] text-ink-muted">
            {remainingMinutes > 0
              ? `Осталось около ${formatMinutesLeft(remainingMinutes)}`
              : "Все поля обработаны"}
          </p>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(360px,42%)_1fr] border-t border-line">
        {/* --- список полей --- */}
        <section className="min-h-0 overflow-y-auto border-r border-line px-9 py-7 scroll-thin">
          <h2 className="mb-4 text-[20px] font-semibold text-ink">Поля проекта</h2>
          <div className="space-y-3">
            {rows.map((row) => (
              // Карточка кликабельна целиком, но внутри лежит своя кнопка,
              // поэтому это div с ролью кнопки, а не вложенный <button>.
              <div
                key={row.field.id}
                role="button"
                tabIndex={0}
                onClick={() => setSelected(row.field.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") setSelected(row.field.id);
                }}
                className={cn(
                  "block w-full cursor-pointer rounded-2xl border px-5 py-4 text-left transition-colors",
                  row.ready
                    ? "border-brand-200 bg-brand-50/60"
                    : activeRow?.field.id === row.field.id
                      ? "border-brand-300 bg-white"
                      : "border-line bg-white hover:border-[#D6DAE0]",
                )}
              >
                <div className="flex items-start gap-3.5">
                  <FieldBadge index={row.index} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[17px] font-semibold text-ink">{row.field.name}</p>
                    <p className="mt-0.5 text-[14px] text-ink-soft">
                      {formatArea(row.field.area_ha)} · {row.field.crop ?? "Культура не указана"}
                    </p>
                  </div>
                  <StatusPill row={row} />
                </div>

                <div className="mt-3.5 flex items-center gap-3">
                  <Progress
                    value={row.ready ? 100 : (row.state?.percent ?? 0)}
                    tone={row.failed ? "danger" : "brand"}
                    className="flex-1"
                  />
                  <span className="w-11 text-right text-[14px] font-medium text-ink tnum">
                    {row.ready ? 100 : (row.state?.percent ?? 0)}%
                  </span>
                </div>

                {row.ready && !row.failed ? (
                  <Button
                    className="mt-4"
                    onClick={(event) => {
                      event.stopPropagation();
                      navigate(`/p/${project.id}/field/${row.field.id}`);
                    }}
                  >
                    Открыть результат
                  </Button>
                ) : (
                  <p className="mt-2.5 text-[13.5px] text-ink-muted">
                    {row.failed
                      ? (row.state?.current?.error ??
                        "Обработка прервана — попробуйте запустить анализ снова")
                      : (row.state?.current?.stage_title ?? "Ожидает очереди")}
                  </p>
                )}
              </div>
            ))}
          </div>
        </section>

        {/* --- стадии выбранного поля --- */}
        <section className="min-h-0 overflow-y-auto px-9 py-7 scroll-thin">
          {activeRow ? (
            <>
              <h2 className="text-[20px] font-semibold text-ink">{activeRow.field.name}</h2>
              <p className="mt-1 text-[14px] text-ink-muted">Текущий этап анализа</p>

              <div className="mt-5 rounded-2xl border border-line bg-white">
                {groupStages(activeRow.state?.stages ?? []).map((state, index, list) => (
                  <StageRow
                    key={state.group.key}
                    state={state}
                    last={index === list.length - 1}
                    // Реальный статус стадии не перекрашиваем: поле, завершившееся
                    // с недостаточными данными, не должно показывать пять зелёных
                    // галочек. Достраиваем только поля без истории прогресса —
                    // те, что обработаны в прошлой сессии, а jobs уже вычищены.
                    assumeDone={activeRow.ready && !activeRow.failed && !activeRow.state}
                  />
                ))}
              </div>

              <div className="mt-5 flex items-start gap-3.5 rounded-2xl border border-ok-line bg-ok-soft px-5 py-4">
                <ShieldCheck size={22} className="mt-0.5 shrink-0 text-ok" />
                <div>
                  <p className="text-[15px] font-medium text-ink">Данные сохраняются автоматически</p>
                  <p className="mt-0.5 text-[13.5px] text-ink-soft">
                    Можно закрыть страницу и вернуться позже
                  </p>
                </div>
              </div>

              {!progress.connected ? (
                <p className="mt-4 text-[13px] text-ink-muted">
                  Поток событий переподключается — прогресс обновится автоматически.
                </p>
              ) : null}
            </>
          ) : null}
        </section>
      </div>
    </div>
  );
}

function StatusPill({ row }: { row: { ready: boolean; failed: boolean; state?: FieldProgress } }) {
  if (row.failed) {
    return (
      <span className="flex shrink-0 items-center gap-2 text-[14px] text-danger-ink">
        <CircleAlert size={19} />
        Ошибка
      </span>
    );
  }
  if (row.ready) {
    return (
      <span className="flex shrink-0 items-center gap-2 text-[14px] text-ok-ink">
        <span className="flex h-5 w-5 items-center justify-center rounded-full border-2 border-ok">
          <Check size={12} strokeWidth={3.2} />
        </span>
        Готово
      </span>
    );
  }
  return (
    <span className="flex shrink-0 items-center gap-2 text-[14px] text-ink-soft">
      <Spinner className="h-4 w-4" />
      Обрабатывается
    </span>
  );
}

function StageRow({
  state,
  last,
  assumeDone,
}: {
  state: GroupState;
  last: boolean;
  assumeDone: boolean;
}) {
  const Icon = ICONS[state.group.icon];
  const status = assumeDone && state.status === "pending" ? "done" : state.status;

  return (
    <div className={cn("flex gap-4 px-5 py-4", !last && "border-b border-line-soft")}>
      <div className="relative flex w-6 shrink-0 justify-center pt-0.5">
        <StageMarker status={status} />
        {!last ? (
          <span className="absolute left-1/2 top-7 h-[calc(100%-8px)] w-px -translate-x-1/2 bg-line" />
        ) : null}
      </div>

      <Icon
        size={22}
        className={cn(
          "mt-0.5 shrink-0",
          status === "done" ? "text-brand-700" : status === "running" ? "text-brand-600" : "text-ink-faint",
        )}
      />

      <div className="min-w-0 flex-1">
        <p
          className={cn(
            "text-[15px] font-medium",
            status === "pending" ? "text-ink-soft" : "text-ink",
          )}
        >
          {state.group.title}
        </p>
        <p className="mt-0.5 text-[13.5px] text-ink-muted">
          {status === "failed"
            ? (state.error ?? "Шаг завершился ошибкой")
            : (state.message ?? DEFAULT_STAGE_TEXT[status])}
        </p>
        {status === "running" ? (
          <Progress value={state.progress * 100} height="sm" className="mt-2.5 max-w-[420px]" />
        ) : null}
      </div>
    </div>
  );
}

function StageMarker({ status }: { status: GroupState["status"] }) {
  if (status === "done") {
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-brand-700 text-white">
        <Check size={14} strokeWidth={3} />
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-danger text-white">
        <CircleAlert size={14} strokeWidth={2.6} />
      </span>
    );
  }
  if (status === "running") {
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full border-2 border-brand-700">
        <span className="h-2.5 w-2.5 rounded-full bg-brand-700" />
      </span>
    );
  }
  return <span className="h-6 w-6 rounded-full border-2 border-line-track" />;
}
