"""V5: sensor-conditional NDVI + classifier источника; все сырые NDVI сенсоров.

Для каждого примера исключается весь снимок своего поля. Другие поля той же
даты доступны. Статистики связи полей обучаются без целевого года.
"""
from pathlib import Path
import argparse
import json
import sys
import numpy as np
import pandas as pd
from catboost import CatBoostRegressor,CatBoostClassifier,Pool


def sensor_features(v3,visible,base):
    dates=np.sort(visible.date.unique()).astype('datetime64[D]').astype(int)
    ids=sorted(visible.anon_polygon_id.unique());pi={p:i for i,p in enumerate(ids)}
    ti={int(t):i for i,t in enumerate(dates)};years=pd.to_datetime(dates,unit='D').year.to_numpy()
    mats=[]
    for s in v3.SENSORS:
        m=visible.pivot(index='date',columns='anon_polygon_id',values=s+'_ndvi').reindex(columns=ids).to_numpy(float)
        m[(m < -1)|(m > 1)]=np.nan;mats.append(m)
    req=base[['row_id','polygon','date_str','year']]
    extras=[{} for _ in mats]
    for pnum,(pid,q) in enumerate(req.groupby('polygon',sort=False)):
        j=pi[pid];cols=np.array([k for k in range(len(ids)) if k!=j])
        for si,m in enumerate(mats):
            own=m[:,j];other=m[:,cols]
            known=np.isfinite(own);kt=dates[known];kv=own[known]
            for year,g in q.groupby('year'):
                fit=(years!=year)[:,None]&np.isfinite(own[:,None])&np.isfinite(other)
                n=fit.sum(0);den=np.maximum(n,1)
                xx=np.where(fit,other,0.);yy=np.where(fit,own[:,None],0.)
                mx=xx.sum(0)/den;my=yy.sum(0)/den
                vx=(xx*xx).sum(0)/den-mx**2;vy=(yy*yy).sum(0)/den-my**2
                cov=(xx*yy).sum(0)/den-mx*my
                beta=np.clip(cov/np.maximum(vx,1e-6),.2,2.)
                beta=(beta*n+30)/(n+30);intercept=my-beta*mx
                corr=np.clip(cov/np.sqrt(np.maximum(vx*vy,1e-10)),0.,1.)
                weights=corr**4*n/(n+40);weights[n<15]=0
                pair=np.isfinite(own[:,None])&np.isfinite(other)
                diff=np.where(pair,own[:,None]-beta*other,0.)
                cs=np.vstack([np.zeros(len(cols)),np.cumsum(diff,axis=0)])
                cn=np.vstack([np.zeros(len(cols)),np.cumsum(pair,axis=0)])
                for row in g.itertuples():
                    t=int(np.datetime64(row.date_str,'D').astype(int));ix=ti[t]
                    keep=kt!=t;ts=kt[keep];vs=kv[keep];pos=np.searchsorted(ts,t)
                    f={'native_lin':float(np.interp(t,ts,vs)) if len(ts) else np.nan}
                    for k in range(3):
                        l=pos-1-k;r=pos+k
                        f[f'native_prev{k}']=float(vs[l]) if l>=0 else np.nan
                        f[f'native_prev{k}_days']=float(t-ts[l]) if l>=0 else np.nan
                        f[f'native_next{k}']=float(vs[r]) if r<len(ts) else np.nan
                        f[f'native_next{k}_days']=float(ts[r]-t) if r<len(ts) else np.nan
                    window=np.abs(ts-t)<=45
                    near=vs[window]
                    f['native_mean45']=float(np.mean(near)) if len(near) else np.nan
                    f['native_std45']=float(np.std(near)) if len(near) else np.nan
                    # Сырые значения других полей: собственная колонка всегда NaN.
                    for k,other_pid in enumerate(ids):
                        f[f'donor_{other_pid}']=float(m[ix,k]) if k!=j else np.nan
                    avail=np.isfinite(other[ix]);w=weights.copy()
                    f['native_day_count']=int(avail.sum())
                    f['native_day_mean']=float(np.nanmean(other[ix])) if avail.any() else np.nan
                    for wd in (45,120):
                        lo=np.searchsorted(dates,t-wd);hi=np.searchsorted(dates,t+wd,side='right')
                        count=cn[hi]-cn[lo]-pair[ix]
                        total=cs[hi]-cs[lo]-diff[ix]
                        bias=(total+2*intercept)/(count+2)
                        pp=beta*other[ix]+bias;ww=w*count/(count+3)
                        order=np.argsort(-ww);usable=avail&(count>=2)&(ww>0)
                        for top in (1,3,8,59):
                            take=order[usable[order]][:top];wt=ww[take]
                            f[f'native_peer{wd}_{top}']=float(np.dot(wt,pp[take])/wt.sum()) if wt.sum()>0 else np.nan
                            f[f'native_peer{wd}_{top}_weight']=float(wt.sum())
                    extras[si][row.row_id]=f
        if (pnum+1)%10==0:print('Sensor features fields',pnum+1,flush=True)
    return [pd.DataFrame.from_dict(x,orient='index').rename_axis('row_id') for x in extras]


def make_tables(v3,visible,base):
    extra=sensor_features(v3,visible,base)
    classifier=base.copy()
    for si,s in enumerate(v3.SENSORS):
        cols=['native_prev0_days','native_next0_days','native_day_count','native_lin']
        classifier=classifier.merge(extra[si][cols].add_prefix(s+'_'),on='row_id',how='left',validate='one_to_one')
    tables=[]
    for si,s in enumerate(v3.SENSORS):
        table=base.merge(extra[si],on='row_id',how='left',validate='one_to_one')
        # Полигон — известная категория: видимые точки этих же полей есть в обучении.
        table['field_category']=table.polygon.astype(str);table['source_candidate']=s
        a,b=v3.TO_LANDSAT[s]
        table['native_anchor']=table.native_lin.fillna((table.lin_harm-b)/a).fillna(.3)
        for c in extra[si]:
            if not c.startswith('donor_') and '_days' not in c and '_weight' not in c and c!='native_day_count':
                table[c+'_minus_anchor']=table[c]-table.native_anchor
        tables.append(table)
    classifier['field_category']=classifier.polygon.astype(str)
    return classifier,tables


def train_predict(v3,visible,truth,tr,ev,args):
    base=pd.concat([tr,ev],ignore_index=True)
    clf,tables=make_tables(v3,visible,base)
    train_ids=set(tr.row_id);trainmask=clf.row_id.isin(train_ids).to_numpy()
    source=truth.set_index('row_id').sensor
    labels=clf.row_id.map(source).map({s:i for i,s in enumerate(v3.SENSORS)})
    cols=[c for c in clf if c not in v3.META]
    cmask=trainmask&labels.notna().to_numpy()
    model=CatBoostClassifier(iterations=900,depth=6,learning_rate=.04,l2_leaf_reg=6,
        random_seed=42,thread_count=4,verbose=False,allow_writing_files=False,loss_function='MultiClass')
    model.fit(Pool(clf.loc[cmask,cols],labels[cmask].astype(int),cat_features=['crop','field_category']))
    probabilities=model.predict_proba(clf.loc[~trainmask,cols])
    clabel=labels[~trainmask].to_numpy()
    accuracy=float(np.mean(np.argmax(probabilities,axis=1)==clabel)) if np.isfinite(clabel).any() else None
    regtrain=[];regeval=[]
    raw=visible.set_index('row_id')
    for si,s in enumerate(v3.SENSORS):
        tab=tables[si];tm=tab.row_id.isin(train_ids)
        y=tab.row_id.map(raw[s+'_ndvi'])
        valid=tm&y.notna()
        tt=tab.loc[valid].copy();tt['y']=y[valid].values;regtrain.append(tt)
        regeval.append(tab.loc[~tm].copy())
    train=pd.concat(regtrain,ignore_index=True);target=pd.concat(regeval,ignore_index=True)
    features=[c for c in train if c not in v3.META]
    reg=CatBoostRegressor(iterations=args.iterations,depth=7,learning_rate=.03,l2_leaf_reg=8.,
        random_seed=42,thread_count=4,verbose=False,allow_writing_files=False,loss_function='RMSE')
    reg.fit(Pool(train[features],train.y-train.native_anchor,
                 cat_features=['crop','field_category','source_candidate']))
    pp=np.clip(target.native_anchor.to_numpy()+reg.predict(target[features]),-.1,1.)
    preds=np.stack(np.split(pp,3),axis=1)
    soft=(probabilities*preds).sum(1)
    hard=preds[np.arange(len(preds)),np.argmax(probabilities,axis=1)]
    # Oracle только для диагностики: истинный сенсор не используется в submission.
    oracle=preds[np.arange(len(preds)),np.nan_to_num(clabel).astype(int)] if accuracy is not None else None
    payload={'classifier':model,'regressor':reg,'classifier_features':cols,'regressor_features':features}
    return soft,hard,oracle,accuracy,payload


def main():
    p=argparse.ArgumentParser();p.add_argument('--train',required=True);p.add_argument('--test',required=True)
    p.add_argument('--example');p.add_argument('--v3-dir',required=True);p.add_argument('--results',required=True)
    p.add_argument('--iterations',type=int,default=1800);p.add_argument('--final',action='store_true')
    p.add_argument('--final-only',action='store_true')
    args=p.parse_args();sys.path.insert(0,str(Path(args.v3_dir).resolve()));import ndvi_v3 as v3
    root=Path(args.results);root.mkdir(parents=True,exist_ok=True);old=Path(args.v3_dir)/'results'
    df=v3.read_inputs(args.train,args.test);report=[]
    for seed in (() if args.final_only else (2026,9071)):
        tr,ev=pd.read_pickle(old/f'features_cv_{seed}.pkl');vis=v3.masked(df,ev.row_id.to_numpy())
        soft,hard,oracle,acc,payload=train_predict(v3,vis,df,tr,ev,args)
        print('Sensor accuracy',seed,acc,flush=True)
        oo=ev[['row_id','polygon','date_str','split','y']].copy()
        for name,pred in [('soft',soft),('hard',hard),('oracle_sensor_DIAGNOSTIC_ONLY',oracle)]:
            oo[name]=pred
            for scope,mask in [('all',np.ones(len(ev),bool)),('test_polygons',ev.split=='test')]:
                item=dict(seed=seed,model=name,scope=scope,rmse=v3.rmse(ev.y[mask],pred[mask]))
                print(item,flush=True);report.append(item)
        oo.to_csv(root/f'predictions_{seed}.csv',index=False)
        pd.DataFrame(report).to_csv(root/'validation.csv',index=False)
    if args.final or args.final_only:
        tr=v3.samples(df);ev=v3.samples(df,df.loc[df.is_synthetic_gap,'row_id'].values)
        soft,hard,_,_,payload=train_predict(v3,df,df,tr,ev,args)
        v3.write_submission(df[df.split=='test'],args.example,ev,soft,root/'submission_v5.csv')
        for name in ['classifier','regressor']:payload[name].save_model(str(root/f'{name}.cbm'))
        (root/'features.json').write_text(json.dumps({k:v for k,v in payload.items() if k.endswith('features')}))

if __name__=='__main__':main()
