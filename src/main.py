import json
import sqlite3
import itertools
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
        pg['ws']=list(itertools.chain(json.loads(pg["words1"]),json.loads(pg["words2"])))
        pgs.append(pg)
        # print(pg)

    tagged_data = [
        TaggedDocument(
            words=pg["ws"],
            tags=[pg["id"]]
        )
        for pg in pgs
    ]

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
            vec = d2v_model.dv[pg["id"]]
            X_train.append(vec)
            y_train.append(pg['interaction'])
    
    base_svc = SVC(kernel='rbf', C=0.3, gamma=0.02, class_weight='balanced', random_state=43)
    classifier = CalibratedClassifierCV(estimator=base_svc, ensemble=False)
    classifier.fit(X_train, y_train)

    connz = sqlite3.connect(db_path)
    connz.row_factory = sqlite3.Row
    cursorz = connz.cursor()
    try:
        with connz:
            for pg in pgs:
                vec = d2v_model.infer_vector(pg["ws"], epochs=100, alpha=0.025, min_alpha=0.001).reshape(1, -1)
                pred_label = classifier.predict(vec)[0]
                pred_proba = np.max(classifier.predict_proba(vec)[0])
                cursorz.execute('update tvml set pred_label=?, pred_proba=? where src=? and pgm_uid=?',[pred_label, pred_proba,pg['src'],pg['pgm_uid']])
                if pg.get('src') is None:
                    pass
                else:
                    if pg['src'] == 0 and pred_label == 'p':
                        print(f'{pred_label}({pred_proba:.4f}) {pg["pg_title"]} {pg["pg_detail"]}')
    finally:
        connz.close()

if __name__ == "__main__":
    main()
