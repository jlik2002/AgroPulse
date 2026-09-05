import {
  Building2,
  CircleHelp,
  Download,
  FileText,
  MapPinOff,
  Plus,
  TriangleAlert,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { downloadFile } from "@/api/client";
import { useCreateFarm, useRegistry } from "@/api/queries";
import type { RegistryRow } from "@/api/types";
import { useProjectContext } from "@/app/ProjectContext";
import { FarmEditDialog, type FarmDraft } from "@/components/farm/FarmEditDialog";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { Chip } from "@/components/ui/Chip";
import { EmptyState, ErrorState, Loading, Notice } from "@/components/ui/State";
import { cn } from "@/lib/cn";
import { FARM_TRUST, REVIEW_CATEGORY, farmsWord, needTone } from "@/lib/farm";
import { formatArea, formatPeriod, fieldsWord } from "@/lib/format";
import { statusOf } from "@/lib/status";

/** Реестр приоритетной поддержки — главный экран государственного сценария.
 *
 *  Три списка вместо одного отсортированного, и это не оформление. Хозяйство
 *  без заключения нельзя поставить в конец очереди: последнее место читается
 *  как «поддержка не нужна», тогда как сказать про него нечего. Поля вне
 *  хозяйств в реестр не входят вовсе, и это видно, а не спрятано. */
export function FarmsPage() {
  const navigate = useNavigate();
  const { project } = useProjectContext();
  const registry = useRegistry(project.id);
  const createFarm = useCreateFarm(project.id);

  const [adding, setAdding] = useState(false);
  const [downloading, setDownloading] = useState<"pdf" | "csv" | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const totals = useMemo(() => {
    const rows = [...(registry.data?.rows ?? []), ...(registry.data?.undetermined ?? [])];
    const count = (key: string) =>
      rows.filter((row) => row.assessment.category === key).length;
    return {
      urgent: count("urgent"),
      support: count("support"),
      clarify: count("clarify"),
      undetermined: count("undetermined"),
      problemArea: rows.reduce((sum, row) => sum + row.assessment.problem_area_ha, 0),
      unassessedArea: rows.reduce((sum, row) => sum + row.assessment.unassessed_area_ha, 0),
    };
  }, [registry.data]);

  const download = async (kind: "pdf" | "csv") => {
    setDownloading(kind);
    setDownloadError(null);
    try {
      await downloadFile(`/projects/${project.id}/registry.${kind}`);
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : String(error));
    } finally {
      setDownloading(null);
    }
  };

  if (registry.isPending) return <Loading text="Собираем реестр" />;
  if (registry.isError) {
    return (
      <div className="mx-auto max-w-2xl px-9 py-12">
        <ErrorState error={registry.error} />
      </div>
    );
  }

  const data = registry.data;
  const empty = data.farms_total === 0;

  return (
    <div className="px-9 py-7">
      <div className="flex items-start justify-between gap-8">
        <div>
          <h1 className="text-[30px] font-semibold leading-tight text-ink">
            Реестр приоритетной поддержки
          </h1>
          <p className="mt-1.5 text-[15px] text-ink-muted">
            {data.farms_total} {farmsWord(data.farms_total)} · {formatArea(data.total_area_ha)} ·
            наблюдение за {formatPeriod(data.period_from, data.period_to)}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-3">
          <Button
            variant="outline"
            size="lg"
            onClick={() => void download("csv")}
            disabled={empty || downloading !== null}
          >
            <Download size={18} />
            {downloading === "csv" ? "Готовим…" : "CSV"}
          </Button>
          <Button
            variant="outline"
            size="lg"
            onClick={() => void download("pdf")}
            disabled={empty || downloading !== null}
          >
            <FileText size={18} />
            {downloading === "pdf" ? "Собираем…" : "Реестр PDF"}
          </Button>
          <Button size="lg" onClick={() => setAdding(true)}>
            <Plus size={18} />
            Хозяйство
          </Button>
        </div>
      </div>

      {downloadError ? (
        <ErrorState className="mt-4" title="Документ не сформирован" error={downloadError} />
      ) : null}

      {empty ? (
        <Card className="mt-6">
          <EmptyState
            icon={<Building2 size={22} />}
            title="В проекте ещё нет хозяйств"
            description="Хозяйство — единица решения о поддержке: его поля оцениваются вместе, и реестр ранжирует именно хозяйства. Заведите первое, а затем добавьте ему поля на карте."
            action={
              <Button onClick={() => setAdding(true)}>
                <Plus size={17} />
                Создать хозяйство
              </Button>
            }
          />
        </Card>
      ) : (
        <>
          <div className="mt-6 grid grid-cols-4 gap-4">
            <StatCard tone="danger" value={totals.urgent} label="Срочная проверка" />
            <StatCard tone="warn" value={totals.support} label="Рассмотреть поддержку" />
            <StatCard tone="violet" value={totals.clarify} label="Запросить сведения" />
            <StatCard tone="muted" value={totals.undetermined} label="Без заключения" />
          </div>

          <Card className="mt-4">
            <CardHeader
              title="Очередь рассмотрения"
              subtitle="Индекс потребности в поддержке выражает приоритет рассмотрения, а не размер ущерба и не сумму помощи"
            />
            <div className="px-5 pb-5 pt-1">
              {data.rows.length === 0 ? (
                <EmptyState
                  title="Заключение не сформировано ни по одному хозяйству"
                  description="Запустите анализ полей — без наблюдений индекс не рассчитывается."
                />
              ) : (
                <table className="w-full text-[14px]">
                  <thead>
                    <tr className="text-left text-[13px] text-ink-muted">
                      <th className="w-12 pb-2 font-medium">№</th>
                      <th className="pb-2 font-medium">Хозяйство</th>
                      <th className="w-28 pb-2 text-right font-medium">Площадь</th>
                      <th className="w-20 pb-2 text-right font-medium">Индекс</th>
                      <th className="pb-2 font-medium">Причина</th>
                      <th className="w-32 pb-2 font-medium">Достоверность</th>
                      <th className="w-44 pb-2 font-medium">Действие</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line-soft">
                    {data.rows.map((row) => (
                      <Row
                        key={row.farm.id}
                        row={row}
                        onOpen={() => navigate(`/p/${project.id}/farm/${row.farm.id}`)}
                      />
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </Card>

          {data.undetermined.length > 0 ? (
            <Card className="mt-4">
              <CardHeader
                title="Хозяйства без заключения"
                subtitle="Индекс не выставлен: данных для вывода не хватает"
              />
              <div className="px-5 pb-5 pt-1">
                <Notice tone="info" icon={<CircleHelp size={16} />} className="mb-3">
                  Поставить их в конец очереди нельзя: последнее место читалось бы как
                  «поддержка не нужна», а сказать про них нечего.
                </Notice>
                <ul className="divide-y divide-line-soft">
                  {data.undetermined.map((row) => (
                    <li key={row.farm.id} className="flex items-center gap-4 py-3">
                      <Link
                        to={`/p/${project.id}/farm/${row.farm.id}`}
                        className="min-w-0 flex-1 truncate font-medium text-ink hover:text-brand-700"
                      >
                        {row.farm.name}
                      </Link>
                      <span className="shrink-0 text-[13.5px] text-ink-soft">
                        {formatArea(row.assessment.total_area_ha)} ·{" "}
                        {row.assessment.fields_total} {fieldsWord(row.assessment.fields_total)}
                      </span>
                      <span className="w-64 shrink-0 truncate text-[13.5px] text-ink-muted">
                        {row.assessment.notes[0] ?? "наблюдений за период недостаточно"}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            </Card>
          ) : null}
        </>
      )}

      {data.unassigned_fields.length > 0 ? (
        <Card className="mt-4">
          <CardHeader
            title="Поля вне хозяйств"
            subtitle="В реестр не входят: решение о поддержке принимается по хозяйству"
          />
          <div className="px-5 pb-5 pt-1">
            <Notice tone="warn" icon={<MapPinOff size={16} />} className="mb-3">
              Эти контуры заведены до появления хозяйств. Откройте поле на карте и укажите
              владельца — иначе их площадь останется вне любого отчёта.
            </Notice>
            <ul className="divide-y divide-line-soft">
              {data.unassigned_fields.map((row) => {
                const style = statusOf(row.status);
                return (
                  <li key={row.field_id} className="flex items-center gap-4 py-3">
                    <Link
                      to={`/p/${project.id}/field/${row.field_id}`}
                      className="min-w-0 flex-1 truncate font-medium text-ink hover:text-brand-700"
                    >
                      {row.name}
                    </Link>
                    <span className="shrink-0 text-[13.5px] text-ink-soft">
                      {formatArea(row.area_ha)} · {row.crop ?? "культура не указана"}
                    </span>
                    <Chip size="sm" className={cn("shrink-0", style.chip)}>
                      {style.title}
                    </Chip>
                  </li>
                );
              })}
            </ul>
          </div>
        </Card>
      ) : null}

      <FarmEditDialog
        open={adding}
        onOpenChange={setAdding}
        mode="create"
        initial={null}
        saving={createFarm.isPending}
        error={(createFarm.error as Error | null)?.message ?? null}
        onSubmit={(draft: FarmDraft) =>
          createFarm.mutate(draft, {
            onSuccess: (farm) => {
              setAdding(false);
              navigate(`/p/${project.id}/farm/${farm.id}`);
            },
          })
        }
      />
    </div>
  );
}

function Row({ row, onOpen }: { row: RegistryRow; onOpen: () => void }) {
  const assessment = row.assessment;
  const category = REVIEW_CATEGORY[assessment.category];
  const trust = FARM_TRUST[assessment.trust];

  return (
    <tr className="cursor-pointer align-top transition-colors hover:bg-[#FAFBFB]" onClick={onOpen}>
      <td className="py-3 text-[15px] font-semibold text-ink tnum">{row.rank}</td>
      <td className="py-3 pr-4">
        <span className="block font-medium text-ink">{row.farm.name}</span>
        {row.farm.district ? (
          <span className="block text-[13px] text-ink-muted">{row.farm.district}</span>
        ) : null}
      </td>
      <td className="py-3 text-right text-ink-soft tnum">
        {formatArea(assessment.total_area_ha)}
        {assessment.unassessed_area_ha > 0 ? (
          <span className="block text-[12.5px] text-ink-muted">
            без оценки {formatArea(assessment.unassessed_area_ha)}
          </span>
        ) : null}
      </td>
      <td className="py-3 text-right">
        <span
          className={cn(
            "text-[19px] font-semibold tnum",
            needTone(assessment.support_need_score),
          )}
        >
          {assessment.support_need_score === null
            ? "—"
            : Math.round(assessment.support_need_score)}
        </span>
      </td>
      <td className="py-3 pr-4 text-ink-soft">{assessment.reason ?? "—"}</td>
      <td className="py-3">
        <Chip size="sm" className={trust.chip}>
          {trust.title}
        </Chip>
      </td>
      <td className="py-3">
        <Chip size="sm" className={category.chip} dot={category.dot}>
          {category.action}
        </Chip>
      </td>
    </tr>
  );
}

function StatCard({
  tone,
  value,
  label,
}: {
  tone: "danger" | "warn" | "violet" | "muted";
  value: number;
  label: string;
}) {
  const tones = {
    danger: "bg-danger-soft text-danger",
    warn: "bg-warn-soft text-warn",
    violet: "bg-[#F2ECFB] text-[#65409F]",
    muted: "bg-[#F1F2F4] text-ink-muted",
  } as const;

  return (
    <Card className="flex items-center gap-4 px-5 py-4">
      <span className={cn("flex h-12 w-12 items-center justify-center rounded-full", tones[tone])}>
        <TriangleAlert size={22} />
      </span>
      <span>
        <span className="block text-[26px] font-semibold leading-none text-ink tnum">{value}</span>
        <span className="mt-1.5 block text-[14px] text-ink-soft">{label}</span>
      </span>
    </Card>
  );
}
