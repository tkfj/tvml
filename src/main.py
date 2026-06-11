import json
import sqlite3
import itertools
import os
import yaml
from typing import Iterator, Dict

from gensim.models.doc2vec import Doc2Vec, TaggedDocument
from sklearn.svm import SVC
from sklearn.calibration import CalibratedClassifierCV
import numpy as np

db_path = "./db/tvml.db"

def stream_program_data() -> Iterator[Dict]:
    """
    データベースから番組情報を1件ずつ辞書形式で返すジェネレータ
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # カラム名でアクセス可能にする
    cursor = conn.cursor()

    try:
        cursor.execute("""
SELECT * FROM tvml
WHERE
(src = 0)
OR
(src in (1,9) AND interaction in ('p', 'n'))
        """)
        for row in cursor:
            yield dict(row)
    finally:
        conn.close()

def main():
    pgs=[]
    for pg in stream_program_data():
        pg['id']=str(pg["src"])+":"+str(pg["pgm_uid"])
        pg['ws1']=list(json.loads(pg["words1"]))
        pg['ws2']=list(json.loads(pg["words2"]))
        pg['ws']=list(itertools.chain(pg["ws1"],pg["ws2"]))
        pgs.append(pg)
        print(pg)

    # タイトルのみと、タイトル＋説明でベクトルデータを作る
    # 長すぎる説明で発散しないようにするため
    tagged_data = list(itertools.chain([
        TaggedDocument(
            words=pg['ws1'],
            tags=[f"{pg['id']}:title"]
        )
        for pg in pgs if len(pg['ws1'])>0
    ],[
        TaggedDocument(
            words=pg['ws2'],
            tags=[f"{pg['id']}:detail"]
        )
        for pg in pgs if len(pg['ws2'])>0
    ],[
        TaggedDocument(
            words=pg['ws'],
            tags=[f"{pg['id']}:all"]
        )
        for pg in pgs if len(pg['ws'])>0
    ]))

    d2v_model = Doc2Vec(
        documents=tagged_data,
        vector_size=64,     # 少ないデータなので64〜100がベスト
        dm=0,
        min_count=2,
        workers=4,
        epochs=50,           # 繰り返し学習回数を少し多めにして定着させる
        negative=10
    )
    for word in ["ショッピング", "サスペンス", "WEC", "FORMULA", "EWC"]:
        if word in d2v_model.wv:
            similars = d2v_model.wv.most_similar(word, topn=5)
            for t, score in similars:
                print(f"{word} {t}: {score:.4f}")
        else:
            print(f"'{word}' is NOT in the vocabulary.")

    X_train = []
    y_train = []
    
    for pg in pgs:
        if pg.get('interaction') and pg['interaction'] in ['p','n']:
            if len(pg['ws1'])>0:
                vec = d2v_model.dv[f"{pg['id']}:title"]
                X_train.append(vec)
                y_train.append(pg['interaction'])
            if len(pg['ws2'])>0:
                vec = d2v_model.dv[f"{pg['id']}:detail"]
                X_train.append(vec)
                y_train.append(pg['interaction'])
            if len(pg['ws'])>0:
                vec = d2v_model.dv[f"{pg['id']}:all"]
                X_train.append(vec)
                y_train.append(pg['interaction'])
    
    base_svc = SVC(kernel='rbf', C=0.3, gamma=0.02, class_weight='balanced', random_state=43)
    classifier = CalibratedClassifierCV(estimator=base_svc, ensemble=False)
    classifier.fit(X_train, y_train)

    connz = sqlite3.connect(db_path)
    connz.row_factory = sqlite3.Row
    cursorz = connz.cursor()

    if os.path.isfile("./static_tokens.yaml"):
        with open("./static_tokens.yaml") as f:
            static_tokens_conf = yaml.safe_load(f)
        blocklist = [set(b) for b in static_tokens_conf.get('blocklist',[])]
    else:
        blocklist = list()

    try:
        with connz:
            for pg in pgs:
                is_blocked = any(b.issubset(pg['ws']) for b in blocklist)
                pred_label1=None
                pred_label2=None
                pred_label3=None
                pred_label=None
                pred_proba=None
                if len(pg['ws1'])>0:
                    vec1 = d2v_model.infer_vector(pg["ws1"], epochs=100, alpha=0.025, min_alpha=0.001).reshape(1, -1)
                    pred_label1 = classifier.predict(vec1)[0]
                    pred_proba1 = np.max(classifier.predict_proba(vec1)[0])
                if len(pg['ws2'])>0:
                    vec2 = d2v_model.infer_vector(pg["ws2"], epochs=100, alpha=0.025, min_alpha=0.001).reshape(1, -1)
                    pred_label2 = classifier.predict(vec2)[0]
                    pred_proba2 = np.max(classifier.predict_proba(vec2)[0])
                if len(pg['ws'])>0:
                    vec3 = d2v_model.infer_vector(pg["ws"], epochs=100, alpha=0.025, min_alpha=0.001).reshape(1, -1)
                    pred_label3 = classifier.predict(vec3)[0]
                    pred_proba3 = np.max(classifier.predict_proba(vec3)[0])

                if pred_label3 and pred_label3 == 'p':
                    pred_label = pred_label3
                    pred_proba = pred_proba3
                elif pred_label1 and pred_label1 == 'p':
                    pred_label = pred_label2
                    pred_proba = pred_proba2
                elif pred_label2 and pred_label2 == 'p':
                    pred_label = pred_label2
                    pred_proba = pred_proba2
                elif pred_label1 and pred_label2 and pred_label1 == pred_label2:
                    pred_label = pred_label1
                    pred_proba = max(pred_proba1, pred_proba2)
                elif pred_label1 and pred_label3 and pred_label1 == pred_label3:
                    pred_label = pred_label1
                    pred_proba = max(pred_proba1, pred_proba3)
                elif pred_label2 and pred_label3 and pred_label2 == pred_label3:
                    pred_label = pred_label2
                    pred_proba = max(pred_proba2, pred_proba3)
                elif pred_label3:
                    pred_label = pred_label3
                    pred_proba = pred_proba3
                elif pred_label1:
                    pred_label = pred_label1
                    pred_proba = pred_proba1
                elif pred_label2:
                    pred_label = pred_label2
                    pred_proba = pred_proba2
                if pred_label and pred_proba:
                    cursorz.execute('update tvml set pred_label=?, pred_proba=?, is_blocked=? where src=? and pgm_uid=?',[pred_label, pred_proba, is_blocked, pg['src'], pg['pgm_uid']])
                    if pg.get('src') is None:
                        pass
                    else:
                        if pg['src'] == 0 and (not is_blocked) and pred_label == 'p':
                            print(f'{pred_label}({pred_proba:.4f}) {pg["pg_title"]} {pg["pg_detail"]}')
    finally:
        connz.close()

if __name__ == "__main__":
    main()
