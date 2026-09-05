/** Форматирование значений в русской локали.
 *
 *  Числа в интерфейсе идут с запятой в дробной части — как на макетах
 *  («NDVI 0,54»). Отдельная функция вместо `toFixed` нужна именно поэтому. */

const MONTHS_SHORT = [
  "янв.", "фев.", "мар.", "апр.", "мая", "июн.",
  "июл.", "авг.", "сен.", "окт.", "ноя.", "дек.",
];

const MONTHS_GENITIVE = [
  "января", "февраля", "марта", "апреля", "мая", "июня",
  "июля", "августа", "сентября", "октября", "ноября", "декабря",
];

export function parseDate(value: string): Date {
  // Даты приходят как YYYY-MM-DD. Разбираем вручную, чтобы браузер не сдвинул
  // их на часовой пояс и «31 августа» не превратилось в «30 августа».
  const [year, month, day] = value.slice(0, 10).split("-").map(Number);
  return new Date(year, (month ?? 1) - 1, day ?? 1);
}

/** 12 авг. 2026 */
export function formatDate(value: string | Date | null | undefined): string {
  if (!value) return "—";
  const date = typeof value === "string" ? parseDate(value) : value;
  return `${pad(date.getDate())} ${MONTHS_SHORT[date.getMonth()]} ${date.getFullYear()}`;
}

/** 12 авг. */
export function formatDayMonth(value: string | Date | null | undefined): string {
  if (!value) return "—";
  const date = typeof value === "string" ? parseDate(value) : value;
  return `${pad(date.getDate())} ${MONTHS_SHORT[date.getMonth()]}`;
}

/** 12 августа */
export function formatDayMonthLong(value: string | Date | null | undefined): string {
  if (!value) return "—";
  const date = typeof value === "string" ? parseDate(value) : value;
  return `${date.getDate()} ${MONTHS_GENITIVE[date.getMonth()]}`;
}

/** 01 май — 31 авг. 2026 */
export function formatPeriod(from: string | null | undefined, to: string | null | undefined): string {
  if (!from || !to) return "—";
  const start = parseDate(from);
  const end = parseDate(to);
  const sameYear = start.getFullYear() === end.getFullYear();
  const left = `${pad(start.getDate())} ${MONTHS_SHORT[start.getMonth()]}${sameYear ? "" : ` ${start.getFullYear()}`}`;
  const right = `${pad(end.getDate())} ${MONTHS_SHORT[end.getMonth()]} ${end.getFullYear()}`;
  return `${left} — ${right}`;
}

/** 05–09 сентября */
export function formatDateRangeShort(from: string, to: string): string {
  const start = parseDate(from);
  const end = parseDate(to);
  if (start.getMonth() === end.getMonth()) {
    return `${pad(start.getDate())}–${pad(end.getDate())} ${MONTHS_GENITIVE[end.getMonth()]}`;
  }
  return `${formatDayMonth(from)} — ${formatDayMonth(to)}`;
}

/** 0,54 — дробное с запятой. */
export function formatNumber(
  value: number | null | undefined,
  digits = 2,
  fallback = "—",
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return fallback;
  return value.toFixed(digits).replace(".", ",");
}

/** 124 га — площадь без дробной части, с неразрывным пробелом в разрядах. */
export function formatArea(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const rounded = value >= 100 ? Math.round(value) : Math.round(value * 10) / 10;
  return `${rounded.toLocaleString("ru-RU")} га`;
}

export function formatPercent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits).replace(".", ",")}%`;
}

/** 4,8 МБ */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  const units = ["КБ", "МБ", "ГБ"];
  let value = bytes / 1024;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${formatNumber(value, 1)} ${units[index]}`;
}

/** Осталось около 1 минуты / 2 минут */
export function formatMinutesLeft(minutes: number): string {
  const rounded = Math.max(1, Math.round(minutes));
  const last = rounded % 10;
  const tens = rounded % 100;
  if (tens >= 11 && tens <= 14) return `${rounded} минут`;
  if (last === 1) return `${rounded} минуты`;
  if (last >= 2 && last <= 4) return `${rounded} минут`;
  return `${rounded} минут`;
}

/** Согласование существительного с числом: 2 поля, 5 полей. */
export function plural(count: number, one: string, few: string, many: string): string {
  const tens = count % 100;
  if (tens >= 11 && tens <= 14) return many;
  const last = count % 10;
  if (last === 1) return one;
  if (last >= 2 && last <= 4) return few;
  return many;
}

export function fieldsWord(count: number): string {
  return plural(count, "поле", "поля", "полей");
}

export function daysWord(count: number): string {
  return plural(count, "день", "дня", "дней");
}

export function pagesWord(count: number): string {
  return plural(count, "страница", "страницы", "страниц");
}

/** Сегодня, 14:32 — подпись времени последнего обновления в шапке. */
export function formatUpdatedAt(value: Date): string {
  const now = new Date();
  const time = `${pad(value.getHours())}:${pad(value.getMinutes())}`;
  const sameDay =
    value.getDate() === now.getDate() &&
    value.getMonth() === now.getMonth() &&
    value.getFullYear() === now.getFullYear();
  return sameDay ? `сегодня, ${time}` : `${formatDate(value)}, ${time}`;
}

export function toIsoDate(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}
