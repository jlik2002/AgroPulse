/** Тонкий клиент над fetch.
 *
 *  Базовый адрес по умолчанию относительный — `/api`. В разработке этот путь
 *  проксирует Vite, в собранном образе — nginx. Благодаря этому адрес бэкенда
 *  нигде не зашит в код и запуск по README не требует правок исходников. */

const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "/api";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string | null,
    message: string,
    readonly details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
  query?: Record<string, string | number | boolean | undefined | null>;
}

export function apiUrl(path: string, query?: RequestOptions["query"]): string {
  const url = `${BASE_URL}${path}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") {
      params.append(key, String(value));
    }
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, signal, query } = options;

  const response = await fetch(apiUrl(path, query), {
    method,
    signal,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (!response.ok) {
    throw await toApiError(response);
  }

  // 204 No Content отдают удаление проекта и поля.
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Разбор ошибки бэкенда: он отдаёт `{error: {code, message, details}}`. */
async function toApiError(response: Response): Promise<ApiError> {
  let code: string | null = null;
  let message = `Запрос завершился с кодом ${response.status}`;
  let details: unknown;

  try {
    const payload = await response.json();
    const error = payload?.error ?? payload;
    if (typeof error?.message === "string") message = error.message;
    else if (typeof error?.detail === "string") message = error.detail;
    if (typeof error?.code === "string") code = error.code;
    details = error?.details;
  } catch {
    // Тело может быть пустым или не-JSON — сообщение по коду ответа уже есть.
  }

  return new ApiError(response.status, code, message, details);
}

/** Скачивание файла (CSV, PDF) с сохранением имени из Content-Disposition. */
export async function downloadFile(
  path: string,
  query?: RequestOptions["query"],
  fallbackName = "agropulse",
): Promise<{ name: string; size: number }> {
  const response = await fetch(apiUrl(path, query));
  if (!response.ok) throw await toApiError(response);

  const blob = await response.blob();
  const name = filenameFromDisposition(response.headers.get("Content-Disposition"), fallbackName);

  const href = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = href;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(href);

  return { name, size: blob.size };
}

/** Получить файл, не сохраняя его: нужно для предпросмотра PDF в iframe. */
export async function fetchBlob(
  path: string,
  query?: RequestOptions["query"],
): Promise<{ blob: Blob; name: string; pages: number | null }> {
  const response = await fetch(apiUrl(path, query));
  if (!response.ok) throw await toApiError(response);
  const blob = await response.blob();
  // Число страниц знает только вёрстка PDF, поэтому бэкенд отдаёт его заголовком.
  const pages = Number(response.headers.get("X-Report-Pages"));
  return {
    blob,
    name: filenameFromDisposition(response.headers.get("Content-Disposition"), "report.pdf"),
    pages: Number.isFinite(pages) && pages > 0 ? pages : null,
  };
}

function filenameFromDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback;
  // RFC 5987: бэкенд отдаёт кириллицу как filename*=UTF-8''...
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (encoded) {
    try {
      return decodeURIComponent(encoded[1]);
    } catch {
      return fallback;
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain ? plain[1] : fallback;
}
