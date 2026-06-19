import sqlite3
import itertools
import json
import os
import yaml

import prepare1

db_path_intr = "./db/tvlike.db"#TODO コールドスタートだと存在しない→tvlikeプログラムがコールドスタートに対応してるのでは
db_path_pgm = "./db/tvguide.db"
db_path_ml = "./db/tvml.db"
db_path_ml0 = "./db/tvml0.db"

with open(db_path_ml0,'w') as f:
    # ファイルがあれば切り捨てる
    pass

conn = sqlite3.connect(':memory:')
conn.row_factory = sqlite3.Row  # カラム名でアクセス可能にする
cursor = conn.cursor()

cursor.execute(f"ATTACH DATABASE ? AS tvguide_db", [db_path_pgm])
cursor.execute(f"ATTACH DATABASE ? AS tvlike_db", [db_path_intr])
cursor.execute(f"ATTACH DATABASE ? AS tvml0_db", [db_path_ml0])
cursor.execute(f"ATTACH DATABASE ? AS tvml_db", [db_path_ml])


cursor.execute("""
CREATE TABLE main.stations (
  tuner TEXT,
  station_id TEXT,
  is_target INTEGER
)
""")

colnames=[
  'uniqk',
  'pgm_uid',
  'asof',
  'bsdate',
  'tuner',
  'station_id',
  'station_name',
  'pgm_station_name',
  'pid',
  'event_id',
  'pg_start',
  'pg_end',
  'pg_title',
  'pg_detail',
  'genre',
  'link',
  'words1',
  'words2',
  'interaction',
  'pred_label',
  'pred_proba',
  'is_target',
  'is_preinstalled',
]
create_tvml_sql = """
CREATE TABLE IF NOT EXISTS {{DB_NAME}}.tvml (
  uniqk INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
  pgm_uid TEXT,
  asof TEXT NOT NULL,
  bsdate TEXT NOT NULL,
  tuner TEXT NOT NULL,
  station_id TEXT NOT NULL,
  station_name TEXT,
  pgm_station_name TEXT,
  pid TEXT,
  event_id TEXT,
  pg_start TEXT NOT NULL,
  pg_end TEXT NOT NULL,
  pg_title TEXT,
  pg_detail TEXT,
  genre TEXT,
  link TEXT,
  words1 TEXT,
  words2 TEXT,
  interaction TEXT,
  pred_label TEXT,
  pred_proba REAL,
  is_target INTEGER NOT NULL,
  is_preinstalled INTEGER NOT NULL
)
"""
create_idx_tvml_pgm_sql="""
CREATE UNIQUE INDEX IF NOT EXISTS {{DB_NAME}}.idx_tvml_pgm ON tvml (
  bsdate, tuner, station_id, pg_start
)
"""
cursor.execute(create_tvml_sql.replace('{{DB_NAME}}','tvml_db'))
cursor.execute(create_tvml_sql.replace('{{DB_NAME}}','tvml0_db'))
cursor.execute(create_tvml_sql.replace('{{DB_NAME}}','main'))
cursor.execute(create_idx_tvml_pgm_sql.replace('{{DB_NAME}}','tvml_db'))
cursor.execute(create_idx_tvml_pgm_sql.replace('{{DB_NAME}}','tvml0_db'))


stations = {}
static_tokens = {}
if os.path.isfile("./static_tokens.yaml"):
    with open("./static_tokens.yaml", "r") as f:
        static_tokens_conf = yaml.safe_load(f)
    stations = static_tokens_conf.get('stations',{})
    static_tokens = static_tokens_conf.get('tokens',{})

with conn:
  for t in stations.keys():
    for s in stations[t].keys():
      cursor.execute("INSERT INTO stations VALUES(?,?,1)",[t,s])
  for intr in static_tokens.keys():
    for i, t in enumerate(static_tokens[intr]):
      cursor.execute("""
        INSERT INTO tvml0_db.tvml (
          asof, bsdate, tuner, station_id, pg_start, pg_end, pg_title, pg_detail, interaction, is_target, is_preinstalled
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
      """, ['000101010000', '00010101', f'__{intr}', f'{i:08}', '000101010000', '000101010001', t, '', intr, 0, 1])

insert_pgm_sql = (
"INSERT INTO tvml0_db.tvml ("
+ ",".join(c for c in colnames if c not in ['uniqk','words1','words2','pred_label','pred_proba'])
+ ") SELECT "
+ ",".join(c for c in colnames if c not in ['uniqk','words1','words2','pred_label','pred_proba'])
+ " FROM tvml_base AS t"
) 

default_with_sql="""
WITH
tvpgm_rank AS (
  SELECT
  p.*,
  COALESCE(s.is_target,0) as is_target,
  0 as is_preinstalled,
  DENSE_RANK() OVER (PARTITION BY bsdate ORDER BY asof DESC) AS asof_rk
  FROM tvguide_db.programs AS p
  LEFT OUTER JOIN stations AS s
  ON p.tuner = s.tuner
  AND p.station_id = s.station_id
), 
tvpgm_latest AS (
  SELECT
  *
  FROM tvpgm_rank
  WHERE asof_rk = 1
),
tvlike_rank AS (
  SELECT
  *,
  DENSE_RANK() OVER(PARTITION BY bsdate, tuner, station_id, pg_start, pg_end, pg_title ORDER BY asof DESC) AS pgm_rk
  FROM tvlike_db.interactions
),
tvlike_latest AS (
  SELECT
  *
  FROM tvlike_rank
  WHERE pgm_rk = 1
),
tvml_base AS (
  SELECT
  p.*,COALESCE(l.interaction,'_') AS interaction
  FROM tvpgm_latest AS p
  LEFT OUTER JOIN tvlike_latest AS l
  ON ( -- 変化なしとみなす条件
    p.bsdate = l.bsdate
    AND p.tuner = l.tuner
    AND p.station_id = l.station_id
    AND p.pg_start = l.pg_start
    AND p.pg_end = l.pg_end
    AND p.pg_title = l.pg_title
  )
)
"""

with conn:
  cursor.execute(f"{default_with_sql} {insert_pgm_sql}")

preparer = prepare1.Prepare1()


def fetch_tvml0():
  global conn
  cursor_sel = conn.cursor()
  try:
    cursor_sel.row_factory=sqlite3.Row
    cursor_sel.execute("SELECT * FROM tvml0_db.tvml")
    for row in cursor_sel:
      yield row
  finally:
    cursor_sel.close()

from tqdm import tqdm

with conn:
  for row in tqdm(fetch_tvml0()):
    cursor.execute(
      "select * from tvml_db.tvml where bsdate=? and tuner=? and station_id=? and pg_start=? and pg_title=? and pg_detail=? limit 1"
      ,[row['bsdate'],row['tuner'],row['station_id'],row['pg_start'],row['pg_title'],row['pg_detail'],]
    ) #TODO 複数ある場合の保険をかけるか？→いらんのでは. 同じなんだし。
    tgtrows=cursor.fetchall()
    print(f"{row['pg_title']} {row['pg_detail']}")
    if len(tgtrows)>0:
      # tgtrow = tgtrows.pop()
      w1 = tgtrows[0]['words1']
      w2 = tgtrows[0]['words2']
    else:
      w1 = json.dumps(preparer.proc_tokens(preparer.call_mecab_api(row['pg_title'])),ensure_ascii=False)
      w2 = json.dumps(preparer.proc_tokens(preparer.call_mecab_api(row['pg_detail'])),ensure_ascii=False)
        #API投げる
        #DB更新
    cursor.execute(
      "update tvml0_db.tvml set words1=?, words2=? where uniqk=?"
      , [w1, w2, row['uniqk']]
    )
  cursor.execute(
    "select interaction,count(*) as c from tvml0_db.tvml group by interaction"
  )
  for row in cursor.fetchall():
    print(f"{row['interaction']}: {row['c']}")
  

cursor.execute(f"DETACH DATABASE tvguide_db")
cursor.execute(f"DETACH DATABASE tvlike_db")
cursor.execute(f"DETACH DATABASE tvml0_db")
cursor.execute(f"DETACH DATABASE tvml_db")
conn.close()
