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

db_in_path = "./db/tvml0.db"
db_out_path = "./db/tvml.db"

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
    if os.path.isfile("./static_tokens.yaml"):
        with open("./static_tokens.yaml") as f:
            static_tokens_conf = yaml.safe_load(f)
        blocklist = [set(b) for b in static_tokens_conf.get('blocklist',[])]
        stations_arr=[f'{x}:{y}' for x in static_tokens_conf.get('stations',{}).keys() for y in static_tokens_conf['stations'][x] ]
    else:
        blocklist = list()

    model_conf = {}
    if os.path.isfile("./model_config.yaml"):
        with open("./model_config.yaml") as f:
            model_conf = yaml.safe_load(f)
    print(model_conf)

    def scale_duration(duration):
        d=min(max(duration,1),180)
        return math.log(d) / math.log(180)

    pgs=[]
    print('reading program data...', end='', file=sys.stderr, flush=True);
    for pg in stream_program_data():
        pg['ws1']=list(json.loads(pg["words1"]))
        pg['ws2']=list(json.loads(pg["words2"]))
        pg['ws']=list(itertools.chain(pg["ws1"],pg["ws2"]))
        pg['duration']=int(
            (datetime.datetime.strptime(pg['pg_end'],'%Y%m%d%H%M')
              -datetime.datetime.strptime(pg['pg_start'],'%Y%m%d%H%M')
            ).total_seconds() // 60)
        pg['genre_arr']=pg['genre'].split(',') if pg['genre'] else []
        pgs.append(pg)
        # print(pg)
    print('finish.', file=sys.stderr, flush=True)

    print('make classifier...', end='', file=sys.stderr, flush=True)
    def pg_filter4classifier(pgs):
        i=0
        for pg in pgs:
            if model_conf.get('_dev_train_max_size',-1)>0:
                if i >= model_conf['_dev_train_max_size']:
                    break
            if pg['is_target'] == 0 and pg['is_preinstalled'] == 0:
                continue
            if pg.get('interaction', '_') not in ['p','n']:
                continue
            if len(pg['ws'])<=0:
                continue
            i+=1
            yield pg
    def make_other_feature(pg):
        assert len(pg['genre_arr'])<=1, "複数ジャンルには対応していません。"
        _st=f"{pg['tuner']}:{pg['station_id']}"
        return [
            scale_duration(pg['duration']),
            int(pg['genre_arr'][0],16) if pg['genre_arr'] else 99,
            stations_arr.index(_st) if _st in stations_arr else 999,
        ]

    def to_X_pd_from_np(nparr):
        df = pd.DataFrame(nparr)
        num_cols = df.shape[1]
        df = df.rename(columns={num_cols - 2: 'genre_cat', num_cols - 1: 'station_cat'})
        # df = df.rename(columns={num_cols - 1: 'genre_cat'})
        # df = df.rename(columns={num_cols - 1: 'station_cat'})
        df['genre_cat'] = df['genre_cat'].astype(int) #.astype('category')
        df['station_cat'] = df['station_cat'].astype(int) #.astype('category')
        return df

    text_full = []
    X_text_full = []
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
        text_full.append(f"{pg['pg_title']} {pg['pg_detail']}")
        X_others.append(make_other_feature(pg))
        y_all.append(1 if pg['interaction']=='p' else 0)
    
    X_text_full = batch_vectorise(text_full, model_conf.get('transformers_tokenizer_batch_size'))
    X_text_128 = pca.fit_transform(X_text_full)
    X_all_nparr = np.hstack((
        np.array(X_text_128),
        np.array(X_others),
    ))
    y_all_nparr = np.array(y_all)

    X_all_pd = to_X_pd_from_np(X_all_nparr)

    # データを訓練用8割、テスト用2割に分割
    X_tr, X_te, y_tr, y_te = train_test_split(
        X_all_pd, y_all_nparr, test_size=0.2, random_state=43, stratify=y_all_nparr
    )

    pos_count = np.sum(y_tr == 1)
    neg_count = np.sum(y_tr == 0)
    xgb_scale_pos_weight = neg_count / pos_count if pos_count > 0 else 1
    xgb_conf = model_conf.get('xgboost',{})
    classifier = xgb.XGBClassifier(
      scale_pos_weight=xgb_scale_pos_weight,
      enable_categorical=True,
      **xgb_conf
    )
    classifier.fit(X_tr, y_tr)
    print('finish.', file=sys.stderr, flush=True);

    # 学習に使っていない「テストデータ」で予測・評価
    y_te_probs = classifier.predict_proba(X_te)[:, 1]
    y_te_preds = classifier.predict(X_te)
    print("=== テストデータでのスコア ===")
    print(classification_report(y_te, y_te_preds, target_names=["n", "p"]))
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
            if pg['is_target']==0 and pg['is_preinstalled']==0:
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
                txts = [f'{pg["pg_title"]} {pg["pg_detail"]}' for pg in pgschunk]
                inputs = tokenizer(txts, return_tensors='pt', padding=True, truncation=True).to(device)
                with torch.no_grad():
                    outputs = model(**inputs)
                    vecs = outputs.last_hidden_state.mean(dim=1).squeeze().cpu().numpy()
                    vecs = pca.transform(vecs)
                for pg,vec in zip(pgschunk, vecs):
                    pg['vec_ws0'] = vec
                    pg['vec_meta'] = np.array(make_other_feature(pg))
                vec_join = np.vstack([np.hstack((pg['vec_ws0'], pg['vec_meta'],)) for pg in pgschunk])
                df = to_X_pd_from_np(vec_join)
                for i, pg in enumerate(pgschunk):
                    pg['pred_proba'] = float(classifier.predict_proba(df)[i][1])
                    pg['pred_label'] = 'p' if pg['pred_proba'] >= 0.5 else 'n'
                for pg in pgschunk:
                    is_blocked = any(b.issubset(pg['ws']) for b in blocklist)
                    cursorz.execute('update tvml set pred_label=?, pred_proba=? where uniqk=?',[pg['pred_label'], pg['pred_proba'], pg['uniqk']])
                    if (not is_blocked) and pg['is_target'] == 1 and pg['pred_label'] == 'p':
                        print(f"{pg['pred_label']}({pg['pred_proba']:.4f}) {pg['pg_title']} {pg['pg_detail']}")
    finally:
        connz.close()
    print('finish.', file=sys.stderr, flush=True)
    os.replace(db_in_path, db_out_path)

if __name__ == "__main__":
    main()
