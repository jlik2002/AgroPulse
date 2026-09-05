"""Преобразование NDVI конкретной съёмки по другим полям.

Сначала для каждого поля оценивается значение без наблюдения целевой даты.
Затем сопоставление «ожидаемое -> измеренное» строится по другим полям снимка.
Отдельно оцениваются общий и локальный (по связанным полям) сдвиг и масштаб.
"""
import numpy as np
import pandas as pd


def scene_features(v3,visible,base,context=None):
    ids=sorted(visible.anon_polygon_id.unique());pi={p:i for i,p in enumerate(ids)}
    dates=np.sort(visible.date.unique()).astype('datetime64[D]').astype(int)
    ti={int(t):i for i,t in enumerate(dates)};years=pd.to_datetime(dates,unit='D').year.to_numpy()
    queries=base[['row_id','polygon','date_str','year']]
    # ЕДИНСТВЕННОЕ ОТЛИЧИЕ ОТ АРХИВНОГО ФАЙЛА (см. README пакета).
    # smooth — общая матрица ожидаемых значений по всем полям и датам: ниже
    # из неё берутся ожидания ДРУГИХ полей той же съёмки. Заполняется она
    # только в ячейках перечисленных здесь строк, поэтому набор строк влияет
    # на признаки соседей. При обучении сюда приходил весь кадр целиком.
    # Предсказанию нужно считать признаки лишь для целевых строк, но матрицу
    # заполнять по-прежнему целиком — иначе ожидания соседей окажутся пустыми
    # и признаки съёмки молча выродятся. context разделяет эти два множества.
    # По умолчанию context=None — поведение архивного файла в точности.
    filled=queries if context is None else context[['row_id','polygon','date_str','year']]
    smooth=np.full((len(dates),len(ids)),np.nan)
    for pid,f in visible.groupby('anon_polygon_id',sort=False):
        j=pi[pid];ctx=v3.PolygonContext(f)
        q=filled[filled.polygon==pid]
        for year,g in q.groupby('year'):
            same=ctx.k_year==year;ts=ctx.k_t[same];hs=ctx.k_h[same]
            good=np.isfinite(hs)&(hs>=-.2)&(hs<=1.2);ts=ts[good];hs=hs[good]
            for row in g.itertuples():
                t=int(np.datetime64(row.date_str,'D').astype(int));keep=ts!=t
                tt=ts[keep];vv=hs[keep]
                if len(tt):
                    choose=np.argsort(np.abs(tt-t))[:8];dx=(tt[choose]-t)/20.;y=vv[choose]
                    w0=np.exp(-np.abs(dx));w=w0.copy();a=np.column_stack([np.ones(len(dx)),dx])
                    for _ in range(3):
                        coef=np.linalg.solve(a.T@(w[:,None]*a)+np.diag([1e-8,.04]),a.T@(w*y))
                        r=y-a@coef;scale=max(.03,float(1.4826*np.median(np.abs(r-np.median(r)))))
                        w=w0*np.minimum(1.,1.5*scale/np.maximum(np.abs(r),1e-8))
                    smooth[ti[t],j]=coef[0]
                else:smooth[ti[t],j]=.3
    output=[{} for _ in range(3)]
    for si,s in enumerate(v3.SENSORS):
        aa,bb=v3.TO_LANDSAT[s]
        expected=(smooth-bb)/aa
        observed=visible.pivot(index='date',columns='anon_polygon_id',values=s+'_ndvi').reindex(columns=ids).to_numpy(float)
        residual=observed-expected
        # Веса связи определяются по умеренным остаткам; наблюдения текущей съёмки не клипуются.
        bounded=np.clip(residual,-.3,.3)
        for pnum,(pid,q) in enumerate(queries.groupby('polygon',sort=False)):
            j=pi[pid];cols=np.array([k for k in range(len(ids)) if k!=j])
            for year,g in q.groupby('year'):
                own=bounded[:,j,None];others=bounded[:,cols]
                mask=(years!=year)[:,None]&np.isfinite(own)&np.isfinite(others)
                n=mask.sum(0);den=np.maximum(n,1);x=np.where(mask,others,0);y=np.where(mask,own,0)
                mx=x.sum(0)/den;my=y.sum(0)/den
                vx=(x*x).sum(0)/den-mx*mx;vy=(y*y).sum(0)/den-my*my
                cov=(x*y).sum(0)/den-mx*my
                corr=np.clip(cov/np.sqrt(np.maximum(vx*vy,1e-10)),0,1)
                peerweight=corr**3*n/(n+30);peerweight[n<15]=0
                for row in g.itertuples():
                    t=int(np.datetime64(row.date_str,'D').astype(int));i=ti[t]
                    z=float(expected[i,j]);xx=expected[i,cols];yy=observed[i,cols]
                    valid=np.isfinite(xx)&np.isfinite(yy);f={'scene_temporal':z}
                    for name,weights in [('global',np.ones(len(cols))),('related',peerweight)]:
                        good=valid&(weights>0);xv=xx[good];yv=yy[good];w=weights[good]
                        tag='scene_'+name
                        f[tag+'_count']=int(len(xv));f[tag+'_support']=float(w.sum())
                        if len(xv):
                            w=w/w.sum();rr=yv-xv
                            mean=float(np.dot(w,rr));f[tag+'_shift']=mean
                            f[tag+'_offset_prediction']=z+mean
                            f[tag+'_spread']=float(np.sqrt(np.dot(w,(rr-mean)**2)))
                            # y - x = offset + gain_delta*(x - z); ridge к identity.
                            design=np.column_stack([np.ones(len(xv)),xv-z])
                            for robust in (False,True):
                                ww=w.copy()
                                for _ in range(3 if robust else 1):
                                    coef=np.linalg.solve(design.T@(ww[:,None]*design)+np.diag([.02,.04]),design.T@(ww*rr))
                                    err=rr-design@coef;scale=max(.03,float(1.4826*np.median(np.abs(err-np.median(err)))))
                                    ww=w*np.minimum(1.,1.5*scale/np.maximum(np.abs(err),1e-8))
                                suffix='robust' if robust else 'affine'
                                f[tag+'_'+suffix]=z+float(coef[0])
                                f[tag+'_'+suffix+'_gain']=1+float(coef[1])
                        else:
                            for key in ['shift','spread','offset_prediction','affine','affine_gain','robust','robust_gain']:f[tag+'_'+key]=np.nan
                    output[si][row.row_id]=f
            if (pnum+1)%20==0:print('Scene features',s,'fields',pnum+1,flush=True)
    return [pd.DataFrame.from_dict(d,orient='index').rename_axis('row_id') for d in output]
