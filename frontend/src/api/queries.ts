/** Хуки чтения и мутаций поверх react-query.
 *
 *  Ключи собраны в одном месте: после запуска обработки нужно точечно
 *  сбрасывать кэш полей и сводки, а не перезагружать страницу целиком. */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from "@tanstack/react-query";

import { request } from "@/api/client";
import type {
  Anomaly,
  Farm,
  FarmSummary,
  Field,
  Forecast,
  GeneratedReport,
  Parcel,
  PolygonGeometry,
  Project,
  ProjectSummary,
  RadarSeries,
  Region,
  Registry,
  Risk,
  Timeseries,
} from "@/api/types";

export const keys = {
  projects: ["projects"] as const,
  project: (id: string) => ["project", id] as const,
  fields: (projectId: string) => ["fields", projectId] as const,
  field: (id: string) => ["field", id] as const,
  timeseries: (id: string) => ["timeseries", id] as const,
  anomalies: (id: string) => ["anomalies", id] as const,
  radar: (id: string) => ["radar", id] as const,
  risk: (id: string) => ["risk", id] as const,
  forecast: (id: string) => ["forecast", id] as const,
  summary: (projectId: string) => ["summary", projectId] as const,
  // Справочник хозяйств общий, поэтому ключ без проекта.
  farms: ["farms"] as const,
  farm: (id: string) => ["farm", id] as const,
  farmSummary: (projectId: string, farmId: string) =>
    ["farm-summary", projectId, farmId] as const,
  registry: (projectId: string) => ["registry", projectId] as const,
  farmReports: (id: string) => ["farm-reports", id] as const,
  projectReports: (projectId: string) => ["project-reports", projectId] as const,
  regions: (q: string) => ["regions", q] as const,
};

type Options<T> = Omit<UseQueryOptions<T, Error, T, readonly unknown[]>, "queryKey" | "queryFn">;

// --- проект ---------------------------------------------------------------

export function useProject(projectId: string | undefined, options?: Options<Project>) {
  return useQuery({
    queryKey: keys.project(projectId ?? ""),
    queryFn: () => request<Project>(`/projects/${projectId}`),
    enabled: Boolean(projectId),
    ...options,
  });
}

export interface CreateProjectPayload {
  name?: string | null;
  period_from: string;
  period_to: string;
}

/** Проекты этого посетителя. Отбор делает бэкенд по cookie, поэтому
 *  клиенту не нужно ничего помнить самому. */
export function useMyProjects(enabled = true) {
  return useQuery({
    queryKey: keys.projects,
    queryFn: () => request<Project[]>("/projects"),
    enabled,
    // Список читается один раз на входе; держать его свежим незачем.
    staleTime: Infinity,
    retry: 1,
  });
}

export function useCreateProject() {
  return useMutation({
    mutationFn: (payload: CreateProjectPayload) =>
      request<Project>("/projects", { method: "POST", body: payload }),
  });
}

export interface UpdateProjectPayload {
  name?: string | null;
  period_from?: string;
  period_to?: string;
}

export function useUpdateProject(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: UpdateProjectPayload) =>
      request<Project>(`/projects/${projectId}`, { method: "PATCH", body: payload }),
    onSuccess: (project) => client.setQueryData(keys.project(projectId), project),
  });
}

// --- поля -----------------------------------------------------------------

export function useFields(projectId: string | undefined, options?: Options<Field[]>) {
  return useQuery({
    queryKey: keys.fields(projectId ?? ""),
    queryFn: () => request<Field[]>(`/projects/${projectId}/fields`),
    enabled: Boolean(projectId),
    ...options,
  });
}

export function useField(fieldId: string | undefined, options?: Options<Field>) {
  return useQuery({
    queryKey: keys.field(fieldId ?? ""),
    queryFn: () => request<Field>(`/fields/${fieldId}`),
    enabled: Boolean(fieldId),
    ...options,
  });
}

export interface CreateFieldPayload {
  name: string;
  geometry: PolygonGeometry;
  /** Хозяйство-владелец. Обязательно: бэкенд отвечает 422 без него. */
  farm_id: string;
  /** Культура текущего сезона. Обязательна: бэкенд отвечает 422 без неё. */
  crop: string;
  sowing_date?: string | null;
  source?: "drawn" | "osm" | "worldcereal";
  external_ref?: string | null;
}

export function useCreateField(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateFieldPayload) =>
      request<Field>(`/projects/${projectId}/fields`, { method: "POST", body: payload }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: keys.fields(projectId) });
      client.invalidateQueries({ queryKey: keys.registry(projectId) });
    },
  });
}

export interface UpdateFieldPayload {
  name?: string;
  geometry?: PolygonGeometry;
  /** Перенос поля в другое хозяйство. На расчёт не влияет. */
  farm_id?: string;
  crop?: string | null;
  sowing_date?: string | null;
}

export function useUpdateField(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ fieldId, payload }: { fieldId: string; payload: UpdateFieldPayload }) =>
      request<Field>(`/fields/${fieldId}`, { method: "PATCH", body: payload }),
    // Правка контура, культуры или даты посева обесценивает расчёт, и бэкенд
    // ставит поле на пересчёт. Сбрасываем всё, что из этого расчёта выведено,
    // иначе на экране остались бы прежние аномалии, риск и прогноз — а именно
    // так и выглядело «указал культуру, а отчёт прежний».
    onSuccess: (field) => {
      for (const key of [
        keys.fields(projectId),
        keys.field(field.id),
        keys.timeseries(field.id),
        keys.anomalies(field.id),
        keys.radar(field.id),
        keys.risk(field.id),
        keys.forecast(field.id),
        keys.summary(projectId),
        // Перенос поля меняет состав хозяйств, а правка культуры — их баллы:
        // реестр и карточка хозяйства считаются по полям и обязаны обновиться.
        keys.registry(projectId),
      ]) {
        client.invalidateQueries({ queryKey: key });
      }
      client.invalidateQueries({ queryKey: ["farm-summary"] });
    },
  });
}

export function useDeleteField(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (fieldId: string) => request<void>(`/fields/${fieldId}`, { method: "DELETE" }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: keys.fields(projectId) });
      client.invalidateQueries({ queryKey: keys.registry(projectId) });
      client.invalidateQueries({ queryKey: ["farm-summary"] });
    },
  });
}

// --- хозяйства ------------------------------------------------------------

/** Весь справочник хозяйств. Отбора по проекту нет намеренно: одно и то же
 *  предприятие должно быть доступно из любого проекта, иначе его приходится
 *  заводить заново под каждый период наблюдения. */
export function useFarms(options?: Options<Farm[]>) {
  return useQuery({
    queryKey: keys.farms,
    queryFn: () => request<Farm[]>("/farms"),
    ...options,
  });
}

export function useFarm(farmId: string | undefined, options?: Options<Farm>) {
  return useQuery({
    queryKey: keys.farm(farmId ?? ""),
    queryFn: () => request<Farm>(`/farms/${farmId}`),
    enabled: Boolean(farmId),
    ...options,
  });
}

export interface FarmPayload {
  name: string;
  inn?: string | null;
  legal_form?: string | null;
  district?: string | null;
  region?: string | null;
  contact?: string | null;
  note?: string | null;
}

export function useCreateFarm(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: FarmPayload) =>
      request<Farm>("/farms", { method: "POST", body: payload }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: keys.farms });
      client.invalidateQueries({ queryKey: keys.registry(projectId) });
    },
  });
}

export function useUpdateFarm(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ farmId, payload }: { farmId: string; payload: FarmPayload }) =>
      request<Farm>(`/farms/${farmId}`, { method: "PATCH", body: payload }),
    onSuccess: (farm) => {
      client.setQueryData(keys.farm(farm.id), farm);
      client.invalidateQueries({ queryKey: keys.farms });
      client.invalidateQueries({ queryKey: keys.registry(projectId) });
      client.invalidateQueries({ queryKey: ["farm-summary"] });
    },
  });
}

export function useDeleteFarm(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    // Ответ несёт число полей, оставшихся без хозяйства: интерфейс обязан
    // сказать о них, иначе они молча выпадут из реестра.
    mutationFn: (farmId: string) =>
      request<{ orphaned_fields: number }>(`/farms/${farmId}`, { method: "DELETE" }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: keys.farms });
      client.invalidateQueries({ queryKey: keys.fields(projectId) });
      client.invalidateQueries({ queryKey: keys.registry(projectId) });
    },
  });
}

/** Заключение по хозяйству за период проекта. Проект в адресе обязателен:
 *  справочник общий, а период наблюдения лежит на проекте. */
export function useFarmSummary(
  projectId: string | undefined,
  farmId: string | undefined,
  options?: Options<FarmSummary>,
) {
  return useQuery({
    queryKey: keys.farmSummary(projectId ?? "", farmId ?? ""),
    queryFn: () =>
      request<FarmSummary>(`/projects/${projectId}/farms/${farmId}/summary`),
    enabled: Boolean(projectId && farmId),
    ...options,
  });
}

export function useRegistry(projectId: string | undefined, options?: Options<Registry>) {
  return useQuery({
    queryKey: keys.registry(projectId ?? ""),
    queryFn: () => request<Registry>(`/projects/${projectId}/registry`),
    enabled: Boolean(projectId),
    ...options,
  });
}

// --- сформированные документы --------------------------------------------

export function useFarmReports(farmId: string | undefined) {
  return useQuery({
    queryKey: keys.farmReports(farmId ?? ""),
    queryFn: () => request<GeneratedReport[]>(`/farms/${farmId}/reports`),
    enabled: Boolean(farmId),
  });
}

export function useProjectReports(projectId: string | undefined) {
  return useQuery({
    queryKey: keys.projectReports(projectId ?? ""),
    queryFn: () => request<GeneratedReport[]>(`/projects/${projectId}/reports`),
    enabled: Boolean(projectId),
  });
}

// --- обработка ------------------------------------------------------------

export function useStartProjectProcessing(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    // Без списка бэкенд считает весь проект. Со списком — только выбранные
    // поля: сбор по полю занимает минуты и расходует квоту Earth Engine.
    mutationFn: (fieldIds?: string[]) =>
      request<{ project_id: string; tasks: { field_id: string; task_id: string }[] }>(
        `/projects/${projectId}/process`,
        { method: "POST", body: fieldIds ? { field_ids: fieldIds } : undefined },
      ),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: keys.fields(projectId) });
      client.invalidateQueries({ queryKey: keys.summary(projectId) });
    },
  });
}

// --- результаты -----------------------------------------------------------

export function useTimeseries(fieldId: string | undefined, options?: Options<Timeseries>) {
  return useQuery({
    queryKey: keys.timeseries(fieldId ?? ""),
    queryFn: () => request<Timeseries>(`/fields/${fieldId}/timeseries`),
    enabled: Boolean(fieldId),
    ...options,
  });
}

export function useAnomalies(fieldId: string | undefined, options?: Options<Anomaly[]>) {
  return useQuery({
    queryKey: keys.anomalies(fieldId ?? ""),
    queryFn: () => request<Anomaly[]>(`/fields/${fieldId}/anomalies`),
    enabled: Boolean(fieldId),
    ...options,
  });
}

export function useRadar(fieldId: string | undefined, options?: Options<RadarSeries>) {
  return useQuery({
    queryKey: keys.radar(fieldId ?? ""),
    queryFn: () => request<RadarSeries>(`/fields/${fieldId}/radar`),
    enabled: Boolean(fieldId),
    ...options,
  });
}

export function useRisk(fieldId: string | undefined, options?: Options<Risk>) {
  return useQuery({
    queryKey: keys.risk(fieldId ?? ""),
    queryFn: () => request<Risk>(`/fields/${fieldId}/risk`),
    enabled: Boolean(fieldId),
    ...options,
  });
}

export function useForecast(fieldId: string | undefined, options?: Options<Forecast | null>) {
  return useQuery({
    queryKey: keys.forecast(fieldId ?? ""),
    queryFn: () => request<Forecast | null>(`/fields/${fieldId}/forecast`),
    enabled: Boolean(fieldId),
    ...options,
  });
}

export function useProjectSummary(projectId: string | undefined, options?: Options<ProjectSummary>) {
  return useQuery({
    queryKey: keys.summary(projectId ?? ""),
    queryFn: () => request<ProjectSummary>(`/projects/${projectId}/summary`),
    enabled: Boolean(projectId),
    ...options,
  });
}

// --- территория -----------------------------------------------------------

export function useRegionSearch(query: string) {
  return useQuery({
    queryKey: keys.regions(query),
    queryFn: () => request<Region[]>("/regions/search", { query: { q: query, limit: 6 } }),
    // Ниже двух символов бэкенд отвечает ошибкой валидации — не дёргаем его.
    enabled: query.trim().length >= 2,
    staleTime: 5 * 60_000,
  });
}

export interface ParcelSearchBounds {
  west: number;
  south: number;
  east: number;
  north: number;
  limit?: number;
}

export function useSearchParcels() {
  return useMutation({
    mutationFn: (bounds: ParcelSearchBounds) =>
      request<Parcel[]>("/parcels/search", { method: "POST", body: { limit: 60, ...bounds } }),
  });
}
