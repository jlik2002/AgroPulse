/** Текущий проект хранится у клиента: регистрации в сервисе нет,
 *  идентификатор проекта и есть ключ доступа к результатам. */

const STORAGE_KEY = "agropulse.project";

export function loadProjectId(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    // Приватный режим браузера может запретить хранилище — не повод падать.
    return null;
  }
}

export function saveProjectId(projectId: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, projectId);
  } catch {
    /* пусто */
  }
}

export function clearProjectId(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* пусто */
  }
}
