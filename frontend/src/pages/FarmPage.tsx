import {
  ArrowLeft,
  Building2,
  CircleHelp,
  Download,
  FileText,
  Pencil,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { downloadFile } from "@/api/client";
import {
  useDeleteFarm,
  useFarmReports,
  useFarmSummary,
  useUpdateFarm,
} from "@/api/queries";
import type { FieldSummary, GeneratedReport } from "@/api/types";
import { useProjectContext } from "@/app/ProjectContext";
import { FarmEditDialog, type FarmDraft } from "@/components/farm/FarmEditDialog";
import { FieldShape } from "@/components/map/FieldShapes";
import { FitBounds, MapCanvas } from "@/components/map/MapCanvas";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { Chip } from "@/components/ui/Chip";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState, ErrorState, Loading, Notice } from "@/components/ui/State";
import { cn } from "@/lib/cn";
import { FARM_TRUST, REVIEW_CATEGORY, needTone } from "@/lib/farm";
import {
  formatArea,
  formatBytes,
  formatDate,
  formatPercent,
  formatPeriod,
  fieldsWord,
  pagesWord,
} from "@/lib/format";
import { combinedBounds } from "@/lib/geo";
import { riskTone, statusOf } from "@/lib/status";

/** Карточка хозяйства: заключение, его поля и сформированные документы.
 *
 *  Индекс и достоверность стоят рядом и всегда вместе. Порознь они позволяют
 *  прочитать «низкая потребность» там, где на хозяйство просто нет снимков, —
 *  ровно та ошибка, ради которой достоверность и считается. */
export function FarmPage() {
  const navigate = useNavigate();
  const { farmId = "" } = useParams();
  const { project, fields, indexOf } = useProjectContext();

  const summary = useFarmSummary(project.id, farmId);
  const reports = useFarmReports(farmId);
  const updateFarm = useUpdateFarm(project.id);
  const deleteFarm = useDeleteFarm(project.id);

  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const farmFields = useMemo(
    () => fields.filter((field) => field.farm_id === farmId),
    [fields, farmId],
  );
  const geometryOf = useMemo(
    () => new Map(farmFields.map((field) => [field.id, field.geometry])),
    [farmFields],
  );
  const bounds = useMemo(
    () => combinedBounds(farmFields.map((field) => field.geometry)),
    [farmFields],
  );

  const build = async (path: string) => {
    setBuilding(true);
    setError(null);
    try {
      await downloadFile(path);
      await reports.refetch();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBuilding(false);
    }
  };

  if (summary.isPending) return <Loading text="Открываем хозяйство" />;
  if (summary.isError) {
    return (
      <div className="mx-auto max-w-2xl px-9 py-12">
        <ErrorState title="Хозяйство не найдено" error={summary.error} />
      </div>
    );
  }

  const { farm, assessment } = summary.data;
  const category = REVIEW_CATEGORY[assessment.category];
  const trust = FARM_TRUST[assessment.trust];
  const details = [farm.legal_form, farm.inn ? `ИНН ${farm.inn}` : null, farm.district, farm.region]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="px-9 py-7">
      <Link
        to={`/p/${project.id}/farms`}
        className="inline-flex items-center gap-1.5 text-[14px] text-ink-muted hover:text-brand-700"
      >
        <ArrowLeft size={16} />
        Реестр хозяйств
      </Link>

      <div className="mt-3 flex items-start justify-between gap-8">
        <div className="min-w-0">
          <h1 className="text-[30px] font-semibold leading-tight text-ink">{farm.name}</h1>
          <p className="mt-1.5 text-[15px] text-ink-muted">
            {details || "реквизиты не указаны"} · наблюдение за{" "}
            {formatPeriod(summary.data.period_from, summary.data.period_to)}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-3">
          <Button variant="outline" size="lg" onClick={() => setEditing(true)}>
            <Pencil size={17} />
            Реквизиты
          </Button>
          <Button
            variant="outline"
            size="lg"
            onClick={() => void build(`/projects/${project.id}/farms/${farm.id}/export.csv`)}
            disabled={building || farmFields.length === 0}
          >
            <Download size={17} />
            CSV
          </Button>
          <Button
            size="lg"
            onClick={() => void build(`/projects/${project.id}/farms/${farm.id}/report.pdf`)}
            disabled={building || farmFields.length === 0}
          >
            <FileText size={18} />
            {building ? "Собираем…" : "Заключение"}
          </Button>
        </div>
      </div>

      {error ? <ErrorState className="mt-4" title="Документ не сформирован" error={error} /> : null}

      {/* --- заключение --- */}
      <Card className="mt-6">
        <div className="grid grid-cols-4 divide-x divide-line">
          <Metric
            value={
              assessment.support_need_score === null
                ? "—"
                : String(Math.round(assessment.support_need_score))
            }
            valueClass={needTone(assessment.support_need_score)}
            label="индекс потребности в поддержке"
          />
          <Metric value={formatArea(assessment.total_area_ha)} label="площадь хозяйства" />
          <Metric
            value={`${assessment.fields_total}`}
            label={`${fieldsWord(assessment.fields_total)} под наблюдением`}
          />
          <Metric
            value={formatPercent(assessment.problem_share)}
            label="доля проблемной площади"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2.5 border-t border-line px-5 py-4">
          <Chip className={category.chip} dot={category.dot}>
            {category.title}
          </Chip>
          <span className="text-[14px] text-ink-soft">→ {assessment.action}</span>
          <span className="ml-auto flex items-center gap-2 text-[14px] text-ink-soft">
            Достоверность
            <Chip size="sm" className={trust.chip}>
              {trust.title}
            </Chip>
          </span>
        </div>

        {assessment.reason ? (
          <p className="border-t border-line-soft px-5 py-3.5 text-[14px] text-ink">
            <TriangleAlert size={16} className="mr-2 inline text-warn" />
            {assessment.reason}
          </p>
        ) : null}

        {assessment.unassessed_area_ha > 0 ? (
          <Notice tone="warn" icon={<CircleHelp size={16} />} className="mx-5 mb-5">
            {formatArea(assessment.unassessed_area_ha)} не оценено — по этим полям наблюдений
            не хватило. Их площадь не занижает индекс, но понижает достоверность заключения.
          </Notice>
        ) : null}

        {assessment.notes.length > 0 ? (
          <ul className="mx-5 mb-5 space-y-1.5 text-[13.5px] text-ink-muted">
            {assessment.notes.map((note) => (
              <li key={note}>· {note}</li>
            ))}
          </ul>
        ) : null}
      </Card>

      <div className="mt-4 grid grid-cols-2 gap-4">
        {/* --- поля --- */}
        <Card className="flex flex-col">
          <CardHeader
            title="Поля хозяйства"
            subtitle="В порядке очереди на осмотр"
            action={
              <Button size="sm" variant="ghost" asChild>
                <Link to={`/p/${project.id}/fields`}>Добавить</Link>
              </Button>
            }
          />
          <div className="space-y-2 p-5 pt-3">
            {summary.data.fields.length === 0 ? (
              <EmptyState
                icon={<Building2 size={20} />}
                title="У хозяйства пока нет полей"
                description="Нарисуйте контур на карте и выберите это хозяйство в карточке поля."
              />
            ) : (
              summary.data.fields.map((row) => (
                <FieldRow
                  key={row.field_id}
                  row={row}
                  href={`/p/${project.id}/field/${row.field_id}`}
                />
              ))
            )}
          </div>
        </Card>

        {/* --- карта --- */}
        <Card className="flex flex-col">
          <CardHeader title="Угодья на карте" />
          <div className="m-5 mt-3 flex-1 overflow-hidden rounded-xl border border-line">
            <MapCanvas basemap="satellite" className="min-h-[320px]">
              <FitBounds bounds={bounds} padding={30} />
              {summary.data.fields.map((row) => {
                const geometry = geometryOf.get(row.field_id);
                if (!geometry) return null;
                const style = statusOf(row.status);
                return (
                  <FieldShape
                    key={row.field_id}
                    geometry={geometry}
                    index={indexOf(row.field_id)}
                    style={{ color: style.map, fillOpacity: 0.55, weight: 2.5 }}
                    label={`${row.name} · ${style.title}`}
                    onClick={() => navigate(`/p/${project.id}/field/${row.field_id}`)}
                  />
                );
              })}
            </MapCanvas>
          </div>
        </Card>
      </div>

      {/* --- документы --- */}
      <Card className="mt-4">
        <CardHeader
          title="Отчёты по хозяйству"
          subtitle="Заключения и отчёты по его полям. Скачивается сохранённая версия, а не пересобранная"
        />
        <div className="px-5 pb-5 pt-1">
          {(reports.data ?? []).length === 0 ? (
            <EmptyState
              icon={<FileText size={20} />}
              title="Документов пока нет"
              description="Сформируйте заключение — оно останется в этом списке."
            />
          ) : (
            <ul className="divide-y divide-line-soft">
              {(reports.data ?? []).map((report) => (
                <ReportRow key={report.id} report={report} />
              ))}
            </ul>
          )}
        </div>
      </Card>

      <div className="mt-4 flex justify-end">
        <Button variant="ghost" onClick={() => setConfirmDelete(true)}>
          <Trash2 size={17} />
          Удалить хозяйство
        </Button>
      </div>

      <FarmEditDialog
        open={editing}
        onOpenChange={setEditing}
        mode="edit"
        initial={{
          name: farm.name,
          legal_form: farm.legal_form,
          inn: farm.inn,
          district: farm.district,
          region: farm.region,
          contact: farm.contact,
        }}
        saving={updateFarm.isPending}
        error={(updateFarm.error as Error | null)?.message ?? null}
        onSubmit={(draft: FarmDraft) =>
          updateFarm.mutate(
            { farmId: farm.id, payload: draft },
            { onSuccess: () => setEditing(false) },
          )
        }
      />

      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title={`Удалить «${farm.name}»?`}
        description={
          farmFields.length > 0
            ? `${farmFields.length} ${fieldsWord(farmFields.length)} останутся в проекте без хозяйства и выпадут из реестра. Собранные снимки и результаты анализа сохранятся.`
            : "У хозяйства нет полей — удаление ни на что не повлияет."
        }
        confirmLabel="Удалить"
        onConfirm={() =>
          deleteFarm.mutate(farm.id, {
            onSuccess: () => navigate(`/p/${project.id}/farms`),
          })
        }
      />
    </div>
  );
}

function Metric({
  value,
  label,
  valueClass,
}: {
  value: string;
  label: string;
  valueClass?: string;
}) {
  return (
    <div className="px-5 py-4">
      <p className={cn("text-[26px] font-semibold leading-none text-ink tnum", valueClass)}>
        {value}
      </p>
      <p className="mt-2 text-[13.5px] leading-snug text-ink-soft">{label}</p>
    </div>
  );
}

function FieldRow({ row, href }: { row: FieldSummary; href: string }) {
  const style = statusOf(row.status);
  return (
    <Link
      to={href}
      className="flex items-center gap-3.5 rounded-xl border border-line px-4 py-3 transition-colors hover:border-[#D6DAE0]"
    >
      <span className="w-6 shrink-0 text-[14px] font-semibold text-ink-muted tnum">
        {row.inspection_rank ?? "—"}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[15px] font-medium text-ink">{row.name}</span>
        <span className="block text-[13px] text-ink-muted">
          {formatArea(row.area_ha)} · {row.crop ?? "культура не указана"}
        </span>
      </span>
      <Chip size="sm" className={cn("shrink-0", style.chip)}>
        {style.title}
      </Chip>
      <span
        className={cn("w-10 shrink-0 text-right text-[18px] font-semibold tnum", riskTone(row.risk_score))}
      >
        {row.risk_score === null ? "—" : Math.round(row.risk_score)}
      </span>
    </Link>
  );
}

const REPORT_KIND_TITLES: Record<GeneratedReport["kind"], string> = {
  field: "Отчёт по полю",
  farm: "Заключение по хозяйству",
  project: "Сводка по проекту",
  registry: "Реестр поддержки",
};

function ReportRow({ report }: { report: GeneratedReport }) {
  const [busy, setBusy] = useState(false);
  return (
    <li className="flex items-center gap-4 py-3">
      <FileText size={18} className="shrink-0 text-ink-muted" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[14.5px] font-medium text-ink">{report.title}</span>
        <span className="block text-[13px] text-ink-muted">
          {REPORT_KIND_TITLES[report.kind]} · {formatDate(report.created_at)}
          {report.pages ? ` · ${report.pages} ${pagesWord(report.pages)}` : ""}
          {report.size_bytes ? ` · ${formatBytes(report.size_bytes)}` : ""}
        </span>
      </span>
      <Button
        size="sm"
        variant="outline"
        disabled={busy}
        onClick={() => {
          setBusy(true);
          void downloadFile(`/reports/${report.id}/download`).finally(() => setBusy(false));
        }}
      >
        <Download size={15} />
        Скачать
      </Button>
    </li>
  );
}
