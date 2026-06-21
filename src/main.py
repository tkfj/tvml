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
from gensim.models.doc2vec import Doc2Vec, TaggedDocument
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

    print('create tags...', end='', file=sys.stderr, flush=True)
    tagged_data = list(itertools.chain([
        TaggedDocument(
            words=pg['ws'],
            tags=[pg['uniqk']]
        )
        for pg in pgs if len(pg['ws'])>0
    ]))
    print('finish.', file=sys.stderr, flush=True)

    print('doc2vec...', end='', file=sys.stderr, flush=True)
    doc2vec_conf = model_conf.get('doc2vec',{})
    doc2vec_conf['workers'] = max(os.cpu_count(),10) if doc2vec_conf.get('workers',-1)<0 else 3
    d2v_model = Doc2Vec(
        documents=tagged_data,
        **doc2vec_conf,
    )
    print('finish.', file=sys.stderr, flush=True)

    print('make classifier...', end='', file=sys.stderr, flush=True)
    def pg_filter4classifier(pgs):
        for i, pg in enumerate(pgs):
            # if i > 1000:
            #     break
            if pg['is_target'] == 0 and pg['is_preinstalled'] == 0:
                continue
            if pg.get('interaction', '_') not in ['p','n']:
                continue
            if len(pg['ws'])<=0:
                continue
            yield pg
    def make_other_feature(pg):
        assert len(pg['genre_arr'])<=1, "複数ジャンルには対応していません。"
        _st=f"{pg['tuner']}:{pg['station_id']}"
        return [
            scale_duration(pg['duration']),
            int(pg['genre_arr'][0],16) if pg['genre_arr'] else 99,
            stations_arr.index(_st) if _st in stations_arr else 999,
            # *[ 1 if x in pg['genre_arr'] else 0 for x in list('0123456789ABCDEF')],
            # *[ 1 if x == f"{pg['tuner']}:{pg['station_id']}" else 0 for x in stations_arr],
        ]
    # xx={
    #     'duration': 120,
    #     'genre_arr': ["F"],
    #     'tuner': 'cs',
    #     'station_id': '309'
    # }
    # print(make_other_feature(xx))


    def to_X_pd_from_np(nparr):
        df = pd.DataFrame(nparr)
        num_cols = df.shape[1]
        df = df.rename(columns={num_cols - 2: 'genre_cat', num_cols - 1: 'station_cat'})
        # df = df.rename(columns={num_cols - 1: 'genre_cat'})
        # df = df.rename(columns={num_cols - 1: 'station_cat'})
        df['genre_cat'] = df['genre_cat'].astype(int) #.astype('category')
        df['station_cat'] = df['station_cat'].astype(int) #.astype('category')
        return df

    X_text_full = []
    X_others = []
    y_all = []
    device='cuda'
    tokenizer = AutoTokenizer.from_pretrained("cl-tohoku/bert-base-japanese-v3")
    model = AutoModel.from_pretrained("cl-tohoku/bert-base-japanese-v3").to(device)
    pca = PCA(n_components = 64)
    # (これは学習データのBERTベクトル全体で一度 fit_transform しておく)
    # pca = PCA(n_components=128) 
    # X_tr_bert_128d = pca.fit_transform(X_tr_bert_768d)
    for pg in tqdm(pg_filter4classifier(pgs)):
        inputs = tokenizer(f"{pg['pg_title']} {pg['pg_detail']}", return_tensors='pt', padding=True, truncation=True).to(device)
        with torch.no_grad():
            outputs = model(**inputs)
            vec = outputs.last_hidden_state.mean(dim=1).squeeze().cpu().numpy()
        # print("ベクトルの形状:", vec.shape)  # ➔ (768,)
        # print("正常にCPUでベクトル化できました！")
        # vec = d2v_model.dv[pg['uniqk']]
        X_text_full.append(vec)
        X_others.append(make_other_feature(pg))
        y_all.append(1 if pg['interaction']=='p' else 0)
    
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
        for pg in pgs:
            if pg['is_target']==0 and pg['is_preinstalled']==0:
                continue
            if pg['asof']!=pg['asof_max']:
                continue
            yield pg

    def pred1(ws, pg, classifier):
        inputs = tokenizer(ws, return_tensors='pt', padding=True, truncation=True).to(device)
        with torch.no_grad():
            outputs = model(**inputs)
            vec = outputs.last_hidden_state.mean(dim=1).squeeze().cpu().numpy().reshape(1, -1)
            vec = pca.transform(vec)
        # vec = d2v_model.infer_vector(ws, epochs=100, alpha=0.025, min_alpha=0.001).reshape(1, -1)
        others = np.array(make_other_feature(pg)).reshape(1, -1)
        vec_join = np.hstack((vec, others,))
        df = to_X_pd_from_np(vec_join)
        # pred_label = 'p' if classifier.predict(df)[0] == 1 else 'n'
        pred_proba = float(classifier.predict_proba(df)[0][1])
        pred_label = 'p' if pred_proba >= 0.5 else 'n'
        return pred_label, pred_proba

    def pred(pg, classifier):
        pred_label0=None
        pred_label1=None
        pred_label2=None

        if len(pg['ws'])>0:
            pred_label0, pred_proba0 = pred1(f"{pg['pg_title']} {pg['pg_detail']}", pg, classifier)
            if pred_label0 and pred_label0 == 'p':
                return pred_label0, pred_proba0

        if len(pg['ws1'])>0:
            pred_label1, pred_proba1 = pred1(pg['pg_title'], pg, classifier)
            if pred_label1 and pred_label1 == 'p':
                return pred_label1, pred_proba1

        if len(pg['ws2'])>0:
            pred_label2, pred_proba2 = pred1(pg['pg_detail'], pg, classifier)
            if pred_label2 and pred_label2 == 'p':
                return pred_label2, pred_proba2

        if pred_label1 and pred_label0 and pred_label1 == pred_label0:
            return pred_label1, max(pred_proba1, pred_proba0)
        elif pred_label2 and pred_label0 and pred_label2 == pred_label0:
            return pred_label2, max(pred_proba2, pred_proba0)
        elif pred_label1 and pred_label2 and pred_label1 == pred_label2:
            return pred_label1, max(pred_proba1, pred_proba2)
        elif pred_label0:
            return pred_label0, pred_proba0
        elif pred_label1:
            return pred_label1, pred_proba1
        elif pred_label2:
            return pred_label2, pred_proba2
        return None, None

    print('make predict...', end='', file=sys.stderr, flush=True)
    connz = sqlite3.connect(db_in_path)
    try:
        connz.row_factory = sqlite3.Row
        cursorz = connz.cursor()
        with connz:
            for pg in tqdm(pg_filtered(pgs)):
                is_blocked = any(b.issubset(pg['ws']) for b in blocklist)
                pred_label, pred_proba = pred(pg, classifier)
                if pred_label and pred_proba:
                    cursorz.execute('update tvml set pred_label=?, pred_proba=? where uniqk=?',[pred_label, pred_proba, pg['uniqk']])
                    if (not is_blocked) and pg['is_target'] == 1 and pred_label == 'p':
                        print(f'{pred_label}({pred_proba:.4f}) {pg["pg_title"]} {pg["pg_detail"]}')
    finally:
        connz.close()
    print('finish.', file=sys.stderr, flush=True)
    os.replace(db_in_path, db_out_path)

if __name__ == "__main__":
    main()
