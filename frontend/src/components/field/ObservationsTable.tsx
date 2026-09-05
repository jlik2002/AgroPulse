import { ChevronLeft, ChevronRight, CircleHelp, Info } from "lucide-react";
import { useMemo, useState } from "react";

import type { Observation, ValueType } from "@/api/types";
import { ValueTypeMark } from "@/components/field/ValueTypeMark";
import { Chip } from "@/components/ui/Chip";
import { Select } from "@/components/ui/Select";
import { Tooltip } from "@/components/ui/Tooltip";
import { cn } from "@/lib/cn";
import { formatDate, formatNumber, formatPercent } from "@/lib/format";
import { VALUE_TYPE } from "@/lib/status";

export type ColumnKey =
  | "ndvi"
  | "ndmi"
  | "evi"
  | "temperature"
  | "precipitation"
  | "coverage"
  | "zscore"
  | "source";

export const COLUMN_TITLES: Record<ColumnKey, string> = {
  ndvi: "NDVI",
  ndmi: "NDMI",
  evi: "EVI",
  temperature: "Температура",
  precipitation: "Осадки",
  coverage: "Покрытие",
  zscore: "Отклонение z",
  source: "Источник",
};

export const DEFAULT_COLUMNS: ColumnKey[] = [
  "ndvi",
  "ndmi",
  "temperature",
  "precipitation",
  "coverage",
  "source",
];

interface ObservationsTableProps {
  observations: Observation[];
  columns: ColumnKey[];
  pageSize: number;
  onPageSizeChange: (size: number) => void;
}

/** Таблица исходных и рассчитанных значений.
 *
 *  Для отсутствующего наблюдения всегда показывается причина: голый дефис
 *  оставлял бы пользователя гадать, ошибка это или облачность. */
export function ObservationsTable({
  observations,
  columns,
  pageSize,
  onPageSizeChange,
}: ObservationsTableProps) {
  const [page, setPage] = useState(0);

  const total = observations.length;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const current = Math.min(page, pages - 1);
  const rows = useMemo(
    () => observations.slice(current * pageSize, current * pageSize + pageSize),
    [observations, current, pageSize],
  );

  return (
    <div>
      <div className="overflow-x-auto scroll-thin">
        <table className="w-full min-w-[900px] border-collapse">
          <thead>
            <tr className="border-b border-line text-left">
              <Th className="w-[130px]">Дата</Th>
              <Th className="w-[190px]">Тип значения</Th>
              {columns.map((column) => (
                <Th key={column} className={column === "source" ? "w-[140px]" : "w-[110px]"}>
                  <span className="flex items-center gap-1.5">
                    {COLUMN_TITLES[column]}
                    {HINTS[column] ? (
                      <Tooltip content={HINTS[column]}>
                        <span className="text-ink-muted">
                          <Info size={13} />
                        </span>
                      </Tooltip>
                    ) : null}
                  </span>
                </Th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.date}-${row.value_type}`} className="border-b border-line-soft">
                <Td className="font-medium">{formatDate(row.date)}</Td>
                <Td>
                  <span className="flex items-center gap-2.5">
                    <ValueTypeMark type={row.value_type} />
                    <Chip size="sm" className={VALUE_TYPE[row.value_type].chip}>
                      {VALUE_TYPE[row.value_type].title}
                    </Chip>
                  </span>
                </Td>
                {columns.map((column) => (
                  <Td key={column} className="tnum">
                    <Cell row={row} column={column} />
                  </Td>
                ))}
              </tr>
            ))}
            {rows.length === 0 ? (
              <tr>
                <td colSpan={columns.length + 2} className="py-10 text-center text-[14px] text-ink-muted">
                  Под выбранные фильтры не подошло ни одно значение
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center gap-4 border-t border-line px-1 pt-4">
        <p className="flex items-center gap-2 text-[13px] text-ink-muted">
          <CircleHelp size={15} />
          Покрытие — доля площади поля, по которой удалось получить пригодные пиксели.
        </p>

        <div className="ml-auto flex items-center gap-3">
          <span className="text-[13.5px] text-ink-soft tnum">
            {total === 0
              ? "0 из 0"
              : `${current * pageSize + 1}–${Math.min(total, (current + 1) * pageSize)} из ${total}`}
          </span>
          <Select
            className="h-9 w-[140px]"
            ariaLabel="Строк на странице"
            value={String(pageSize)}
            options={[10, 20, 50, 100].map((size) => ({
              value: String(size),
              label: `По ${size} строк`,
            }))}
            onChange={(value) => {
              onPageSizeChange(Number(value));
              setPage(0);
            }}
          />
          <div className="flex gap-2">
            <PageButton
              label="Предыдущая страница"
              disabled={current === 0}
              onClick={() => setPage(current - 1)}
            >
              <ChevronLeft size={17} />
            </PageButton>
            <PageButton
              label="Следующая страница"
              disabled={current >= pages - 1}
              onClick={() => setPage(current + 1)}
            >
              <ChevronRight size={17} />
            </PageButton>
          </div>
        </div>
      </div>
    </div>
  );
}

const HINTS: Partial<Record<ColumnKey, string>> = {
  ndvi: "Нормализованный вегетационный индекс: (NIR − RED) / (NIR + RED).",
  ndmi: "Индекс влагосодержания: (NIR − SWIR) / (NIR + SWIR). Реагирует на водный стресс раньше NDVI.",
  coverage: "Доля площади поля с пригодными пикселями после маски облаков и теней.",
  zscore: "Отклонение от собственной нормы поля в стандартных отклонениях.",
};

function Cell({ row, column }: { row: Observation; column: ColumnKey }) {
  switch (column) {
    case "ndvi":
      return <>{formatNumber(row.ndvi_mean)}</>;
    case "ndmi":
      return <>{formatNumber(row.ndmi_mean)}</>;
    case "evi":
      return <>{formatNumber(row.evi_mean)}</>;
    case "temperature":
      return <>{row.temperature === null ? "—" : `${formatNumber(row.temperature, 0)}°C`}</>;
    case "precipitation":
      return <>{row.precipitation === null ? "—" : `${formatNumber(row.precipitation, 0)} мм`}</>;
    case "zscore":
      return (
        <span className={row.ndvi_zscore !== null && row.ndvi_zscore < -1 ? "text-danger-ink" : ""}>
          {formatNumber(row.ndvi_zscore)}
        </span>
      );
    case "source":
      return <span className="text-ink-soft">{sourceTitle(row)}</span>;
    case "coverage":
      return <Coverage row={row} />;
    default:
      return <>—</>;
  }
}

/** Покрытие: либо доля пригодных пикселей, либо причина её отсутствия. */
function Coverage({ row }: { row: Observation }) {
  // Снимок есть, но пригодных пикселей не нашлось — доля покрытия сама по себе
  // ничего не объясняет, поэтому рядом идёт причина.
  if (row.valid_fraction !== null && row.ndvi_mean === null) {
    return (
      <Tooltip content={row.missing_reason ?? "Снимок непригоден: пригодных пикселей нет"}>
        <span className="cursor-help border-b border-dashed border-ink-faint text-ink-soft">
          {formatPercent(row.valid_fraction)}
        </span>
      </Tooltip>
    );
  }
  if (row.valid_fraction !== null) return <>{formatPercent(row.valid_fraction)}</>;

  if (row.value_type === "forecast") {
    return (
      <span className="flex flex-col leading-tight">
        <span className="text-ink-muted">—</span>
        <span className="text-[12px] text-ink-muted">будущая дата</span>
      </span>
    );
  }

  const reason = row.missing_reason ?? "Снимок отсутствует";
  const cloud =
    row.cloud_fraction !== null ? `Облачность ${formatPercent(row.cloud_fraction)}` : reason;

  return (
    <Tooltip
      content={
        <span>
          {reason}
          {row.value_type === "restored" ? <br /> : null}
          {row.value_type === "restored" ? "Значение восстановлено моделью." : null}
        </span>
      }
    >
      <span className="cursor-help border-b border-dashed border-ink-faint text-ink-soft">
        {cloud}
      </span>
    </Tooltip>
  );
}

/** Коды источников пришли из пайплайна; пользователю нужен смысл, а не код. */
const SOURCE_TITLES: Record<string, string> = {
  s2_gee: "Sentinel-2",
  s2_stac: "Sentinel-2 (STAC)",
  open_meteo: "Open-Meteo",
};

function sourceTitle(row: Observation): string {
  if (row.value_type === "forecast") return "Прогноз";
  if (row.value_type === "restored") return "Модель";
  return SOURCE_TITLES[row.source] ?? row.source ?? "Sentinel-2";
}

function Th({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <th
      className={cn(
        "px-3 pb-3 pt-1 text-[13.5px] font-medium text-ink-soft first:pl-1",
        className,
      )}
    >
      {children}
    </th>
  );
}

function Td({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <td className={cn("px-3 py-3.5 text-[14px] text-ink first:pl-1", className)}>{children}</td>
  );
}

function PageButton({
  children,
  disabled,
  label,
  onClick,
}: {
  children: React.ReactNode;
  disabled: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="flex h-9 w-9 items-center justify-center rounded-lg border border-line bg-white text-ink transition-colors hover:bg-[#F3F4F6] disabled:opacity-40"
    >
      {children}
    </button>
  );
}

export type { ValueType };
