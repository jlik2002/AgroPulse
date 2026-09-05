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

/** Хозяйство — сельхозпроизводитель, которому принадлежат поля.
 *  Единица решения о поддержке: реестр ранжирует хозяйства, а не контуры.
 *  Справочник общий и проекту не принадлежит — заведённое однажды хозяйство
 *  доступно из любого проекта. */
export interface Farm {
  id: string;
  name: string;
  inn: string | null;
  legal_form: string | null;
  district: string | null;
  region: string | null;
  contact: string | null;
  note: string | null;
  created_at: string;
}

/** Категория для комиссии. Ни одна не означает решения о деньгах:
 *  спутник даёт основание рассмотреть хозяйство, а не назначить выплату. */
export type ReviewCategory = "urgent" | "support" | "clarify" | "monitor" | "undetermined";

export type FarmTrust = "high" | "medium" | "low";

export interface FarmAssessment {
  /** Индекс потребности в поддержке, 0–100. Пуст, если заключения нет. */
  support_need_score: number | null;
  trust: FarmTrust;
  trust_title: string;
  category: ReviewCategory;
  category_title: string;
  action: string;

  fields_total: number;
  critical: number;
  attention: number;
  normal: number;
  insufficient_data: number;
  pending: number;

  total_area_ha: number;
  assessed_area_ha: number;
  /** Площадь, по которой заключения нет. Показывается всегда: без неё
   *  низкий индекс неотличим от отсутствия наблюдений. */
  unassessed_area_ha: number;
  problem_area_ha: number;
  critical_area_ha: number;

  assessed_share: number;
  problem_share: number;
  critical_share: number;

  weighted_risk: number | null;
  max_field_risk: number | null;
  mean_confidence: number | null;

  anomalies_total: number;
  anomalies_confirmed: number;

  reason: string | null;
  notes: string[];
}

export interface FarmSummary {
  farm: Farm;
  period_from: string;
  period_to: string;
  assessment: FarmAssessment;
  fields: FieldSummary[];
}

export interface RegistryRow {
  /** Место в очереди рассмотрения. Пусто у хозяйства без заключения. */
  rank: number | null;
  farm: Farm;
  assessment: FarmAssessment;
}

export interface Registry {
  project_id: string;
  period_from: string;
  period_to: string;
  farms_total: number;
  total_area_ha: number;
  rows: RegistryRow[];
  undetermined: RegistryRow[];
  /** Хозяйства справочника, у которых в этом проекте полей нет. */
  other_farms: Farm[];
  /** Поля, не привязанные ни к одному хозяйству. В реестр не входят. */
  unassigned_fields: FieldSummary[];
}

export type ReportKind = "field" | "farm" | "project" | "registry";

export interface GeneratedReport {
  id: string;
  kind: ReportKind;
  title: string;
  filename: string;
  project_id: string;
  farm_id: string | null;
  field_id: string | null;
  pages: number | null;
  size_bytes: number | null;
  created_at: string;
}

export interface Field {
  id: string;
  project_id: string;
  /** Хозяйство-владелец. Пусто у полей, заведённых до появления хозяйств. */
  farm_id: string | null;
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
  /** Единый балл движка 0..100 — глубина и устойчивость отклонения. Это не
   *  доверие: надёжность вывода лежит в `trust`. */
  anomaly_score: number;
  /** Разложение сигналов движка в пиковой точке. `historical_z` есть только
   *  когда у поля доступна история за прошлые сезоны. */
  level_z: number | null;
  slope_z: number | null;
  historical_z: number | null;
  change_point_nearby: boolean;
  restored_fraction: number | null;
  /** Можно ли верить событию. Один сигнал вместо прежних трёх; основания
   *  вердикта лежат в `factors.trust`. */
  trust: "confirmed" | "unverified" | "disputed" | null;
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
