import * as Popover from "@radix-ui/react-popover";
import { CalendarSearch, Download, Settings2, SlidersHorizontal } from "lucide-react";
import { useMemo, useState } from "react";

import { downloadFile } from "@/api/client";
import type { Observation, ValueType } from "@/api/types";
import {
  COLUMN_TITLES,
  DEFAULT_COLUMNS,
  ObservationsTable,
  type ColumnKey,
} from "@/components/field/ObservationsTable";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Checkbox } from "@/components/ui/Checkbox";
import { Select } from "@/components/ui/Select";
import { Segmented } from "@/components/ui/Segmented";
import { ValueTypeMark } from "@/components/field/ValueTypeMark";
import { formatDayMonthLong, formatPeriod, plural } from "@/lib/format";
import { VALUE_TYPE } from "@/lib/status";

type TypeFilter = "all" | ValueType;
type CoverageFilter = "any" | "high" | "medium" | "low";

const TYPE_OPTIONS: { value: TypeFilter; label: string }[] = [
  { value: "all", label: "Все" },
  { value: "observed", label: "Наблюдаемые" },
  { value: "restored", label: "Восстановленные" },
  { value: "forecast", label: "Прогноз" },
];

const COVERAGE_OPTIONS = [
  { value: "any", label: "Любое покрытие" },
  { value: "high", label: "Покрытие ≥ 80%" },
  { value: "medium", label: "Покрытие 50–80%" },
  { value: "low", label: "Покрытие < 50%" },
];

const ALL_COLUMNS: ColumnKey[] = [
  "ndvi",
  "ndmi",
  "evi",
  "temperature",
  "precipitation",
  "coverage",
  "zscore",
  "source",
];

interface DataExplorerProps {
  fieldId: string;
  fieldName: string;
  observations: Observation[];
  periodFrom: string;
  periodTo: string;
  /** Селектор поля показывается только на общем разделе «Данные». */
  fieldSelect?: { value: string; options: { value: string; label: string }[]; onChange: (id: string) => void };
  /** На вкладке поля заголовок раздела не нужен: он уже есть в шапке страницы. */
  showHeading?: boolean;
}

/** Прозрачный доступ ко всем значениям, которыми пользовался сервис.
 *  Фильтры применяются на клиенте: ряд одного поля — это десятки строк. */
export function DataExplorer({
  fieldId,
  fieldName,
  observations,
  periodFrom,
  periodTo,
  fieldSelect,
  showHeading = true,
}: DataExplorerProps) {
  const [type, setType] = useState<TypeFilter>("all");
  const [coverage, setCoverage] = useState<CoverageFilter>("any");
  const [search, setSearch] = useState("");
  const [columns, setColumns] = useState<ColumnKey[]>(DEFAULT_COLUMNS);
  const [pageSize, setPageSize] = useState(10);

  const counts = useMemo(
    () => ({
      observed: observations.filter((row) => row.value_type === "observed").length,
      restored: observations.filter((row) => row.value_type === "restored").length,
      forecast: observations.filter((row) => row.value_type === "forecast").length,
    }),
    [observations],
  );

  const lastObserved = useMemo(
    () =>
      [...observations]
        .filter((row) => row.value_type === "observed")
        .sort((a, b) => a.date.localeCompare(b.date))
        .at(-1) ?? null,
    [observations],
  );

  const filtered = useMemo(
    () =>
      observations
        .filter((row) => (type === "all" ? true : row.value_type === type))
        .filter((row) => matchCoverage(row, coverage))
        .filter((row) => (search ? row.date.includes(normalizeSearch(search)) : true))
        .sort((a, b) => a.date.localeCompare(b.date)),
    [observations, type, coverage, search],
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        {showHeading ? (
          <div>
            <h1 className="text-[30px] font-semibold leading-tight text-ink">Данные</h1>
            <p className="mt-1.5 text-[15px] text-ink-muted">
              Исходные и рассчитанные значения по полям
            </p>
          </div>
        ) : (
          <h2 className="text-[22px] font-semibold text-ink">Исходные и рассчитанные значения</h2>
        )}

        <div className="flex items-center gap-3">
          <Button
            size="lg"
            onClick={() =>
              void downloadFile(`/fields/${fieldId}/export.csv`, undefined, `${fieldName}.csv`)
            }
          >
            <Download size={18} />
            Скачать CSV
          </Button>

          <Popover.Root>
            <Popover.Trigger asChild>
              <Button variant="outline" size="lg">
                <Settings2 size={18} />
                Настроить столбцы
              </Button>
            </Popover.Trigger>
            <Popover.Portal>
              <Popover.Content
                align="end"
                sideOffset={6}
                className="z-[1200] w-64 rounded-xl border border-line bg-white p-4 shadow-pop animate-fade-in"
              >
                <p className="mb-3 text-[13px] font-medium text-ink-soft">Столбцы таблицы</p>
                <div className="space-y-2.5">
                  {ALL_COLUMNS.map((column) => (
                    <Checkbox
                      key={column}
                      label={COLUMN_TITLES[column]}
                      checked={columns.includes(column)}
                      onChange={(checked) =>
                        setColumns((previous) =>
                          checked
                            ? ALL_COLUMNS.filter((item) => previous.includes(item) || item === column)
                            : previous.filter((item) => item !== column),
                        )
                      }
                    />
                  ))}
                </div>
              </Popover.Content>
            </Popover.Portal>
          </Popover.Root>
        </div>
      </div>

      <Card className="flex flex-wrap items-center gap-3 px-5 py-4">
        {fieldSelect ? (
          <Select
            className="h-11 w-[240px]"
            ariaLabel="Поле"
            value={fieldSelect.value}
            options={fieldSelect.options}
            onChange={fieldSelect.onChange}
          />
        ) : null}

        <span className="flex h-11 items-center gap-2.5 rounded-xl border border-line bg-white px-3.5 text-[14px] text-ink">
          <CalendarSearch size={17} className="text-ink-muted" />
          {formatPeriod(periodFrom, periodTo)}
        </span>

        <Segmented
          value={type}
          options={TYPE_OPTIONS}
          onChange={(value) => setType(value as TypeFilter)}
        />

        <Select
          className="h-11 w-[210px]"
          ariaLabel="Качество покрытия"
          value={coverage}
          options={COVERAGE_OPTIONS}
          onChange={(value) => setCoverage(value as CoverageFilter)}
        />

        <label className="flex h-11 min-w-[190px] flex-1 items-center gap-2.5 rounded-xl border border-line bg-white px-3.5">
          <SlidersHorizontal size={17} className="shrink-0 text-ink-muted" />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Найти дату"
            aria-label="Найти дату"
            className="h-full min-w-0 flex-1 bg-transparent text-[14px] text-ink outline-none placeholder:text-ink-muted"
          />
        </label>
      </Card>

      <div className="flex flex-wrap items-center gap-3">
        <span className="text-[15px] text-ink">
          Всего {observations.length}{" "}
          {plural(observations.length, "значение", "значения", "значений")}
        </span>
        <CountChip type="observed" count={counts.observed} />
        <CountChip type="restored" count={counts.restored} />
        <CountChip type="forecast" count={counts.forecast} />
        {lastObserved ? (
          <span className="ml-auto text-[14px] text-ink-muted">
            Последнее наблюдение: {formatDayMonthLong(lastObserved.date)}
          </span>
        ) : null}
      </div>

      <Card className="px-5 py-4">
        <ObservationsTable
          observations={filtered}
          columns={columns}
          pageSize={pageSize}
          onPageSizeChange={setPageSize}
        />
      </Card>
    </div>
  );
}

function CountChip({ type, count }: { type: ValueType; count: number }) {
  const titles: Record<ValueType, string> = {
    observed: plural(count, "наблюдаемое", "наблюдаемых", "наблюдаемых"),
    restored: plural(count, "восстановленное", "восстановленных", "восстановленных"),
    forecast: plural(count, "прогнозное", "прогнозных", "прогнозных"),
  };

  return (
    <span className="flex items-center gap-2 rounded-xl border border-line bg-white px-3 py-1.5">
      <ValueTypeMark type={type} />
      <span className="text-[13.5px] tnum" style={{ color: VALUE_TYPE[type].stroke }}>
        {count} {titles[type]}
      </span>
    </span>
  );
}

function matchCoverage(row: Observation, filter: CoverageFilter): boolean {
  if (filter === "any") return true;
  const value = row.valid_fraction;
  if (value === null) return false;
  if (filter === "high") return value >= 0.8;
  if (filter === "medium") return value >= 0.5 && value < 0.8;
  return value < 0.5;
}

/** Пользователь ищет «12.08» или «12 авг» — приводим к формату дат ряда. */
function normalizeSearch(value: string): string {
  const trimmed = value.trim().toLowerCase();
  const numeric = trimmed.replace(/[^\d]/g, "");
  if (numeric.length === 8) {
    return `${numeric.slice(4, 8)}-${numeric.slice(2, 4)}-${numeric.slice(0, 2)}`;
  }
  if (numeric.length === 4) return `-${numeric.slice(2, 4)}-${numeric.slice(0, 2)}`;
  return trimmed;
}
