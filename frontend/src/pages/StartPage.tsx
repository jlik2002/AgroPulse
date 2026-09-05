import { useEffect, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { useCreateProject, useMyProjects } from "@/api/queries";
import { Loading, ErrorState } from "@/components/ui/State";
import { Button } from "@/components/ui/Button";
import { toIsoDate } from "@/lib/format";

/** Точка входа.
 *
 *  Регистрации в сервисе нет: при первом заходе бэкенд ставит посетителю
 *  cookie с анонимным идентификатором и приписывает к нему созданные проекты.
 *  Поэтому «вернуться к своим результатам» — это запрос к серверу, а не
 *  запись в localStorage: она терялась при чистке браузера, не существовала
 *  в приватном окне и не переезжала на второе устройство, из-за чего сводка
 *  и отчёты после закрытия вкладки оказывались недоступны. */
export function StartPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  // «Новый анализ» приходит с ?new=1: прежние проекты остаются, но открывать
  // нужно чистое рабочее пространство, а не последнее.
  const wantsNew = Boolean(params.get("new"));

  const projects = useMyProjects(!wantsNew);
  const createProject = useCreateProject();
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    // Ждём ответа о существующих проектах: без него мы бы создали лишний
    // и увели пользователя от его данных.
    if (!wantsNew && projects.isPending) return;
    started.current = true;

    const latest = wantsNew ? undefined : projects.data?.[0];
    if (latest) {
      navigate(`/p/${latest.id}/fields`, { replace: true });
      return;
    }

    const to = new Date();
    const from = new Date();
    from.setDate(from.getDate() - 120);

    createProject.mutate(
      { period_from: toIsoDate(from), period_to: toIsoDate(to) },
      {
        onSuccess: (project) => navigate(`/p/${project.id}/fields`, { replace: true }),
      },
    );
  }, [createProject, navigate, projects.isPending, projects.data, wantsNew]);

  if (createProject.isError) {
    return (
      <div className="mx-auto max-w-xl px-6 py-24">
        <ErrorState
          title="Не удалось создать проект"
          error={createProject.error}
          action={<Button onClick={() => window.location.reload()}>Повторить</Button>}
        />
      </div>
    );
  }

  return <Loading text="Готовим рабочее пространство" className="h-screen" />;
}
