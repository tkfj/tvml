import json
import sqlite3
import itertools
import datetime
import math
import os
import sys
import yaml
import xgboost as xgb
import numpy as np
import pandas as pd
import plotext as plt
from tqdm import tqdm

from typing import Iterator, Dict
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, roc_auc_score, log_loss
from sklearn.metrics import roc_curve
from transformers import AutoTokenizer, AutoModel
from sklearn.decomposition import PCA
import torch

from common_genre import GenreUtil

db_in_path = "./db/tvmlw.db"
db_out_path = "./db/tvml.db"

genre_util = GenreUtil()

def stream_program_data() -> Iterator[Dict]:
    """
    データベースから番組情報を1件ずつ辞書形式で返すジェネレータ
    """
    conn = sqlite3.connect(db_in_path)
    try:
        conn.row_factory = sqlite3.Row  # カラム名でアクセス可能にする
        cursor = conn.cursor()
        cursor.execute("""
SELECT *
, MAX(asof) OVER() AS asof_max
FROM tvml
        """)
        for row in cursor:
            yield dict(row)
    finally:
        conn.close()

def main():

    with open("./conf/absolute_defence_line.yaml") as f:
        adl_def = yaml.safe_load(f)

    model_conf = {}
    with open("./conf/model_config.yaml") as f:
        model_conf = yaml.safe_load(f)
    print(model_conf)

    def scale_duration(duration):
        d=min(max(duration/1000/60,1),180)
        return math.log(d) / math.log(180)

    pgs=[]
    print('reading program data...', end='', file=sys.stderr, flush=True);
    for pg in stream_program_data():
        pg['ws1']=list(json.loads(pg["token_title_ipa"] or '[]'))
        pg['ws2']=list(json.loads(pg["token_description_ipa"] or '[]'))
        pg['ws']=list(itertools.chain(pg["ws1"],pg["ws2"]))
        pg['genres_arr'] = [g['lv1'] for g in json.loads(pg['genres']) if g['lv1'] not in [14]] if pg['genres'] else []
        pgs.append(pg)

    print('finish.', file=sys.stderr, flush=True)

    print('make classifier...', end='', file=sys.stderr, flush=True)
    def pg_filter4classifier(pgs):
        i=0
        for pg in pgs:
            if model_conf.get('_dev_train_max_size',-1)>0:
                if i >= model_conf['_dev_train_max_size']:
                    break
            if pg['is_target_channel'] == 0:#  and pg['is_preinstalled'] == 0:
                continue
            if pg.get('interaction', '-') not in ['P','N']:
                continue
            if len(pg['ws'])<=0:
                continue
            i+=1
            yield pg

    def make_absolute_defence_line(pg):
        _adltxt = pg.get('defence_features')
        _adl = json.loads(_adltxt) if _adltxt else {}
        return {_fea: float(_adl.get(_fea, 0.0)) for _fea in adl_def['features'].keys() }

    other_feature_names = list(itertools.chain(
        ['duration', 'genre1_cat', 'channel_cat'],
        genre_util.featurenames,
    ))
    def make_other_feature(pg):
        return list(itertools.chain([
            scale_duration(pg['duration']),
            pg['genres_arr'][0] if pg['genres_arr'] and len(pg['genres'])>0 else 99,
            pg['network_id']*100000+pg['service_id'],
        ], genre_util.generate_features(pg['genres']),
        ))
    
    def to_X_pd_from_np(nparr):
        df = pd.DataFrame(nparr, columns=list(itertools.chain(
            [f'bert_{i+1}' for i in range(pca_conf['n_components'])],
            adl_def['features'].keys(),
            other_feature_names,
        )))
        df['genre1_cat'] = df['genre1_cat'].astype(int) #.astype('category')
        df['channel_cat'] = df['channel_cat'].astype(int) #.astype('category')
        return df

    text_full = []
    X_text_full = []
    X_adl = []
    X_others = []
    y_all = []
    device=model_conf.get('transformers_model_device')
    tokenizer = AutoTokenizer.from_pretrained(model_conf.get('transformers_tokenizer'))
    model = AutoModel.from_pretrained(model_conf.get('transformers_tokenizer')).to(device)
    pca_conf = model_conf.get('pca',{})
    pca = PCA(**pca_conf)

    def batch_vectorise(texts, batch_size=512):
        vectors = []
        for texts_chunk in itertools.batched(tqdm(texts), batch_size):
            inputs = tokenizer(texts_chunk, return_tensors="pt", padding=True, truncation=True).to(device)
            with torch.no_grad():
                outputs = model(**inputs)
                # 各バッチの結果 (batch_size, 768) を取得
                batch_features = outputs.last_hidden_state.mean(dim=1).cpu().numpy()
                vectors.append(batch_features)
        return np.vstack(vectors)

    for pg in pg_filter4classifier(pgs):
        text_full.append(f"{pg['pgm_title'] or ''} {pg['pgm_description'] or ''}")
        _adl = make_absolute_defence_line(pg)
        X_adl.append([_sc for _sc in _adl.values()])
        X_others.append(make_other_feature(pg))
        y_all.append(1 if pg['interaction']=='P' else 0)

    X_text_full = batch_vectorise(text_full, model_conf.get('transformers_tokenizer_batch_size'))
    X_text_pca = pca.fit_transform(X_text_full)
    X_nparr_all = np.hstack((
        np.array(X_text_pca),
        np.array(X_adl),
        np.array(X_others),
    ))
    y_nparr_all = np.array(y_all)
    X_pd_all = to_X_pd_from_np(X_nparr_all)
    print(X_pd_all)

    monotone_constraints = tuple(itertools.chain(
        [0] * pca_conf['n_components'],
        [adl_def['features'][_k].get('monotone_constraints', 0) for _k in adl_def['features'].keys()],
        [0] * len(other_feature_names),
    ))
    print(monotone_constraints)

    # データを訓練用8割、テスト用2割に分割
    X_tr, X_te, y_tr, y_te = train_test_split(
        X_pd_all, y_nparr_all, test_size=0.2, random_state=43, stratify=y_nparr_all
    )

    pos_count = np.sum(y_tr == 1)
    neg_count = np.sum(y_tr == 0)
    xgb_scale_pos_weight = neg_count / pos_count if pos_count > 0 else 1
    xgb_conf = model_conf.get('xgboost',{})
    classifier = xgb.XGBClassifier(
      scale_pos_weight=xgb_scale_pos_weight,
      enable_categorical=True,
      monotone_constraints = monotone_constraints,
      **xgb_conf
    )
    classifier.fit(X_tr, y_tr)
    print('finish.', file=sys.stderr, flush=True);

    # 学習に使っていない「テストデータ」で予測・評価
    y_te_probs = classifier.predict_proba(X_te)[:, 1]
    y_te_preds = classifier.predict(X_te)
    print("=== テストデータでのスコア ===")
    print(classification_report(y_te, y_te_preds, target_names=["N", "P"]))
    auc = roc_auc_score(y_te, y_te_probs)
    print(f"ROC-AUC Score: {auc:.4f}")
    loss = log_loss(y_te, y_te_probs)
    print(f"Log Loss: {loss:.4f}")

    fpr, tpr, thresholds = roc_curve(y_te, y_te_probs)
    plt.clf()  # グラフの初期化
    plt.plot(fpr, tpr, label="ROC Curve")
    plt.title("ROC Curve (CUI Plot)")
    plt.xlabel("False Positive Rate")
    plt.ylabel("True Positive Rate")
    # グラフのサイズをターミナルに合わせる設定（お好みで調整）
    plt.plotsize(60, 60)
    plt.show()

    def pg_filtered(pgs):
        i=0
        for pg in pgs:
            if model_conf.get('_dev_predict_max_size',-1)>0:
                if i >= model_conf['_dev_predict_max_size']:
                    break
            if pg['is_target_channel']==0:
                continue
            if pg['asof']!=pg['asof_max']:
                continue
            i+=1
            yield pg

    print('make predict...', end='', file=sys.stderr, flush=True)
    connz = sqlite3.connect(db_in_path)
    try:
        connz.row_factory = sqlite3.Row
        cursorz = connz.cursor()
        with connz:
            for pgschunk in itertools.batched(tqdm(pg_filtered(pgs)), model_conf.get('transformers_tokenizer_batch_size')):
                txts = [f'{pg["pgm_title"] or ''} {pg["pgm_description"] or ''}' for pg in pgschunk]
                inputs = tokenizer(txts, return_tensors='pt', padding=True, truncation=True).to(device)
                with torch.no_grad():
                    outputs = model(**inputs)
                    vecs = outputs.last_hidden_state.mean(dim=1).squeeze().cpu().numpy()
                    vecs = pca.transform(vecs)
                for pg,vec in zip(pgschunk, vecs):
                    pg['vec_ws0'] = vec
                    pg['adl'] = make_absolute_defence_line(pg)
                    pg['vec_adl'] = np.array([_sc for _sc in pg['adl'].values()])
                    pg['vec_meta'] = np.array(make_other_feature(pg))
                vec_join = np.vstack([np.hstack((pg['vec_ws0'], pg['vec_adl'], pg['vec_meta'],)) for pg in pgschunk])
                df = to_X_pd_from_np(vec_join)
                for i, pg in enumerate(pgschunk):
                    pg['pred_proba'] = float(classifier.predict_proba(df)[i][1])
                    pg['pred_label'] = 'P' if pg['pred_proba'] >= 0.5 else 'N'
                for pg in pgschunk:
                    cursorz.execute('update tvml set pred_label=?, pred_proba=? where tvml_id=?',[pg['pred_label'], pg['pred_proba'], pg['tvml_id']])
                    if pg['is_target_channel'] == 1 and pg['pred_label'] == 'P':
                        print(f"{pg['pred_label']}({pg['pred_proba']:.4f}) {pg['pgm_title']} {pg['pgm_description']}")

    finally:
        connz.close()
    print('finish.', file=sys.stderr, flush=True)
    os.replace(db_in_path, db_out_path)

if __name__ == "__main__":
    main()
