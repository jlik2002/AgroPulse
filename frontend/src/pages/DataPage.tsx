import { useMemo, useState } from "react";

import { useTimeseries } from "@/api/queries";
import { splitSeries } from "@/lib/series";
import { useProjectContext } from "@/app/ProjectContext";
import { DataExplorer } from "@/components/field/DataExplorer";
import { Card } from "@/components/ui/Card";
import { EmptyState, ErrorState, Loading } from "@/components/ui/State";

/** Раздел «Данные»: тот же разбор ряда, но с выбором поля проекта. */
export function DataPage() {
  const { project, fields } = useProjectContext();
  const [selected, setSelected] = useState<string | null>(null);

  const fieldId = selected ?? fields[0]?.id ?? null;
  const timeseries = useTimeseries(fieldId ?? undefined);

  // Тот же отбор, что и на графиках поля: период анализа плюс прогноз.
  const observations = useMemo(
    () => splitSeries(timeseries.data).all,
    [timeseries.data],
  );

  const options = useMemo(
    () =>
      fields.map((field) => ({
        value: field.id,
        label: `Поле: ${field.name}`,
      })),
    [fields],
  );

  if (fields.length === 0) {
    return (
      <div className="px-9 py-7">
        <Card>
          <EmptyState
            title="В проекте нет полей"
            description="Добавьте участок на карте — после анализа здесь появятся все исходные и рассчитанные значения."
          />
        </Card>
      </div>
    );
  }

  if (timeseries.isPending) return <Loading text="Загружаем значения" />;
  if (timeseries.isError) {
    return (
      <div className="px-9 py-7">
        <ErrorState error={timeseries.error} />
      </div>
    );
  }

  return (
    <div className="px-9 py-7">
      <DataExplorer
        fieldId={timeseries.data.field_id}
        fieldName={timeseries.data.field_name}
        observations={observations}
        periodFrom={timeseries.data.period_from}
        periodTo={project.period_to}
        history={timeseries.data.observations}
        fieldSelect={{ value: fieldId ?? "", options, onChange: setSelected }}
      />
    </div>
  );
}
