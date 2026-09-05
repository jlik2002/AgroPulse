import { useCallback, useMemo } from "react";
import { Navigate, Outlet, useLocation, useParams } from "react-router-dom";

import { useFields, useProject } from "@/api/queries";
import { ProjectProvider } from "@/app/ProjectContext";
import { TopNav, type NavItem } from "@/components/layout/TopNav";
import { Loading, ErrorState } from "@/components/ui/State";
import { formatUpdatedAt } from "@/lib/format";

/** Оболочка рабочего пространства: шапка, навигация и общий контекст проекта.
 *
 *  Проект и его поля читаются один раз здесь, а не на каждой странице:
 *  номер поля и период анализа нужны всем экранам сразу. */
export function ProjectLayout() {
  const { projectId = "" } = useParams();
  const location = useLocation();

  const project = useProject(projectId);
  const fields = useFields(projectId);

  const indexOf = useCallback(
    (fieldId: string) => {
      const list = fields.data ?? [];
      const position = list.findIndex((field) => field.id === fieldId);
      return position >= 0 ? position + 1 : 0;
    },
    [fields.data],
  );

  // Обработанным считается любое поле, вышедшее из состояния «в очереди»,
  // в том числе с недостаточными данными: у него намеренно нет балла риска,
  // но именно сводка объясняет, чего не хватило.
  const processed = useMemo(
    () => (fields.data ?? []).some((field) => field.status !== "pending"),
    [fields.data],
  );

  const running = useMemo(
    () => (fields.data ?? []).some((field) => field.status === "pending"),
    [fields.data],
  );

  if (project.isPending) return <Loading text="Открываем проект" className="h-screen" />;

  if (project.isError) {
    return (
      <div className="mx-auto max-w-xl px-6 py-20">
        <ErrorState
          title="Проект не найден"
          error={project.error}
          action={
            <a href="/" className="text-[14px] font-medium text-brand-700 underline-offset-4 hover:underline">
              Начать новый проект
            </a>
          }
        />
      </div>
    );
  }

  const base = `/p/${projectId}`;
  const hasFields = (fields.data ?? []).length > 0;

  // Раздел «Хозяйства» — реестр приоритетной поддержки. Он поднят к полям,
  // а не спрятан под сводку: в государственном сценарии это главный экран,
  // а поле в нём — строка внутри хозяйства.
  //
  // Доступен всегда, в том числе в пустом проекте. Именно оттуда заводят
  // первое хозяйство, и запирать эту страницу до появления полей значило
  // сделать её недостижимой ровно тогда, когда она нужна.
  const items: NavItem[] = [
    { to: `${base}/fields`, label: "Поля" },
    { to: `${base}/farms`, label: "Хозяйства" },
    {
      to: `${base}/summary`,
      label: "Сводка",
      disabled: !processed,
      title: "Сводка появится после первого анализа",
    },
    {
      to: `${base}/data`,
      label: "Данные",
      disabled: !hasFields,
      title: "Добавьте поле, чтобы увидеть данные",
    },
    {
      to: `${base}/reports`,
      label: "Отчёты",
      disabled: !processed,
      title: "Отчёт формируется по результатам анализа",
    },
  ];

  const status = running
    ? { text: "Анализ выполняется", tone: "running" as const }
    : processed
      ? {
          // Время последнего успешного чтения списка полей: именно оно
          // показывает, насколько свежи цифры на экране.
          text: `Обновлено ${formatUpdatedAt(new Date(fields.dataUpdatedAt || Date.now()))}`,
          tone: "ready" as const,
        }
      : { text: "Не запущен", tone: "idle" as const };

  const projectLabel = project.data.name
    ? `Проект · ${project.data.name}`
    : "Новый проект";

  return (
    <ProjectProvider
      value={{
        project: project.data,
        fields: fields.data ?? [],
        indexOf,
        refetchFields: () => void fields.refetch(),
      }}
    >
      <div className="flex min-h-screen flex-col bg-canvas">
        <TopNav items={items} projectLabel={projectLabel} status={status} />
        <main className="flex min-h-0 flex-1 flex-col" key={location.pathname.split("/")[3]}>
          <Outlet />
        </main>
      </div>
    </ProjectProvider>
  );
}

/** `/p/:id` без раздела — открываем карту полей. */
export function ProjectIndexRedirect() {
  const { projectId = "" } = useParams();
  return <Navigate to={`/p/${projectId}/fields`} replace />;
}
