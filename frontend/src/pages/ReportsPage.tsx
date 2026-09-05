import {
  ArrowLeft,
  CalendarDays,
  Check,
  ChevronLeft,
  ChevronRight,
  Download,
  FileText,
  Info,
  Minus,
  Plus,
  Shield,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { fetchBlob } from "@/api/client";
import { useProjectContext } from "@/app/ProjectContext";
import { ReportPreview } from "@/components/report/ReportPreview";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { Checkbox } from "@/components/ui/Checkbox";
import { Chip } from "@/components/ui/Chip";
import { Segmented } from "@/components/ui/Segmented";
import { Select } from "@/components/ui/Select";
import { EmptyState, ErrorState, Notice, Spinner } from "@/components/ui/State";
import { useFieldAnalysis } from "@/hooks/useFieldAnalysis";
import { cn } from "@/lib/cn";
import {
  formatArea,
  formatBytes,
  formatDate,
  formatPeriod,
  pagesWord,
  plural,
} from "@/lib/format";

type ReportKind = "field" | "project";

interface SectionOption {
  key: string;
  label: string;
}

const FIELD_SECTIONS: SectionOption[] = [
  { key: "summary", label: "Краткий вывод" },
  { key: "state", label: "Состояние поля и снимки" },
  { key: "dynamics", label: "Динамика NDVI" },
  { key: "anomalies", label: "Найденные аномалии" },
  { key: "forecast", label: "Прогноз на 14 дней" },
  { key: "quality", label: "Качество данных" },
  { key: "table", label: "Полная таблица значений" },
];

// Оценка объёма документа до его сборки. Пропорции сняты с готовых отчётов:
// примерно два раздела на страницу и девять строк таблицы на страницу.
// Точное число приходит с готовым PDF и замещает оценку.
const SECTIONS_PER_PAGE = 2;
const TABLE_ROWS_PER_PAGE = 9;

/** Разделы сводного отчёта заданы его вёрсткой и не настраиваются. */
const PROJECT_SECTIONS = [
  "Итоги по проекту",
  "Очередь на осмотр",
  "Поля без надёжной оценки",
  "Проблемные поля подробнее",
  "Методика и ограничения",
];

interface ReadyReport {
  url: string;
  name: string;
  size: number;
  pages: number | null;
  createdAt: Date;
}

/** Настройка, предпросмотр и скачивание PDF-отчёта.
 *  После генерации настройки заменяются карточкой готового файла. */
export function ReportsPage() {
  const { project, fields } = useProjectContext();
  const [params] = useSearchParams();

  const [kind, setKind] = useState<ReportKind>("field");
  // Храним только явный выбор пользователя: список полей приезжает запросом,
  // и вычисленное один раз начальное значение осталось бы пустым навсегда.
  const [chosenField, setChosenField] = useState<string | null>(null);
  const [client, setClient] = useState("");
  const [sections, setSections] = useState<string[]>(
    FIELD_SECTIONS.filter((section) => section.key !== "table").map((section) => section.key),
  );
  const [zoom, setZoom] = useState(75);
  const [activePage, setActivePage] = useState(1);
  const [ready, setReady] = useState<ReadyReport | null>(null);
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const fieldId = chosenField ?? params.get("field") ?? fields[0]?.id ?? "";
  const analysis = useFieldAnalysis(kind === "field" ? fieldId : undefined);

  // Объектный URL живёт до смены документа: без освобождения браузер
  // держал бы в памяти каждый сформированный отчёт.
  useEffect(() => {
    if (!ready) return;
    return () => URL.revokeObjectURL(ready.url);
  }, [ready]);

  const structure = useMemo(
    () =>
      kind === "project"
        ? PROJECT_SECTIONS
        : FIELD_SECTIONS.filter((section) => sections.includes(section.key)).map(
            (section) => section.label,
          ),
    [kind, sections],
  );

  const estimatedPages = useMemo(() => {
    if (kind === "project") return Math.max(2, Math.ceil(fields.length / 6) + 2);

    const chosen = sections.filter((key) => key !== "table").length;
    const tablePages = sections.includes("table")
      ? Math.ceil(analysis.series.all.length / TABLE_ROWS_PER_PAGE)
      : 0;

    // Обложка плюс разделы плюс таблица значений, если она включена.
    return Math.max(1, Math.ceil(chosen / SECTIONS_PER_PAGE) + 1 + tablePages);
  }, [kind, sections, fields.length, analysis.series.all.length]);

  const totalPages = ready?.pages ?? estimatedPages;

  const build = async () => {
    setBuilding(true);
    setError(null);
    try {
      const path =
        kind === "field"
          ? `/fields/${fieldId}/report.pdf`
          : `/projects/${project.id}/report.pdf`;
      const query =
        kind === "field"
          ? { client: client || undefined, sections: sections.join(",") }
          : { client: client || undefined };

      const result = await fetchBlob(path, query);
      setReady({
        url: URL.createObjectURL(result.blob),
        name: result.name,
        size: result.blob.size,
        pages: result.pages,
        createdAt: new Date(),
      });
      setActivePage(1);
    } catch (cause) {
      setError(cause);
    } finally {
      setBuilding(false);
    }
  };

  const download = () => {
    if (!ready) return;
    const link = document.createElement("a");
    link.href = ready.url;
    link.download = ready.name;
    document.body.appendChild(link);
    link.click();
    link.remove();
  };

  if (fields.length === 0) {
    return (
      <div className="px-9 py-7">
        <Card>
          <EmptyState
            title="Отчёт формируется по результатам анализа"
            description="Добавьте поля на карте и запустите анализ — после этого здесь можно будет собрать документ."
            action={
              <Button asChild>
                <Link to={`/p/${project.id}/fields`}>Перейти к полям</Link>
              </Button>
            }
          />
        </Card>
      </div>
    );
  }

  return (
    <div className="px-9 py-7">
      <div className="flex items-start justify-between gap-8">
        <div>
          <h1 className="text-[30px] font-semibold leading-tight text-ink">
            {ready ? "Отчёт готов" : "Новый отчёт"}
          </h1>
          <p className="mt-1.5 text-[15px] text-ink-muted">
            {ready
              ? "Документ сформирован и готов к скачиванию"
              : "Настройте содержание и проверьте документ перед скачиванием"}
          </p>
        </div>
        <Chip
          className={ready ? "bg-ok-soft text-ok-ink" : "bg-[#F1F2F4] text-ink-soft"}
          dot={ready ? "bg-ok" : undefined}
        >
          {ready ? "Готов" : "Черновик"}
        </Chip>
      </div>

      <div className="mt-5 grid grid-cols-[400px_1fr] gap-4">
        {/* --- левая колонка --- */}
        <div className="space-y-4">
          {ready ? (
            <>
              <Card className="flex items-center gap-4 border-ok-line bg-ok-soft px-5 py-5">
                <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full border-2 border-ok text-ok">
                  <Check size={28} strokeWidth={2.6} />
                </span>
                <span>
                  <span className="block text-[18px] font-semibold text-ink">
                    PDF успешно сформирован
                  </span>
                  <span className="mt-0.5 block text-[14px] text-ink-soft">
                    Все выбранные разделы добавлены в документ.
                  </span>
                </span>
              </Card>

              <Card className="px-5 py-5">
                <h2 className="text-[18px] font-semibold text-ink">Файл отчёта</h2>

                <div className="mt-4 flex items-start gap-4">
                  <span className="flex h-14 w-11 shrink-0 items-center justify-center rounded-lg border border-danger-line bg-danger-tint text-[11px] font-bold text-danger">
                    PDF
                  </span>
                  <p className="min-w-0 break-words text-[16px] font-medium text-ink">
                    {ready.name}
                  </p>
                </div>

                <dl className="mt-4 space-y-2.5 text-[14px] text-ink-soft">
                  <Row icon={<FileText size={17} />}>
                    {ready.pages ?? estimatedPages} {pagesWord(ready.pages ?? estimatedPages)}
                  </Row>
                  <Row icon={<Download size={17} />}>{formatBytes(ready.size)}</Row>
                  <Row icon={<CalendarDays size={17} />}>
                    Создан {formatDate(ready.createdAt)} в{" "}
                    {ready.createdAt.toLocaleTimeString("ru-RU", {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </Row>
                  <Row icon={<Info size={17} />}>Язык: русский</Row>
                </dl>

                <Button size="lg" block className="mt-5" onClick={download}>
                  <Download size={18} />
                  Скачать PDF
                </Button>
                <Button
                  variant="outline"
                  size="lg"
                  block
                  className="mt-3"
                  onClick={() => {
                    setReady(null);
                    setError(null);
                  }}
                >
                  <Plus size={18} />
                  Создать ещё один отчёт
                </Button>
                <Link
                  to={`/p/${project.id}/summary`}
                  className="mt-4 flex items-center gap-2.5 text-[14px] font-medium text-ink-soft hover:text-brand-700"
                >
                  <ArrowLeft size={17} />
                  Вернуться к сводке
                </Link>
              </Card>

              <Notice icon={<Shield size={17} />} tone="info">
                Данные и выводы в отчёте соответствуют расчёту от{" "}
                {formatDate(ready.createdAt)}.
              </Notice>
            </>
          ) : (
            <Card className="px-5 py-5">
              <h2 className="text-[18px] font-semibold text-ink">Настройки отчёта</h2>

              <Label>Тип отчёта</Label>
              <Segmented
                className="w-full [&>button]:flex-1"
                value={kind}
                options={[
                  { value: "field", label: "По одному полю" },
                  { value: "project", label: "Сводный отчёт" },
                ]}
                onChange={(value) => setKind(value as ReportKind)}
              />

              {kind === "field" ? (
                <>
                  <Label>Поле</Label>
                  <Select
                    value={fieldId}
                    onChange={setChosenField}
                    ariaLabel="Поле отчёта"
                    options={fields.map((field) => ({
                      value: field.id,
                      label: `${field.name} · ${formatArea(field.area_ha)}`,
                    }))}
                  />
                </>
              ) : null}

              <Label>Клиент или хозяйство</Label>
              <input
                value={client}
                onChange={(event) => setClient(event.target.value)}
                placeholder="ООО «Северное»"
                className="h-11 w-full rounded-xl border border-line px-3.5 text-[14px] text-ink outline-none transition-colors focus:border-brand-400"
              />

              <Label>Период отчёта</Label>
              <span className="flex h-11 items-center gap-2.5 rounded-xl border border-line bg-white px-3.5 text-[14px] text-ink">
                <CalendarDays size={17} className="text-ink-muted" />
                {formatPeriod(project.period_from, project.period_to)}
              </span>

              <Label>Включить в отчёт</Label>
              {kind === "field" ? (
                <div className="space-y-2.5">
                  {FIELD_SECTIONS.map((section) => (
                    <Checkbox
                      key={section.key}
                      label={section.label}
                      checked={sections.includes(section.key)}
                      onChange={(checked) =>
                        setSections((previous) =>
                          checked
                            ? FIELD_SECTIONS.filter(
                                (item) =>
                                  previous.includes(item.key) || item.key === section.key,
                              ).map((item) => item.key)
                            : previous.filter((key) => key !== section.key),
                        )
                      }
                    />
                  ))}
                </div>
              ) : (
                <ul className="space-y-2 text-[14px] text-ink-soft">
                  {PROJECT_SECTIONS.map((title) => (
                    <li key={title} className="flex items-center gap-2.5">
                      <Check size={15} className="text-brand-700" />
                      {title}
                    </li>
                  ))}
                </ul>
              )}

              <Label>Язык отчёта</Label>
              <Select
                value="ru"
                ariaLabel="Язык отчёта"
                options={[{ value: "ru", label: "Русский" }]}
                onChange={() => undefined}
              />

              <Notice className="mt-4" icon={<Info size={16} />}>
                Предварительно: {estimatedPages} {pagesWord(estimatedPages)}
              </Notice>

              {error ? <ErrorState className="mt-3" error={error} /> : null}

              <Button
                size="lg"
                block
                className="mt-4"
                disabled={building || (kind === "field" && !fieldId) || sections.length === 0}
                onClick={build}
              >
                {building ? <Spinner className="text-white" /> : <FileText size={18} />}
                {building ? "Формируем PDF…" : "Сформировать PDF"}
              </Button>
            </Card>
          )}
        </div>

        {/* --- предпросмотр --- */}
        <Card className="flex flex-col">
          <CardHeader
            title={ready ? "Предпросмотр отчёта" : "Предпросмотр"}
            subtitle={
              ready ? undefined : (
                <span className="flex items-center gap-2">
                  <span className="h-1.5 w-1.5 rounded-full bg-ok" />
                  Обновляется автоматически
                </span>
              )
            }
            action={
              ready ? (
                <span className="flex items-center gap-3">
                  <span className="rounded-lg border border-line px-3 py-1.5 text-[13.5px] text-ink tnum">
                    {activePage} / {totalPages}
                  </span>
                  <Button variant="outline" size="icon" aria-label="Скачать PDF" onClick={download}>
                    <Download size={17} />
                  </Button>
                </span>
              ) : undefined
            }
          />

          <div className="flex min-h-0 flex-1 gap-4 p-5 pt-4">
            <div className="flex min-h-0 flex-1 items-start justify-center overflow-auto rounded-xl bg-[#F5F6F7] p-6 scroll-thin">
              {ready ? (
                <iframe
                  title="Предпросмотр отчёта"
                  src={`${ready.url}#page=${activePage}&view=FitH&toolbar=0`}
                  className="h-[560px] w-full rounded-lg border border-line bg-white shadow-card"
                />
              ) : kind === "project" ? (
                <ProjectPreviewStub fieldsCount={fields.length} client={client} />
              ) : analysis.isPending ? (
                <div className="flex h-[560px] items-center gap-2.5 text-ink-muted">
                  <Spinner />
                  Готовим предпросмотр
                </div>
              ) : (
                <div
                  className="origin-top overflow-hidden rounded-lg border border-line bg-white shadow-card"
                  style={{
                    width: 640,
                    height: 820,
                    transform: `scale(${zoom / 100})`,
                  }}
                >
                  <ReportPreview
                    field={analysis.field.data ?? null}
                    client={client}
                    periodFrom={project.period_from}
                    periodTo={project.period_to}
                    risk={analysis.risk.data}
                    anomaly={analysis.worst}
                    observations={analysis.series.historical}
                    latest={analysis.latest}
                    deviation={analysis.deviation}
                    peakRisk={analysis.peakRisk}
                    totalPages={totalPages}
                    sections={sections}
                  />
                </div>
              )}
            </div>

            <aside className="w-[230px] shrink-0">
              <p className="mb-3 text-[15px] font-medium text-ink">
                Структура{" "}
                <span className="text-ink-muted">
                  {/* Разделы и страницы — разные величины: один раздел может
                      занять и половину страницы, и десяток. Число страниц
                      живёт рядом с предпросмотром. */}
                  · {structure.length} {plural(structure.length, "раздел", "раздела", "разделов")}
                </span>
              </p>
              <ul className="space-y-2">
                {structure.map((title, index) => (
                  <li key={title}>
                    <button
                      type="button"
                      onClick={() => setActivePage(Math.min(totalPages, index + 1))}
                      className={cn(
                        "flex w-full items-center gap-3 rounded-xl border px-3.5 py-2.5 text-left text-[14px] transition-colors",
                        activePage === index + 1
                          ? "border-brand-300 bg-brand-50 text-ink"
                          : "border-line bg-white text-ink-soft hover:border-[#D6DAE0]",
                      )}
                    >
                      <span className="w-4 shrink-0 text-ink-muted tnum">{index + 1}</span>
                      <span className="min-w-0 truncate">{title}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </aside>
          </div>

          <div className="flex items-center justify-end gap-3 border-t border-line px-5 py-3.5">
            {!ready ? (
              <div className="flex items-center gap-1">
                <ZoomButton
                  label="Уменьшить масштаб"
                  onClick={() => setZoom((value) => Math.max(50, value - 25))}
                >
                  <Minus size={16} />
                </ZoomButton>
                <span className="w-14 text-center text-[14px] text-ink tnum">{zoom}%</span>
                <ZoomButton
                  label="Увеличить масштаб"
                  onClick={() => setZoom((value) => Math.min(150, value + 25))}
                >
                  <Plus size={16} />
                </ZoomButton>
              </div>
            ) : null}

            <div className="flex gap-2">
              <ZoomButton
                label="Предыдущая страница"
                disabled={activePage <= 1}
                onClick={() => setActivePage((value) => Math.max(1, value - 1))}
              >
                <ChevronLeft size={17} />
              </ZoomButton>
              <ZoomButton
                label="Следующая страница"
                disabled={activePage >= totalPages}
                onClick={() => setActivePage((value) => Math.min(totalPages, value + 1))}
              >
                <ChevronRight size={17} />
              </ZoomButton>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return <p className="mb-2 mt-4 text-[13px] text-ink-soft">{children}</p>;
}

function Row({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="shrink-0 text-ink-muted">{icon}</span>
      {children}
    </div>
  );
}

function ZoomButton({
  children,
  label,
  onClick,
  disabled,
}: {
  children: React.ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      disabled={disabled}
      className="flex h-9 w-9 items-center justify-center rounded-lg border border-line bg-white text-ink transition-colors hover:bg-[#F3F4F6] disabled:opacity-40"
    >
      {children}
    </button>
  );
}

/** Для сводного отчёта живой предпросмотр не строим: он собирает данные
 *  всех полей, и повторять эту вёрстку на клиенте значило бы держать
 *  вторую реализацию документа. Показываем состав будущего документа. */
function ProjectPreviewStub({ fieldsCount, client }: { fieldsCount: number; client: string }) {
  return (
    <div className="flex h-[560px] w-[560px] flex-col rounded-lg border border-line bg-white px-10 py-9 shadow-card">
      <h2 className="text-[24px] font-semibold text-ink">Сводный отчёт по хозяйству</h2>
      <p className="mt-2 text-[13.5px] text-ink-soft">
        {client || "Хозяйство не указано"} · {fieldsCount}{" "}
        {plural(fieldsCount, "поле", "поля", "полей")} в проекте
      </p>
      <ul className="mt-7 space-y-3 text-[14px] text-ink-soft">
        {PROJECT_SECTIONS.map((title) => (
          <li key={title} className="flex items-center gap-3">
            <Check size={16} className="text-brand-700" />
            {title}
          </li>
        ))}
      </ul>
      <p className="mt-auto text-[12.5px] text-ink-muted">
        Точная вёрстка страниц будет видна после формирования PDF.
      </p>
    </div>
  );
}
