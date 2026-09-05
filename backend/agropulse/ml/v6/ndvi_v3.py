#!/usr/bin/env python3
"""NDVI v3: остаточные модели CatBoost, межполевые признаки и повторная проверка.

Запуск и измеренные результаты описаны в README.md и REPORT.md.
Основа: предоставленный пользователем ms_v2.py. Скрытые ответы не используются.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, Pool
from scipy.interpolate import PchipInterpolator

SEED = 42
GAP_THRESHOLD = 0.10          # порог организаторов: GapScore = 30*(1 - RMSE/0.10)
CLIM_WINDOW = 10              # полуширина окна дня года для климатологии, дней

# primary_ndvi склеен из трёх приборов с разной шкалой. По дням, когда одно поле
# снято двумя приборами сразу, смещения устойчивы: MODIS читает NDVI примерно
# на 0.08 выше, чем Sentinel-2. Приводим всё к шкале Landsat (самый
# многочисленный и посередине), коэффициенты — регрессия по совпадающим дням.
TO_LANDSAT = {"s2": (0.9188, 0.0648), "landsat": (1.0, 0.0), "modis": (0.9991, -0.0553)}
# обратное смещение: сколько прибор читает относительно Landsat
FROM_LANDSAT = {"s2": -0.0369, "landsat": 0.0, "modis": 0.0557}
SENSORS = ("s2", "landsat", "modis")


DATE_FRACTIONS: dict[int, tuple] = {}


def gapscore(rmse: float) -> float:
    return round(30 * max(0.0, 1 - rmse / GAP_THRESHOLD), 2)


# ---------------------------------------------------------------------------
# Подготовка рядов
# ---------------------------------------------------------------------------

def load(path: Path) -> pd.DataFrame:
    """Прочитать набор и привести к общему виду.

    year и doy пересчитываются из даты: в контрольных строках они замаскированы,
    но дата известна всегда, так что признак законный.
    """
    d = pd.read_csv(path, parse_dates=["date"])
    if "is_synthetic_gap" not in d:
        d["is_synthetic_gap"] = False
    if d["is_synthetic_gap"].dtype == object:
        d["is_synthetic_gap"] = d["is_synthetic_gap"].astype(str).str.lower().isin(
            {"true", "1", "yes", "t"})
    d["year"] = d["date"].dt.year
    d["doy"] = d["date"].dt.dayofyear

    # сводные ряды дополнительных индексов: берём лучший доступный сенсор
    for name, cols in (("evi", ["s2_evi", "landsat_evi", "modis_evi"]),
                       ("ndwi", ["s2_ndwi", "landsat_ndwi"])):
        present = [c for c in cols if c in d.columns]
        d[name] = d[present].bfill(axis=1).iloc[:, 0] if present else np.nan

    for c in ("era5_temp_c", "era5_precip_mm", "crop_type"):
        if c not in d.columns:
            d[c] = np.nan

    # какой прибор дал primary_ndvi — определяем по точному совпадению значения
    v = d["primary_ndvi"].values.astype(float)
    sensor = np.full(len(d), "", object)
    for name, col in (("s2", "s2_ndvi"), ("landsat", "landsat_ndvi"), ("modis", "modis_ndvi")):
        if col not in d.columns:
            continue
        c = d[col].values.astype(float)
        sensor = np.where((sensor == "") & np.isfinite(v) & np.isfinite(c)
                          & (np.abs(c - v) < 1e-9), name, sensor)
    d["sensor"] = sensor
    a = np.array([TO_LANDSAT.get(x, (1.0, 0.0))[0] for x in sensor])
    b = np.array([TO_LANDSAT.get(x, (1.0, 0.0))[1] for x in sensor])
    d["ndvi_harm"] = a * v + b
    return d.sort_values(["anon_polygon_id", "date"]).reset_index(drop=True)


def date_sensor_fractions(frames: list[pd.DataFrame]) -> dict[int, tuple]:
    """Доли приборов по датам съёмки.

    Спутник накрывает весь регион разом, поэтому по другим полигонам в ту же дату
    видно, каким прибором снята и целевая точка. Для контрольных строк это
    единственный способ узнать шкалу ответа: сама строка замаскирована.
    """
    parts = [f.loc[f["sensor"] != "", ["date", "sensor"]] for f in frames]
    al = pd.concat(parts, ignore_index=True)
    al["t"] = al["date"].values.astype("datetime64[D]").astype(int)
    out = {}
    for t, grp in al.groupby("t")["sensor"]:
        n = len(grp)
        counts = grp.value_counts()
        out[int(t)] = tuple(counts.get(s, 0) / n for s in SENSORS)
    return out


def polygon_scale(tk: np.ndarray, vk: np.ndarray) -> float:
    """Характерный масштаб остатка ряда — робастная ошибка линейного восстановления.

    Каждая внутренняя точка восстанавливается по двум соседям (замкнутая формула,
    цикл не нужен), медиана модуля ошибки переводится в сигму множителем 1.4826.
    Считается только по видимым точкам.
    """
    if len(tk) < 5:
        return 0.05
    t0, t1, t2 = tk[:-2], tk[1:-1], tk[2:]
    v0, v2 = vk[:-2], vk[2:]
    span = (t2 - t0).astype(float)
    span[span == 0] = 1.0
    err = np.abs(vk[1:-1] - (v0 + (v2 - v0) * (t1 - t0) / span))
    return float(np.clip(1.4826 * np.median(err), 0.01, 0.30))


class PolygonContext:
    """Всё, что известно про полигон по видимым строкам.

    Собирается один раз на полигон; целевые строки при построении признаков
    исключаются явно, поэтому один и тот же объект годится и для обучения
    (точка прячется), и для инференса (точка и так пуста).
    """

    def __init__(self, frame: pd.DataFrame, hide: np.ndarray | None = None):
        self.t = frame["date"].values.astype("datetime64[D]").astype(int)
        self.doy = frame["doy"].values
        self.year = frame["year"].values
        self.ndvi = frame["primary_ndvi"].values.astype(float).copy()
        _hide = hide if hide is not None else np.zeros(len(frame), bool)
        self.ndvi[_hide] = np.nan
        # hide — строки, которые считаем неизвестными: так кросс-валидация
        # прячет сразу целую долю точек, как это делает настоящий тест,
        # а не по одной (иначе у пропуска всегда оба соседа на месте)
        self.hide = hide if hide is not None else np.zeros(len(frame), bool)
        self.crop = frame["crop_type"].dropna().iloc[0] if frame["crop_type"].notna().any() else None

        self.harm = frame["ndvi_harm"].values.astype(float).copy()
        self.harm[_hide] = np.nan
        self.sensor = frame["sensor"].values.copy()

        known = np.isfinite(self.ndvi)
        self.k_t, self.k_v = self.t[known], self.ndvi[known]
        self.k_h = self.harm[known]
        self.k_s = self.sensor[known]
        self.k_doy, self.k_year = self.doy[known], self.year[known]
        self.scale = polygon_scale(self.k_t, self.k_v)

        # погода: в контрольных строках замаскирована, берём по остальным дням
        self.w_temp, self.w_prec = {}, {}
        for col, store in (("era5_temp_c", self.w_temp), ("era5_precip_mm", self.w_prec)):
            vals = frame[col].values.astype(float).copy()
            vals[self.hide] = np.nan
            ok = np.isfinite(vals)
            store.update(zip(self.t[ok].tolist(), vals[ok].tolist()))

        # Вспомогательные индексы. В контрольных строках теста они замаскированы
        # вместе с primary_ndvi — это снимок одного и того же пролёта. Прячем их
        # ровно так же, иначе NDWI той же даты подсказывает ответ.
        self.aux = {}
        for name in ("evi", "ndwi"):
            v = frame[name].values.astype(float).copy()
            v[self.hide] = np.nan
            ok = np.isfinite(v)
            self.aux[name] = (self.t[ok], v[ok])

    def sensor_features(self, x: int, tk: np.ndarray, hk: np.ndarray) -> dict:
        """Ожидаемая шкала ответа и интерполяция в приведённой шкале."""
        fr = DATE_FRACTIONS.get(x)
        out = {f"day_frac_{s}": (fr[i] if fr else np.nan) for i, s in enumerate(SENSORS)}
        # ожидаемое смещение ответа относительно шкалы Landsat
        out["exp_bias"] = (sum(fr[i] * FROM_LANDSAT[s] for i, s in enumerate(SENSORS))
                           if fr else np.nan)
        if len(tk) >= 2 and np.isfinite(hk).all():
            lin_h = float(np.interp(x, tk, hk))
            out["lin_harm"] = lin_h
            # опора, переведённая обратно в ожидаемую шкалу целевой даты
            out["lin_harm_back"] = lin_h + (out["exp_bias"] if out["exp_bias"] == out["exp_bias"] else 0.0)
        else:
            out["lin_harm"] = np.nan
            out["lin_harm_back"] = np.nan
        return out

    def weather(self, x: int) -> dict:
        """Окна погоды строго до и строго после целевой даты."""
        out = {}
        for lo, hi, tag in ((x - 15, x - 1, "before"), (x + 1, x + 15, "after")):
            days = range(lo, hi + 1)
            temps = [self.w_temp[d] for d in days if d in self.w_temp]
            precs = [self.w_prec[d] for d in days if d in self.w_prec]
            out[f"temp_{tag}"] = float(np.mean(temps)) if temps else np.nan
            out[f"precip_{tag}"] = float(np.sum(precs)) if precs else np.nan
        # накопленное тепло: фаза развития, чего скользящее окно не даёт
        gdd = [max(0.0, self.w_temp[d] - 5.0) for d in range(x - 30, x) if d in self.w_temp]  # без самого дня
        out["gdd_30"] = float(np.sum(gdd)) if gdd else np.nan
        return out

    def climatology(self, doy: int, year: int) -> dict:
        """Норма этого полигона на этот день года по ОСТАЛЬНЫМ годам.

        Целевой год исключается целиком — иначе признак подсматривал бы ответ.
        Колонок климатологии в тесте нет, поэтому считаем сами.
        """
        m = (np.abs(self.k_doy - doy) <= CLIM_WINDOW) & (self.k_year != year)
        v = self.k_v[m]
        if len(v) == 0:
            return {"clim_mean": np.nan, "clim_std": np.nan, "clim_count": 0}
        return {"clim_mean": float(v.mean()),
                "clim_std": float(v.std()) if len(v) > 1 else np.nan,
                "clim_count": int(len(v))}

    def aux_at(self, x: int) -> dict:
        """Ближайшие значения EVI и NDWI и линейная оценка на целевую дату."""
        out = {}
        for name, (at, av) in self.aux.items():
            keep = at != x            # снимок самой целевой даты недоступен
            at, av = at[keep], av[keep]
            if len(at) == 0:
                out[f"{name}_lin"] = np.nan
                out[f"{name}_near"] = np.nan
                out[f"{name}_near_days"] = np.nan
                continue
            j = int(np.argmin(np.abs(at - x)))
            out[f"{name}_lin"] = float(np.interp(x, at, av)) if len(at) > 1 else float(av[0])
            out[f"{name}_near"] = float(av[j])
            out[f"{name}_near_days"] = int(abs(at[j] - x))
        return out


def features(ctx: PolygonContext, x: int, doy: int, year: int,
             drop: int | None = None) -> dict | None:
    """Признаки одной целевой даты. drop — индекс скрываемой известной точки."""
    tk, vk = ctx.k_t, ctx.k_v
    if drop is not None:
        tk, vk = np.delete(tk, drop), np.delete(vk, drop)
    n = len(tk)
    if n < 4:
        return None

    left = int(np.searchsorted(tk, x))
    li = [left - 1 - k for k in range(3)]
    ri = [left + k for k in range(3)]
    lv = [vk[i] if i >= 0 else np.nan for i in li]
    lt = [x - tk[i] if i >= 0 else np.nan for i in li]
    rv = [vk[i] if i < n else np.nan for i in ri]
    rt = [tk[i] - x if i < n else np.nan for i in ri]
    has_l, has_r = li[0] >= 0, ri[0] < n
    if not (has_l or has_r):
        return None

    lin = float(np.interp(x, tk, vk))
    lo, hi = max(0, left - 8), min(n, left + 8)
    pch = float(PchipInterpolator(tk[lo:hi], vk[lo:hi])(x)) if hi - lo >= 4 else lin

    d_l = lt[0] if has_l else np.nan
    d_r = rt[0] if has_r else np.nan
    span = (d_l + d_r) if (has_l and has_r) else np.nan
    slope_l = (lv[0] - lv[1]) / (lt[1] - lt[0]) if has_l and li[1] >= 0 else np.nan
    slope_r = (rv[1] - rv[0]) / (rt[1] - rt[0]) if has_r and ri[1] < n else np.nan
    slope_bridge = (rv[0] - lv[0]) / span if (has_l and has_r) else np.nan

    win = (tk >= x - 45) & (tk <= x + 45)
    wv = vk[win]
    clim = ctx.climatology(doy, year)

    f = {
        "lin": lin, "pchip": pch, "pchip_minus_lin": pch - lin,
        "nearest": lv[0] if (has_l and (not has_r or d_l <= d_r)) else rv[0],
        "mean2": float(np.nanmean([lv[0], rv[0]])),
        "dist_left": d_l, "dist_right": d_r,
        "dist_min": float(np.nanmin([d_l, d_r])), "span": span,
        "gap_position": (d_l / span) if span == span else np.nan,
        "slope_left": slope_l, "slope_right": slope_r, "slope_bridge": slope_bridge,
        "curvature": (slope_r - slope_l) if (slope_l == slope_l and slope_r == slope_r) else np.nan,
        "delta_lr": (rv[0] - lv[0]) if (has_l and has_r) else np.nan,
        "abs_delta_lr": abs(rv[0] - lv[0]) if (has_l and has_r) else np.nan,
        "local_mean": wv.mean() if len(wv) else np.nan,
        "local_std": wv.std() if len(wv) > 1 else np.nan,
        "local_min": wv.min() if len(wv) else np.nan,
        "local_max": wv.max() if len(wv) else np.nan,
        "local_count": len(wv),
        "lin_vs_local_mean": lin - wv.mean() if len(wv) else np.nan,
        "doy": doy, "year": year,
        "doy_sin": np.sin(2 * np.pi * doy / 365.25),
        "doy_cos": np.cos(2 * np.pi * doy / 365.25),
        "n_known": n, "scale": polygon_scale(tk, vk),
        # отклонение опоры от нормы поля: если линейная уже ниже нормы,
        # поправку надо искать в другую сторону, чем если выше
        "lin_vs_clim": lin - clim["clim_mean"] if clim["clim_mean"] == clim["clim_mean"] else np.nan,
    }
    hk = ctx.k_h if drop is None else np.delete(ctx.k_h, drop)
    sf = ctx.sensor_features(x, tk, hk)
    f.update(sf)
    # Опора: если состав приборов на дату известен, берём интерполяцию в
    # приведённой шкале с обратным переводом — она уже без межсенсорной ступеньки.
    f["anchor"] = sf["lin_harm_back"] if sf["lin_harm_back"] == sf["lin_harm_back"] else lin
    f["harm_minus_lin"] = sf["lin_harm_back"] - lin if sf["lin_harm_back"] == sf["lin_harm_back"] else np.nan
    # смещения приборов у ближайших соседей: если сосед снят MODIS, а цель
    # ожидается от Sentinel-2, между ними systematic сдвиг ~0.08
    ks = ctx.k_s if drop is None else np.delete(ctx.k_s, drop)
    f["prev_1_bias"] = FROM_LANDSAT.get(ks[li[0]], np.nan) if has_l else np.nan
    f["next_1_bias"] = FROM_LANDSAT.get(ks[ri[0]], np.nan) if has_r else np.nan
    f.update(clim)
    f.update(ctx.weather(x))
    f.update(ctx.aux_at(x))
    for k in range(3):
        f[f"prev_{k+1}_ndvi"], f[f"prev_{k+1}_days"] = lv[k], lt[k]
        f[f"next_{k+1}_ndvi"], f[f"next_{k+1}_days"] = rv[k], rt[k]
    # соседи как отклонение от опоры: модель учит форму, а не уровень поля
    f["prev_1_resid"] = lv[0] - lin if has_l else np.nan
    f["next_1_resid"] = rv[0] - lin if has_r else np.nan
    return f


# ---------------------------------------------------------------------------
# V3: панель полей, полное маскирование, повторные проверочные маски.
# Никакие значения из старого private_test_ground_truth не читаются моделью.
# ---------------------------------------------------------------------------
import hashlib
import json
import platform
import time
from scipy.optimize import minimize
from sklearn.linear_model import Ridge

KEY = ['anon_polygon_id', 'date']
META = {'y', 'polygon', 'date_str', 'split', 'row_id'}


def masked(frame, indices):
    """Стираем ВСЕ данные снимка до создания любых контекстов и статистик."""
    out = frame.copy()
    keep = set(KEY + ['crop_type', 'is_synthetic_gap', 'year', 'doy', 'split', 'row_id'])
    out.loc[indices, [c for c in out if c not in keep]] = np.nan
    out.loc[indices, 'sensor'] = ''
    return out


def read_inputs(train_path, test_path):
    train, test = load(Path(train_path)), load(Path(test_path))
    if train.duplicated(KEY).any() or test.duplicated(KEY).any():
        raise ValueError('Неуникальный ключ поле + дата')
    if len(train[KEY].merge(test[KEY], on=KEY)):
        raise ValueError('Train и test пересекаются по ключам')
    train['split'], test['split'] = 'train', 'test'
    all_df = pd.concat([train, test], ignore_index=True)
    all_df = masked(all_df, all_df.index[all_df.is_synthetic_gap.fillna(False)])
    all_df['row_id'] = np.arange(len(all_df))
    return all_df


class Panel:
    """Сигналы других полей в ту же дату; коэффициенты обучены без целевого года.

    Остаток каждого поля считается только по его собственным соседям. Поэтому
    исключение целевого поля полностью устраняет путь утечки через доноров.
    В коэффициенты Ridge и корреляции не входит ни одна точка целевого года.
    """
    def __init__(self, df):
        self.df = df
        self.ids = sorted(df.anon_polygon_id.unique())
        self.dates = np.sort(df.date.unique()).astype('datetime64[D]').astype(int)
        self.pi = {p:i for i,p in enumerate(self.ids)}
        self.ti = {int(t):i for i,t in enumerate(self.dates)}
        self.values = np.full((len(self.dates), len(self.ids)), np.nan)
        self.resid = self.values.copy()
        self.sensors = np.full(self.values.shape, -1, dtype=int)
        self.years = pd.to_datetime(self.dates, unit='D').year.to_numpy()
        self.models = {}
        for pid, f in df.groupby('anon_polygon_id', sort=False):
            v = f.primary_ndvi.to_numpy(float)
            ok = np.isfinite(v)
            ts = f.date.to_numpy().astype('datetime64[D]').astype(int)[ok]
            h = f.ndvi_harm.to_numpy(float)[ok]
            ss = f.sensor.to_numpy()[ok]
            ix = np.array([self.ti[int(t)] for t in ts]); col = self.pi[pid]
            self.values[ix,col] = h
            self.sensors[ix,col] = [SENSORS.index(s) if s in SENSORS else -1 for s in ss]
            if len(h) >= 3:
                anchor = h[:-2] + (h[2:]-h[:-2])*(ts[1:-1]-ts[:-2])/(ts[2:]-ts[:-2])
                r = h[1:-1] - anchor
                # Длинные зимние интервалы и огромные выбросы не учат общий шум дня.
                good = (ts[2:]-ts[:-2] <= 60) & (np.abs(r) < .6)
                self.resid[ix[1:-1][good],col] = r[good]
        print('Panel: подготовлена матрица', self.values.shape, flush=True)

    def model(self, pid, year):
        key = (pid, int(year))
        if key in self.models:
            return self.models[key]
        j = self.pi[pid]
        cols = np.array([k for k in range(len(self.ids)) if k != j])
        r = self.resid
        fit = (self.years != year) & np.isfinite(r[:,j])
        x = r[fit][:,cols]; y = r[fit,j]
        weights = np.zeros(len(cols))
        for k in range(len(cols)):
            good = np.isfinite(x[:,k])
            if good.sum() >= 25:
                a,b = x[good,k], y[good]
                if a.std() > 1e-6 and b.std() > 1e-6:
                    corr = np.corrcoef(a,b)[0,1]
                    weights[k] = max(0., corr) ** 2 * good.sum()/(good.sum()+50)
        model = None
        if len(y) >= 50:
            # NaN -> 0 означает отсутствие оценки шума; отдельная маска сообщает пропуск.
            xx = np.concatenate([np.nan_to_num(x)/.1, np.isfinite(x)*.1], axis=1)
            model = Ridge(alpha=30.).fit(xx, y)
        out = (cols, weights, model)
        self.models[key] = out
        return out

    def at(self, pid, t, year):
        i,j = self.ti[int(t)], self.pi[pid]
        cols, weights, model = self.model(pid, year)
        r = self.resid[i,cols]; ss = self.sensors[i,cols]
        good = np.isfinite(r)
        f = {'panel_count':int(good.sum()), 'panel_mean':float(np.nanmean(r)) if good.any() else 0.,
             'panel_median':float(np.nanmedian(r)) if good.any() else 0.,
             'panel_std':float(np.nanstd(r)) if good.any() else 0.}
        for n in (3, 8, 20, 100):
            order = np.argsort(-weights)
            use = order[good[order]][:n]
            w = weights[use]
            f[f'panel_top{n}'] = float(np.dot(w,r[use])/w.sum()) if w.sum()>0 else 0.
            f[f'panel_top{n}_weight'] = float(w.sum())
        for k,s in enumerate(SENSORS):
            m = good & (ss==k)
            f[f'panel_{s}'] = float(r[m].mean()) if m.any() else 0.
            f[f'panel_{s}_count'] = int(m.sum())
        xx = np.concatenate([np.nan_to_num(r)/.1, np.isfinite(r)*.1])[None]
        f['panel_ridge'] = float(model.predict(xx)[0]) if model else 0.
        sensor_valid = ss >= 0
        den = int(sensor_valid.sum())
        fr = tuple(float((ss==k).sum()/den) for k in range(3)) if den else (0., 1., 0.)
        return f, fr


def enhanced_features(ctx, x, doy, year, drop, panel, pid):
    global DATE_FRACTIONS
    pf, fr = panel.at(pid, x, year)
    DATE_FRACTIONS = {x:fr}
    f = features(ctx, x, doy, year, drop=drop)
    if f is None:
        f = {'lin': .3, 'anchor': .3, 'scale': .05}
    tk = ctx.k_t if drop is None else np.delete(ctx.k_t,drop)
    vk = ctx.k_v if drop is None else np.delete(ctx.k_v,drop)
    hk = ctx.k_h if drop is None else np.delete(ctx.k_h,drop)
    sk = ctx.k_s if drop is None else np.delete(ctx.k_s,drop)
    yy = ctx.k_year if drop is None else np.delete(ctx.k_year,drop)
    # Точный обратный affine, а не прибавление среднего постоянного смещения.
    back = lambda v: sum(fr[i]*(v-TO_LANDSAT[s][1])/TO_LANDSAT[s][0] for i,s in enumerate(SENSORS))
    hlin = float(np.interp(x,tk,hk)) if len(tk) else .3
    f['affine_anchor'] = back(hlin)
    f['modis_day'] = float((doy-1)%16==0)
    for period in (5,10,16):
        f[f'orbit_sin{period}'] = np.sin(2*np.pi*x/period)
        f[f'orbit_cos{period}'] = np.cos(2*np.pi*x/period)
    season = vk[yy==year]
    for q in (10,50,90,100):
        val = float(np.percentile(season,q)) if len(season) else np.nan
        f[f'season_q{q}'] = val
        f[f'lin_vs_season_q{q}'] = f['lin'] - val
    f['season_count'] = len(season)
    for n in (4,6,10):
        take = np.argsort(np.abs(tk-x))[:n]
        dx = (tk[take]-x)/15.
        w = np.exp(-np.abs(dx))
        a = np.stack([np.ones(len(dx)),dx],axis=1)
        if len(dx)>=2:
            coef = np.linalg.solve(a.T@(w[:,None]*a)+np.diag([1e-8,.03]), a.T@(w*hk[take]))
            f[f'loc{n}'] = back(float(coef[0]))
            f[f'loc{n}_minus_anchor'] = f[f'loc{n}']-f['anchor']
        else:
            f[f'loc{n}'] = f['affine_anchor']
    for s in SENSORS:
        mask = (sk==s)
        ts,vs = tk[mask], vk[mask]
        f[f'{s}_own_interp'] = float(np.interp(x,ts,vs)) if len(ts) else np.nan
        f[f'{s}_own_dist'] = float(np.min(np.abs(ts-x))) if len(ts) else np.nan
    # Панельная поправка в гармонизированной шкале, затем обратный перевод.
    f.update(pf)
    f['panel_anchor'] = back(hlin+pf['panel_ridge'])
    f['panel_mean_anchor'] = back(hlin+pf['panel_mean'])
    return f


def samples(df, target_ids=None):
    """Признаки visible leave-one-out либо для полностью скрытых строк."""
    panel = Panel(df)
    wanted = set(target_ids) if target_ids is not None else None
    rows = []
    for pidx,(pid,frame) in enumerate(df.groupby('anon_polygon_id',sort=False)):
        ctx = PolygonContext(frame)
        for row in frame.itertuples():
            is_known = np.isfinite(row.primary_ndvi)
            if wanted is None and not is_known:
                continue
            if wanted is not None and row.row_id not in wanted:
                continue
            t = int(np.datetime64(row.date,'D').astype(int))
            drop = int(np.searchsorted(ctx.k_t,t)) if is_known else None
            f = enhanced_features(ctx,t,int(row.doy),int(row.year),drop,panel,pid)
            f.update(y=float(row.primary_ndvi), polygon=pid, crop=str(row.crop_type),
                     date_str=row.date.strftime('%Y-%m-%d'), split=row.split,row_id=row.row_id)
            rows.append(f)
        if (pidx+1)%10==0:
            print('Признаки: полей',pidx+1,'строк',len(rows),flush=True)
    return pd.DataFrame(rows).replace([np.inf,-np.inf],np.nan)


def rmse(y,p):
    return float(np.sqrt(np.mean((np.asarray(y)-np.asarray(p))**2)))


def model_spec():
    return {
        'baseline':dict(anchor='anchor',normalized=True,features='base',depth=6,loss='RMSE'),
        'panel':dict(anchor='affine_anchor',normalized=False,features='all',depth=6,loss='RMSE'),
        'panel_scaled':dict(anchor='affine_anchor',normalized=True,features='all',depth=6,loss='RMSE'),
        'local':dict(anchor='loc6',normalized=False,features='all',depth=6,loss='RMSE'),
        'robust':dict(anchor='affine_anchor',normalized=False,features='all',depth=6,loss='Huber:delta=0.08'),
    }


def base_columns(df):
    # Ровно семейство признаков исходной версии; их вычисление теперь без утечки.
    exclude_prefix = ('panel_','season_','lin_vs_season_','loc','orbit_')
    exclude = {'affine_anchor','modis_day'}
    return [c for c in df if c not in META and c not in exclude
            and not c.startswith(exclude_prefix) and '_own_' not in c]


def fit_one(data, valid, spec, args, seed, iterations=None):
    cols = base_columns(data) if spec['features']=='base' else [c for c in data if c not in META]
    scale = data.scale.to_numpy() if spec['normalized'] else np.ones(len(data))
    y = (data.y.to_numpy()-data[spec['anchor']].to_numpy())/scale
    # Для normalized RMSE компенсируем scale^2 весами: оптимизируем исходный RMSE.
    # Baseline оставлен с исходной невзвешенной целью для корректного сравнения.
    weight = scale**2 if spec['normalized'] and spec['features']!='base' else np.ones(len(data))
    model = CatBoostRegressor(iterations=iterations or args.iterations,depth=spec['depth'],
        learning_rate=.03,l2_leaf_reg=6.,loss_function=spec['loss'],random_seed=seed,
        thread_count=args.threads,verbose=False,allow_writing_files=False)
    model.fit(Pool(data[cols],y,cat_features=['crop'],weight=weight))
    def pred(frame):
        sc = frame.scale.to_numpy() if spec['normalized'] else 1.
        return np.clip(frame[spec['anchor']].to_numpy()+sc*model.predict(frame[cols]),-.1,1.)
    return model,cols,pred(valid)


def pick_masks(df, seed, rate):
    rng = np.random.default_rng(seed)
    indices = []
    for _,g in df.groupby('anon_polygon_id'):
        known = g.index[g.primary_ndvi.notna()].to_numpy()
        indices.extend(rng.choice(known,max(1,round(len(known)*rate)),replace=False))
    return np.array(indices,dtype=int)


def paired_interval(y, p, baseline, groups, seed=123):
    # Парный bootstrap по полигон-годам учитывает зависимость точек внутри сезона.
    keys,inv = np.unique(groups,return_inverse=True)
    e1=np.bincount(inv,weights=(y-p)**2); e0=np.bincount(inv,weights=(y-baseline)**2)
    count=np.bincount(inv); rng=np.random.default_rng(seed)
    deltas=[]
    for _ in range(1000):
        ix=rng.integers(0,len(keys),len(keys)); n=count[ix].sum()
        deltas.append(np.sqrt(e1[ix].sum()/n)-np.sqrt(e0[ix].sum()/n))
    return np.percentile(deltas,[2.5,97.5]).tolist()


def write_submission(raw_test, example_path, target, prediction, path):
    out = pd.DataFrame({'anon_polygon_id':target.polygon,'date':target.date_str,
                        'primary_ndvi_true':prediction})
    expected = pd.read_csv(example_path)[KEY] if example_path else raw_test.loc[raw_test.is_synthetic_gap,KEY].copy()
    expected['date']=pd.to_datetime(expected.date).dt.strftime('%Y-%m-%d')
    test_keys=raw_test.loc[raw_test.is_synthetic_gap,KEY].copy()
    test_keys['date']=pd.to_datetime(test_keys.date).dt.strftime('%Y-%m-%d')
    if set(map(tuple,expected.values))!=set(map(tuple,test_keys.values)):
        raise ValueError('Ключи шаблона не совпадают с synthetic gaps')
    if expected.duplicated(KEY).any() or out.duplicated(KEY).any():
        raise ValueError('Дубликаты ключей submission')
    result=expected.merge(out,on=KEY,how='left',validate='one_to_one')
    if len(out)!=len(expected) or not np.isfinite(result.primary_ndvi_true).all():
        raise ValueError('Неполное покрытие submission')
    result[['date','primary_ndvi_true','anon_polygon_id']].to_csv(path,index=False)


def build_samples(df, target_ids=None, clean_inputs=False):
    if not clean_inputs:
        return samples(df, target_ids)
    # Исключаем невозможные измерения только из входа, а не из целевой выборки.
    bad = df.index[df.primary_ndvi.notna() & ~df.primary_ndvi.between(-1, 1)]
    context = masked(df, bad)
    ids = df.loc[df.primary_ndvi.notna(), 'row_id'].to_numpy() if target_ids is None else target_ids
    result = samples(context, ids)
    result['y'] = result.row_id.map(df.set_index('row_id').primary_ndvi)
    return result


def predict_saved(df, args, out):
    manifest = json.loads((out/'manifest.json').read_text())
    saved = manifest['args']
    target = build_samples(df, df.loc[df.is_synthetic_gap, 'row_id'].values,
                           saved.get('clean_inputs', False))
    predictions = {}
    for name in saved['models']:
        cols = json.loads((out/f'{name}_features.json').read_text())
        spec = model_spec()[name]
        pp = []
        for seed in saved['seeds']:
            model = CatBoostRegressor()
            model.load_model(str(out/f'{name}_{seed}.cbm'))
            scale = target.scale.to_numpy() if spec['normalized'] else 1.
            pp.append(np.clip(target[spec['anchor']].to_numpy()+scale*model.predict(target[cols]), -.1, 1.))
        predictions[name] = np.mean(pp, axis=0)
    weights = json.loads((out/'selection.json').read_text())['weights']
    predictions['ensemble'] = sum(weights[n]*predictions[n] for n in weights)
    for name, pred in predictions.items():
        write_submission(df[df.split=='test'], args.example, target, pred, out/f'submission_{name}.csv')
    print('Предсказания сохранённых моделей готовы:', out.resolve(), flush=True)


def main():
    ap=argparse.ArgumentParser(description='NDVI v3: честная проверка и межполевой ансамбль')
    ap.add_argument('--train',required=True);ap.add_argument('--test',required=True)
    ap.add_argument('--example');ap.add_argument('--outdir',default='ndvi_results')
    ap.add_argument('--iterations',type=int,default=2500);ap.add_argument('--threads',type=int,default=4)
    ap.add_argument('--seeds',type=int,nargs='+',default=[42,137])
    ap.add_argument('--validation-seeds',type=int,nargs='+',default=[2026,9071])
    ap.add_argument('--models',nargs='+',default=list(model_spec()))
    ap.add_argument('--skip-final',action='store_true')
    ap.add_argument('--clean-inputs',action='store_true',help='Исключить NDVI вне [-1,1] из входного контекста')
    ap.add_argument('--predict-only',action='store_true',help='Использовать модели и параметры из outdir')
    args=ap.parse_args()
    if len(args.validation_seeds)<2: ap.error('Нужны минимум два seed: выбор и повторная проверка')
    if not (set(args.models)-{'baseline'}): ap.error('Добавьте хотя бы одну новую модель')
    if 'baseline' not in args.models: ap.error('Включите baseline для проверки улучшения')
    out=Path(args.outdir);out.mkdir(parents=True,exist_ok=True)
    specs=model_spec()
    if set(args.models)-set(specs): ap.error('Неизвестная модель')
    df=read_inputs(args.train,args.test)
    if args.predict_only:
        predict_saved(df,args,out)
        return
    rate=float(df.is_synthetic_gap.sum()/
         (df.loc[df.split=='test','primary_ndvi'].notna().sum()+df.is_synthetic_gap.sum()))
    manifest={'args':vars(args),'python':platform.python_version(),'files':{},'rate':rate}
    for label,path in [('train',args.train),('test',args.test)]:
        manifest['files'][label]={'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest()}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
    oofs=[]; reports=[]; weights=None; choice=None
    for fold,seed in enumerate(args.validation_seeds):
        print('\nVALIDATION',fold,'seed',seed,flush=True)
        hidden=pick_masks(df,seed,rate); visible=masked(df,hidden)
        # Все числа hidden отсутствуют и в train features, и в панельной статистике.
        cache=out/f'features_cv_{seed}.pkl'
        signature=hashlib.sha256((json.dumps(manifest['files'],sort_keys=True)+str(seed)+str(args.clean_inputs)+
                                  Path(__file__).read_text()).encode()).hexdigest()
        sigpath=cache.with_suffix('.sha256')
        if cache.exists() and sigpath.exists() and sigpath.read_text()==signature:
            tr,ev=pd.read_pickle(cache)
        else:
            tr=build_samples(visible,clean_inputs=args.clean_inputs)
            ev=build_samples(visible,df.loc[hidden,'row_id'].values,clean_inputs=args.clean_inputs)
            truth=df.set_index('row_id').primary_ndvi
            ev['y']=ev.row_id.map(truth)
            pd.to_pickle((tr,ev),cache);sigpath.write_text(signature)
        pred={}
        for name in args.models:
            print('fit',name,flush=True)
            pp=[]
            for model_seed in args.seeds:
                _,_,p=fit_one(tr,ev,specs[name],args,model_seed);pp.append(p)
            pred[name]=np.mean(pp,axis=0)
        # Выбор весов ТОЛЬКО на первом фолде, по тестовым полям.
        domain=(ev.split=='test').to_numpy(); y=ev.y.to_numpy()
        if fold==0:
            names=[n for n in args.models if n!='baseline']
            mat=np.column_stack([pred[n] for n in names])
            result=minimize(lambda w:np.mean((mat[domain]@w-y[domain])**2),
                 np.ones(len(names))/len(names),bounds=[(0.,1.)]*len(names),
                 constraints={'type':'eq','fun':lambda w:w.sum()-1},method='SLSQP',
                 options={'ftol':1e-12,'maxiter':200})
            if not result.success: raise RuntimeError(result.message)
            weights=dict(zip(names,result.x.tolist()))
            choice={'weights':weights,'selection_seed':seed,'selection_scope':'test polygons'}
            (out/'selection.json').write_text(json.dumps(choice,indent=2))
        pred['ensemble']=sum(weights[n]*pred[n] for n in weights)
        pred['linear']=ev.lin.to_numpy();pred['panel_ridge_only']=ev.panel_anchor.to_numpy()
        for name,p in pred.items():
            for scope,m in [('all',np.ones(len(ev),bool)),('test_polygons',domain)]:
                score=rmse(y[m],p[m])
                item=dict(fold=fold,seed=seed,role='selection' if fold==0 else 'audit',
                          model=name,scope=scope,rmse=score,n=int(m.sum()),gapscore=gapscore(score))
                reports.append(item)
                print(name,scope,round(score,6),flush=True)
        if fold>0:
            groups=(ev.polygon+'_'+ev.date_str.str[:4]).to_numpy()[domain]
            interval=paired_interval(y[domain],pred['ensemble'][domain],pred['baseline'][domain],groups)
            print('Audit ensemble-baseline 95% interval:',interval,flush=True)
            choice.setdefault('audit',[]).append({'seed':seed,'paired_delta_rmse_95':interval})
        oo=ev[['row_id','polygon','date_str','split','y','dist_min']].copy()
        for n,p in pred.items(): oo[n]=p
        oo['fold']=fold;oofs.append(oo)
        pd.DataFrame(reports).to_csv(out/'validation.csv',index=False)
        pd.concat(oofs).to_csv(out/'validation_predictions.csv',index=False)
        (out/'selection.json').write_text(json.dumps(choice,indent=2))
    if args.skip_final:return
    print('\nFINAL: обучение на всех видимых данных',flush=True)
    tr=build_samples(df,clean_inputs=args.clean_inputs)
    target=build_samples(df,df.loc[df.is_synthetic_gap,'row_id'].values,clean_inputs=args.clean_inputs)
    final_predictions={}
    for name in args.models:
        print('final fit',name,flush=True)
        pp=[]
        for model_seed in args.seeds:
            model,cols,p=fit_one(tr,target,specs[name],args,model_seed)
            model.save_model(str(out/f'{name}_{model_seed}.cbm'))
            (out/f'{name}_features.json').write_text(json.dumps(cols))
            pp.append(p)
        final_predictions[name]=np.mean(pp,axis=0)
    final_predictions['ensemble']=sum(weights[n]*final_predictions[n] for n in weights)
    for name,p in final_predictions.items():
        write_submission(df[df.split=='test'],args.example,target,p,out/f'submission_{name}.csv')
    print('Готово:',out.resolve(),flush=True)


if __name__=='__main__':
    main()
