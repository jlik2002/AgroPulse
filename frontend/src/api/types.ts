/** Типы ответов API. Повторяют схемы `backend/agropulse/schemas`.
 *  Держим их вручную, а не генерируем: набор эндпоинтов небольшой, а лишний
 *  шаг генерации в сборке усложнил бы запуск проекта по README. */

export type FieldStatus =
  | "critical"
  | "attention"
  | "normal"
  | "insufficient_data"
  | "pending"
  | "failed";

export type ValueType = "observed" | "restored" | "forecast";

export type FieldSource = "drawn" | "osm" | "worldcereal";

export type AnomalySeverity = "moderate" | "critical";

export type JobStatus = "queued" | "running" | "done" | "failed";

export interface PolygonGeometry {
  type: "Polygon";
  /** Кольца GeoJSON: [долгота, широта]. Порядок именно такой. */
  coordinates: number[][][];
}

export interface Project {
  id: string;
  name: string | null;
  period_from: string;
  period_to: string;
  created_at: string;
}

export interface Field {
  id: string;
  project_id: string;
  name: string;
  geometry: PolygonGeometry;
  area_ha: number | null;
  crop: string | null;
  sowing_date: string | null;
  source: FieldSource;
  /** Ссылка на объект открытого источника, если контур выбран, а не нарисован. */
  external_ref: string | null;
  status: FieldStatus;
  risk_score: number | null;
  created_at: string;
}

export interface Observation {
  date: string;
  value_type: ValueType;
  source: string;
  ndvi_mean: number | null;
  ndmi_mean: number | null;
  evi_mean: number | null;
  valid_fraction: number | null;
  cloud_fraction: number | null;
  scene_id: string | null;
  temperature: number | null;
  precipitation: number | null;
  ndvi_zscore: number | null;
  ndvi_lo: number | null;
  ndvi_hi: number | null;
  confidence: number | null;
  missing_reason: string | null;
}

/** Сводка качества данных ряда. Ключи перечислены явно, а не через
 *  `Record<string, number>`: свободный индекс не ловит опечатку в имени,
 *  и блок, читающий несуществующий ключ, молча не показывается. */
export interface TimeseriesStats {
  total_points: number;
  observed: number;
  restored: number;
  forecast: number;
  scenes_with_ndvi: number;
  mean_valid_fraction: number | null;
}

export interface Timeseries {
  field_id: string;
  field_name: string;
  period_from: string;
  period_to: string;
  observations: Observation[];
  stats: TimeseriesStats;
}

export interface Anomaly {
  id: string;
  start_date: string;
  end_date: string;
  duration_days: number;
  severity: AnomalySeverity;
  max_zscore: number;
  mean_zscore: number | null;
  restored_fraction: number | null;
  confidence: number | null;
  /** Подтверждённость независимыми источниками, 0..100. Отвечает не на тот же
   *  вопрос, что `confidence`: не «хватило ли данных посчитать событие»,
   *  а «сошлись ли на нём радар, оптика и погода». */
  corroboration: number | null;
  factors: Record<string, unknown> | null;
  explanation: string | null;
}

/** Точка радарного ряда Sentinel-1. Значения — медианы по полю в децибелах. */
export interface RadarPoint {
  date: string;
  /** Геометрия съёмки: сравнивать между собой можно только точки одной орбиты. */
  orbit_direction: string | null;
  relative_orbit: number | null;
  vv_median_db: number | null;
  vh_median_db: number | null;
  vh_vv_difference_db: number | null;
  rvi_median: number | null;
  spatial_iqr_db: number | null;
  low_signal_fraction: number | null;
  vv_change_db: number | null;
  vh_change_db: number | null;
  rvi_change: number | null;
  change_point_score: number | null;
  valid_fraction: number | null;
  missing_reason: string | null;
}

export type RadarEventKind = "vegetation_drop" | "vegetation_rise" | "surface_change";

/** Резкое изменение радарного сигнала. Причина не называется: одно и то же
 *  изменение возможно по нескольким причинам, и радар между ними не выбирает. */
export interface RadarEvent {
  date: string;
  kind: RadarEventKind;
  magnitude_db: number;
  score: number | null;
  title: string;
  hypotheses: string[];
  /** Удержался ли новый уровень на следующей съёмке той же орбиты. */
  confirmed: boolean;
}

export interface RadarSeries {
  field_id: string;
  source: string | null;
  points: RadarPoint[];
  events: RadarEvent[];
}

export interface Risk {
  field_id: string;
  status: FieldStatus;
  score: number | null;
  breakdown: Record<string, number> | null;
  explanation: string[];
  confidence: number | null;
  insufficient_reason: string | null;
  climatology: Record<string, unknown> | null;
}

export interface Forecast {
  field_id: string;
  horizon_days: number;
  model_version: string | null;
  /** declining | improving | stable */
  direction: string | null;
  /** high | moderate | low */
  risk_level: string | null;
  confidence: number | null;
  insufficient_reason: string | null;
  factors: Record<string, unknown> | null;
  created_at: string | null;
}

export interface FieldSummary {
  field_id: string;
  name: string;
  area_ha: number | null;
  crop: string | null;
  status: FieldStatus;
  risk_score: number | null;
  anomalies_count: number;
  worst_anomaly: Anomaly | null;
  observed_points: number;
  restored_points: number;
  mean_valid_fraction: number | null;
  inspection_rank: number | null;
}

export interface ProjectSummary {
  project_id: string;
  period_from: string;
  period_to: string;
  total_fields: number;
  critical: number;
  attention: number;
  normal: number;
  insufficient_data: number;
  fields: FieldSummary[];
}

export interface Region {
  display_name: string;
  lon: number;
  lat: number;
  /** запад, юг, восток, север */
  bbox: [number, number, number, number];
  kind: string | null;
}

export interface Parcel {
  external_ref: string;
  geometry: PolygonGeometry;
  area_ha: number;
  name: string | null;
  crop: string | null;
}

/** Одна стадия обработки одного поля — как её отдаёт SSE-поток. */
export interface StageState {
  stage: string;
  stage_title: string;
  stage_index: number;
  status: JobStatus;
  progress: number;
  message: string | null;
  error: string | null;
}

export interface ProgressSnapshot {
  project_id: string;
  stage_total: number;
  stages: { stage: string; title: string; index: number }[];
  fields: Record<string, StageState[]>;
}

export interface StageEvent extends StageState {
  type: "stage";
  field_id: string;
  stage_total: number;
  at: string;
}

export interface FieldDoneEvent {
  type: "field_done";
  field_id: string;
  status: string;
  summary: Record<string, unknown>;
  at: string;
}

export type ProgressEvent = StageEvent | FieldDoneEvent;
