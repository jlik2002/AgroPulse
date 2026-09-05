import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { downloadFile } from "@/api/client";
import { useProjectContext } from "@/app/ProjectContext";
import { DataExplorer } from "@/components/field/DataExplorer";
import { DynamicsTab } from "@/components/field/tabs/DynamicsTab";
import { OverviewTab } from "@/components/field/tabs/OverviewTab";
import { ScenesTab } from "@/components/field/tabs/ScenesTab";
import { FieldHeader } from "@/components/field/FieldHeader";
import { Card } from "@/components/ui/Card";
import { ErrorState, Loading } from "@/components/ui/State";
import { useFieldAnalysis } from "@/hooks/useFieldAnalysis";

const TABS = [
  { key: "overview", label: "Обзор" },
  { key: "scenes", label: "Снимки" },
  { key: "dynamics", label: "Динамика" },
  { key: "data", label: "Данные" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

/** Страница поля: обзор, снимки, динамика и таблица значений.
 *  Вкладка живёт в адресной строке — ссылкой на снимки можно поделиться. */
export function FieldPage() {
  const { fieldId = "" } = useParams();
  const navigate = useNavigate();
  const { project } = useProjectContext();
  const [params, setParams] = useSearchParams();
  const [focus, setFocus] = useState<{ from: string; to: string } | null>(null);

  const analysis = useFieldAnalysis(fieldId);
  const tab = (params.get("tab") as TabKey) || "overview";

  const setTab = (next: string) => {
    const updated = new URLSearchParams(params);
    updated.set("tab", next);
    setParams(updated, { replace: true });
  };

  if (analysis.isPending) return <Loading text="Загружаем результаты поля" />;
  if (analysis.isError || !analysis.field.data) {
    return (
      <div className="px-9 py-9">
        <ErrorState
          title="Не удалось открыть поле"
          error={analysis.error}
          action={
            <Link
              to={`/p/${project.id}/summary`}
              className="text-[14px] font-medium text-brand-700 hover:underline"
            >
              Вернуться к сводке
            </Link>
          }
        />
      </div>
    );
  }

  const field = analysis.field.data;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <FieldHeader
        projectId={project.id}
        field={field}
        tabs={TABS}
        activeTab={tab}
        onTabChange={setTab}
        onExportCsv={() =>
          void downloadFile(`/fields/${field.id}/export.csv`, undefined, `${field.name}.csv`)
        }
        onReport={() => navigate(`/p/${project.id}/reports?field=${field.id}`)}
      />

      <div className="px-9 py-6">
        {tab === "overview" ? (
          <OverviewTab analysis={analysis} projectId={project.id} onOpenTab={setTab} />
        ) : null}

        {tab === "scenes" ? (
          <ScenesTab
            analysis={analysis}
            focus={focus}
            onShowOnChart={() => setTab("dynamics")}
          />
        ) : null}

        {tab === "dynamics" ? (
          <DynamicsTab
            analysis={analysis}
            onOpenScenes={(range) => {
              setFocus(range);
              setTab("scenes");
            }}
          />
        ) : null}

        {tab === "data" && analysis.timeseries.data ? (
          <Card className="border-none bg-transparent shadow-none">
            <DataExplorer
              showHeading={false}
              fieldId={field.id}
              fieldName={field.name}
              observations={analysis.series.all}
              periodFrom={analysis.timeseries.data.period_from}
              periodTo={project.period_to}
            />
          </Card>
        ) : null}
      </div>
    </div>
  );
}
