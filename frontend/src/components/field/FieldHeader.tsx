import { ChevronRight, FileText } from "lucide-react";
import { Link } from "react-router-dom";

import type { Field } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";
import { formatArea } from "@/lib/format";

interface FieldHeaderProps {
  projectId: string;
  field: Field;
  tabs: readonly { key: string; label: string }[];
  activeTab: string;
  onTabChange: (key: string) => void;
  onExportCsv: () => void;
  onReport: () => void;
  /** Дополнительный элемент хлебных крошек — например «Прогноз». */
  breadcrumbTail?: string;
}

/** Шапка страницы поля: хлебные крошки, название, площадь и вкладки. */
export function FieldHeader({
  projectId,
  field,
  tabs,
  activeTab,
  onTabChange,
  onExportCsv,
  onReport,
  breadcrumbTail,
}: FieldHeaderProps) {
  return (
    <div className="border-b border-line px-9 pt-5">
      <nav className="flex items-center gap-1.5 text-[13.5px] text-ink-muted">
        <Link to={`/p/${projectId}/summary`} className="hover:text-brand-700">
          Сводка
        </Link>
        <ChevronRight size={14} />
        {breadcrumbTail ? (
          <>
            <Link to={`/p/${projectId}/field/${field.id}`} className="hover:text-brand-700">
              {field.name}
            </Link>
            <ChevronRight size={14} />
            <span className="text-ink-soft">{breadcrumbTail}</span>
          </>
        ) : (
          <span className="text-ink-soft">{field.name}</span>
        )}
      </nav>

      <div className="mt-1.5 flex items-start justify-between gap-8">
        <div>
          <h1 className="text-[30px] font-semibold leading-tight text-ink">{field.name}</h1>
          <p className="mt-1 text-[15px] text-ink-muted">
            {formatArea(field.area_ha)} · {field.crop ?? "Культура не указана"}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-3">
          <Button variant="outline" size="lg" onClick={onExportCsv}>
            <FileText size={18} />
            CSV
          </Button>
          <Button size="lg" onClick={onReport}>
            Отчёт по полю
          </Button>
        </div>
      </div>

      <div className="mt-4 flex items-center gap-7">
        {tabs.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => onTabChange(item.key)}
            className={cn(
              "relative pb-3 text-[15px] transition-colors",
              item.key === activeTab
                ? "font-medium text-brand-700 after:absolute after:inset-x-0 after:bottom-0 after:h-[2.5px] after:rounded-full after:bg-brand-700"
                : "text-ink hover:text-brand-700",
            )}
          >
            {item.label}
          </button>
        ))}
      </div>
    </div>
  );
}
