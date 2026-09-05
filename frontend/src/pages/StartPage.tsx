import { useEffect, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { useCreateProject } from "@/api/queries";
import { Loading, ErrorState } from "@/components/ui/State";
import { Button } from "@/components/ui/Button";
import { loadProjectId, saveProjectId } from "@/lib/project";
import { toIsoDate } from "@/lib/format";

/** Точка входа. Регистрации в сервисе нет: проект создаётся сам,
 *  а его идентификатор остаётся у браузера — по нему пользователь
 *  возвращается к своим результатам. */
export function StartPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const createProject = useCreateProject();
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    // «Новый анализ» приходит с ?new=1 — прежний проект не трогаем,
    // его результаты остаются доступными по прямой ссылке.
    const existing = params.get("new") ? null : loadProjectId();
    if (existing) {
      navigate(`/p/${existing}/fields`, { replace: true });
      return;
    }

    const to = new Date();
    const from = new Date();
    from.setDate(from.getDate() - 120);

    createProject.mutate(
      { period_from: toIsoDate(from), period_to: toIsoDate(to) },
      {
        onSuccess: (project) => {
          saveProjectId(project.id);
          navigate(`/p/${project.id}/fields`, { replace: true });
        },
      },
    );
  }, [createProject, navigate, params]);

  if (createProject.isError) {
    return (
      <div className="mx-auto max-w-xl px-6 py-24">
        <ErrorState
          title="Не удалось создать проект"
          error={createProject.error}
          action={
            <Button onClick={() => window.location.reload()}>Повторить</Button>
          }
        />
      </div>
    );
  }

  return <Loading text="Готовим рабочее пространство" className="h-screen" />;
}
