import datetime
import sqlite3
from typing import Iterator, Dict

db_path = "./db/tvml.db"

def stream_recommend_data(today:str = None) -> Iterator[Dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # カラム名でアクセス可能にする
    cursor = conn.cursor()

    if today:
        bind_sql = 'AND bsdate >= ?'
        bind_params = [today]
    else:
        bind_sql = ''
        bind_params = []

    try:
        cursor.execute(f"""
SELECT * FROM tvml
WHERE
src = 0
AND
pred_label = 'p'
{bind_sql}
ORDER BY bsdate, pg_start, pg_end
        """, bind_params)
        for row in cursor:
            yield dict(row)
    finally:
        conn.close()

def main():
    today = datetime.datetime.now().strftime("%Y%m%d%H%M")
    for pg in stream_recommend_data(today):
        print(f'({pg["pred_proba"]:.4f}) {pg["pg_start"][0:4]}-{pg["pg_start"][4:6]}-{pg["pg_start"][6:8]} {pg["pg_start"][8:10]}:{pg["pg_start"][10:12]} {pg["pg_title"]} {pg["pg_detail"]}')
        

if __name__ == "__main__":
    main()
