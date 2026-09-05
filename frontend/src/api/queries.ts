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
  Field,
  Forecast,
  Parcel,
  PolygonGeometry,
  Project,
  ProjectSummary,
  Region,
  Risk,
  Timeseries,
} from "@/api/types";

export const keys = {
  project: (id: string) => ["project", id] as const,
  fields: (projectId: string) => ["fields", projectId] as const,
  field: (id: string) => ["field", id] as const,
  timeseries: (id: string) => ["timeseries", id] as const,
  anomalies: (id: string) => ["anomalies", id] as const,
  risk: (id: string) => ["risk", id] as const,
  forecast: (id: string) => ["forecast", id] as const,
  summary: (projectId: string) => ["summary", projectId] as const,
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
  crop?: string | null;
  sowing_date?: string | null;
  source?: "drawn" | "osm" | "worldcereal";
  external_ref?: string | null;
}

export function useCreateField(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateFieldPayload) =>
      request<Field>(`/projects/${projectId}/fields`, { method: "POST", body: payload }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.fields(projectId) }),
  });
}

export interface UpdateFieldPayload {
  name?: string;
  geometry?: PolygonGeometry;
  crop?: string | null;
  sowing_date?: string | null;
}

export function useUpdateField(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ fieldId, payload }: { fieldId: string; payload: UpdateFieldPayload }) =>
      request<Field>(`/fields/${fieldId}`, { method: "PATCH", body: payload }),
    onSuccess: (field) => {
      client.invalidateQueries({ queryKey: keys.fields(projectId) });
      client.invalidateQueries({ queryKey: keys.field(field.id) });
    },
  });
}

export function useDeleteField(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (fieldId: string) => request<void>(`/fields/${fieldId}`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.fields(projectId) }),
  });
}

// --- обработка ------------------------------------------------------------

export function useStartProjectProcessing(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      request<{ project_id: string; tasks: { field_id: string; task_id: string }[] }>(
        `/projects/${projectId}/process`,
        { method: "POST" },
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
