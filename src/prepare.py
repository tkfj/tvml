import sqlite3
import itertools
import json
import os
from tqdm import tqdm
import yaml

from common_genre import GenreUtil
from common_mecab import MecabUtil

db_path_like = "./db/tvlike.db"
db_path_token = "./db/tvtoken.db"
db_path_epg = "./db/epg.db"
db_path_ml = "./db/tvml.db"
db_path_mlw = "./db/tvmlw.db"

with open(db_path_mlw,'w') as f:
    # ファイルがあれば切り捨てる
    pass

with open("./conf/absolute_defence_line.yaml") as f:
    adl_def = yaml.safe_load(f)

conn = sqlite3.connect(':memory:')
conn.row_factory = sqlite3.Row  # カラム名でアクセス可能にする
cursor = conn.cursor()

cursor.execute(f"ATTACH DATABASE ? AS epgdb", [db_path_epg])
cursor.execute(f"ATTACH DATABASE ? AS tvtokendb", [db_path_token])
cursor.execute(f"ATTACH DATABASE ? AS tvlikedb", [db_path_like])
cursor.execute(f"ATTACH DATABASE ? AS tvmldb", [db_path_mlw])

create_tvml_sql = """
CREATE TABLE IF NOT EXISTS {{DB_NAME}}.tvml (
  tvml_id INTEGER NOT NULL PRIMARY KEY, --物理的ユニーク以上の意味はない
  asof INTEGER NOT NULL,
  pgm_uid INTEGER NOT NULL,
  network_id INTEGER NOT NULL,
  service_id INTEGER NOT NULL,
  event_id INTEGER NOT NULL,
  is_free INTEGER NOT NULL,
  start_at INTEGER NOT NULL,
  end_at INTEGER NOT NULL,
  duration INTEGER NOT NULL,
  pgm_title TEXT,
  pgm_description TEXT,
  genres TEXT,
  extended TEXT,
  service_type INTEGER NOT NULL,
  service_name TEXT NOT NULL,
  remote_control_key_id INTEGER,
  channel TEXT NOT NULL,
  channel_type TEXT NOT NULL,
  token_title_ipa TEXT,
  token_title_neologd TEXT,
  token_description_ipa TEXT,
  token_description_neologd TEXT,
  token_extended_ipa TEXT,
  token_extended_neologd TEXT,
  defence_features TEXT,
  defence_labels TEXT,
  interaction TEXT,
  pred_label TEXT,
  pred_proba REAL,
  is_target_channel INTEGER NOT NULL,
  UNIQUE (pgm_uid, start_at)
)
"""
create_tvtoken_sql = """
CREATE TABLE IF NOT EXISTS {{DB_NAME}}.tvtoken (
  tvtoken_id INTEGER NOT NULL PRIMARY KEY, --物理的ユニーク以上の意味はない
  asof INTEGER NOT NULL,
  pgm_uid INTEGER NOT NULL,
  start_at INTEGER NOT NULL,
  pgm_title TEXT,
  pgm_description TEXT,
  extended TEXT,
  token_title_ipa TEXT,
  token_title_neologd TEXT,
  token_description_ipa TEXT,
  token_description_neologd TEXT,
  token_extended_ipa TEXT,
  token_extended_neologd TEXT,
  UNIQUE (pgm_uid, start_at)
)
"""
create_trg_token_ins_sql = """
CREATE TRIGGER IF NOT EXISTS {{DB_NAME}}.trg_token_ins
BEFORE INSERT
ON tvtoken
BEGIN
  DELETE FROM tvtoken
  WHERE pgm_uid = NEW.pgm_uid
  AND start_at >= NEW.start_at - 8*24*60*60*1000
  AND start_at <= NEW.start_at + 8*24*60*60*1000
  AND start_at <> NEW.start_at
  ;
END
"""
create_tvlike_sql = """
CREATE TABLE IF NOT EXISTS {{DB_NAME}}.tvlike (
  tvlike_id INTEGER NOT NULL PRIMARY KEY, --物理ユニーク以上の意味はない
  asof INTEGER NOT NULL,
  pgm_uid INTEGER NOT NULL,
  start_at INTEGER NOT NULL,
  pgm_title TEXT,
  interaction TEXT,
  UNIQUE (pgm_uid, start_at)
)
"""
create_trg_like_ins_sql = """
CREATE TRIGGER IF NOT EXISTS {{DB_NAME}}.trg_like_ins
BEFORE INSERT
ON tvlike
BEGIN
  DELETE FROM tvlike
  WHERE pgm_uid = NEW.pgm_uid
  AND start_at >= NEW.start_at - 8*24*60*60*1000
  AND start_at <= NEW.start_at + 8*24*60*60*1000
  AND start_at <> NEW.start_at
  ;
END
"""
cursor.execute(create_tvml_sql.replace('{{DB_NAME}}','tvmldb'))
cursor.execute(create_tvml_sql.replace('{{DB_NAME}}','main'))
cursor.execute(create_tvlike_sql.replace('{{DB_NAME}}','tvlikedb'))
cursor.execute(create_trg_like_ins_sql.replace('{{DB_NAME}}','tvlikedb'))
cursor.execute(create_tvtoken_sql.replace('{{DB_NAME}}','tvtokendb'))
cursor.execute(create_trg_token_ins_sql.replace('{{DB_NAME}}','tvtokendb'))

with open("./conf/channels.yaml", "r") as f:
  channels_conf = yaml.safe_load(f)
channels = channels_conf.get('channels',{})

conn.execute("""
  CREATE TABLE IF NOT EXISTS channels (
    channel_type TEXT NOT NULL,
    service_id INTEGER NOT NULL,
    is_target_channel INTEGER NOT NULL,
    PRIMARY KEY (channel_type, service_id)
  )
""")

genre_util = GenreUtil()

conn.create_function("MOD_GENRE", 1, genre_util.mod_genre)

cur1 = conn.cursor()
with conn:
  try:
    for t in channels.keys():
      for s in channels[t]:
        cur1.execute("INSERT INTO channels VALUES(?,?,1)",[t,s])
  finally:
      cur1.close()
  del cur1

def make_absolute_defence_line(pg):
    def _extract(_w):
        if _w is None or len(_w)==0:
            return False
        if pg['pgm_title'] and _w in pg['pgm_title']:
            return True
        if pg['pgm_description'] and _w in pg['pgm_description']:
            return True
        if pg['extended'] and _w in pg['extended']:#TODO JSON 展開する
            return True
        return False
    _adl_features = {}
    _adl_labels = []
    for _fea, _lbls in adl_def['features'].items():
      _score = 0.0
      for _lbl in _lbls.get("labels",[]):
        _lbln = _lbl.get('name')
        _found = False
        for _ws in _lbl['words']:
          _w = _ws['word']
          _s = _ws['score']
          if _extract(_w):
             _score += _s
             _found = True
        if _found and _lbln:
           _adl_labels.append(_lbln)
      if _score != 0.0:
        _adl_features[_fea] = max(0.0, min(1.0, _score))
    return (
       _adl_features if len(_adl_features)>0 else None,
       _adl_labels if len(_adl_labels)>0 else None,
    )

cursor.execute("""
  CREATE TABLE IF NOT EXISTS absolute_defence_line (
    pgm_uid INTEGER NOT NULL,
    start_at INTEGER NOT NULL,
    defence_features TEXT NOT NULL,
    defence_labels TEXT,
    PRIMARY KEY (pgm_uid, start_at)
  )
""")
with conn:
  cursor.execute("""
    SELECT *
    FROM epgdb.epg
    WHERE (pgm_title IS NOT NULL AND pgm_title != '')
    OR (pgm_description IS NOT NULL AND pgm_description != '')
    OR (extended IS NOT NULL AND extended != '')
  """)
  cursor_w = conn.cursor()
  cursor_w.row_factory = sqlite3.Row
  for _row in tqdm(cursor):
    _adl_features, _adl_labels = make_absolute_defence_line(_row)
    if _adl_features or _adl_labels:
      cursor_w.execute("""
        INSERT INTO absolute_defence_line
        VALUES (?,?,?,?)
      """, [
        _row['pgm_uid'],
        _row['start_at'],
        json.dumps(_adl_features, ensure_ascii=False) if _adl_features else None,
        json.dumps(_adl_labels,ensure_ascii=False) if _adl_labels else None,
      ])
  cursor_w.close()

mecab_util = MecabUtil()
with conn:
  cursor.execute(f"""
    SELECT
      epg.*,
      token.pgm_title AS token_title,
      token.pgm_description AS token_description,
      token.extended AS token_extended,
      token.token_title_ipa,
      token.token_title_neologd,
      token.token_description_ipa,
      token.token_description_neologd,
      token.token_extended_ipa,
      token.token_extended_neologd
    FROM epgdb.epg as epg
    LEFT OUTER JOIN tvtokendb.tvtoken as token
    ON epg.pgm_uid = token.pgm_uid
    AND epg.start_at = token.start_at
    WHERE epg.pgm_title IS DISTINCT FROM token.pgm_title
    OR epg.pgm_description IS DISTINCT FROM token.pgm_description
    OR epg.extended IS DISTINCT FROM token.extended
  """)

  for row in tqdm(cursor):
    if row['pgm_title'] != row['token_title'] and row['pgm_title'] is not None and len(row['pgm_title'])>0:
      w1 = json.dumps(mecab_util.proc_tokens(mecab_util.call_mecab_api(row['pgm_title'])),ensure_ascii=False)
    elif row['pgm_title'] is not None and len(row['pgm_title'])>0:
      w1 = row['token_title_ipa']
    else:
      w1 = None
    if row['pgm_description'] != row['token_description'] and row['pgm_description'] is not None and len(row['pgm_description'])>0:
      w2 = json.dumps(mecab_util.proc_tokens(mecab_util.call_mecab_api(row['pgm_description'])),ensure_ascii=False)
    elif row['pgm_description'] is not None and len(row['pgm_description'])>0:
      w2 = row['token_description_ipa']
    else:
      w2 = None
    if row['extended'] != row['token_extended'] and row['extended'] is not None and len(row['extended'])>0:
      extended_all = " ".join(f"{k} {v}" for k, v in json.loads(row['extended']).items())
      w3 = json.dumps(mecab_util.proc_tokens(mecab_util.call_mecab_api(extended_all)),ensure_ascii=False)
    elif row['extended'] is not None and len(row['extended'])>0:
      w3 = row['token_extended_ipa']
    else:
      w3 = None
    if (row['pgm_title'] != row['token_title']) or (row['pgm_description'] != row['token_description']) or (row['extended'] != row['token_extended']):
      conn.execute("""
        INSERT INTO tvtokendb.tvtoken (
          asof,
          pgm_uid,
          start_at,
          pgm_title,
          pgm_description,
          extended,
          token_title_ipa,
          token_description_ipa,
          token_extended_ipa
        ) VALUES (
          ?,?,?,?,?,?,?,?,?
        )
        ON CONFLICT(pgm_uid, start_at)
        DO UPDATE SET
          asof=EXCLUDED.asof,
          pgm_title=EXCLUDED.pgm_title,
          pgm_description=EXCLUDED.pgm_description,
          extended=EXCLUDED.extended,
          token_title_ipa=EXCLUDED.token_title_ipa,
          token_description_ipa=EXCLUDED.token_description_ipa,
          token_extended_ipa=EXCLUDED.token_extended_ipa
        """
        , [row['asof'], row['pgm_uid'], row['start_at'], row['pgm_title'], row['pgm_description'], row['extended'], w1, w2, w3]
      )

insert_pgm_sql = f"""
INSERT INTO tvmldb.tvml (
  asof,
  pgm_uid,
  network_id,
  service_id,
  event_id,
  is_free,
  start_at,
  end_at,
  duration,
  pgm_title,
  pgm_description,
  genres,
  extended,
  service_type,
  service_name,
  remote_control_key_id,
  channel,
  channel_type,
  token_title_ipa,
  token_title_neologd,
  token_description_ipa,
  token_description_neologd,
  token_extended_ipa,
  token_extended_neologd,
  defence_features,
  defence_labels,
  interaction,
  is_target_channel
) SELECT
  epg.asof,
  epg.pgm_uid,
  epg.network_id,
  epg.service_id,
  epg.event_id,
  epg.is_free,
  epg.start_at,
  epg.start_at-epg.duration as end_at ,
  epg.duration,
  epg.pgm_title,
  epg.pgm_description,
  MOD_GENRE(epg.genres) as genres,
  epg.extended,
  epg.service_type,
  epg.service_name,
  epg.remote_control_key_id,
  epg.channel,
  epg.channel_type,
  tvtoken.token_title_ipa,
  tvtoken.token_title_neologd,
  tvtoken.token_description_ipa,
  tvtoken.token_description_neologd,
  tvtoken.token_extended_ipa,
  tvtoken.token_extended_neologd,
  adl.defence_features,
  adl.defence_labels,
  COALESCE(tvlike.interaction, '-'),
  COALESCE(channels.is_target_channel, 0)
FROM epgdb.epg as epg
LEFT OUTER JOIN tvlikedb.tvlike as tvlike
ON epg.pgm_uid = tvlike.pgm_uid
AND epg.start_at > tvlike.start_at - 8*24*60*60*1000  -- TODO 番組がずれたけどlikeしなおしてない場合の救済が必要。単純に前後８日で結合すれば良いのでは
AND epg.start_at < tvlike.start_at + 8*24*60*60*1000  -- TODO 番組がずれたけどlikeしなおしてない場合の救済が必要。単純に前後８日で結合すれば良いのでは
AND epg.pgm_title = tvlike.pgm_title
LEFT OUTER JOIN tvtokendb.tvtoken as tvtoken
ON epg.pgm_uid = tvtoken.pgm_uid
AND epg.start_at > tvtoken.start_at - 8*24*60*60*1000
AND epg.start_at < tvtoken.start_at + 8*24*60*60*1000
AND epg.pgm_title = tvtoken.pgm_title
LEFT OUTER JOIN absolute_defence_line as adl
ON epg.pgm_uid = adl.pgm_uid
AND epg.start_at = tvtoken.start_at
LEFT OUTER JOIN channels
ON epg.channel_type = channels.channel_type
AND epg.service_id = channels.service_id
"""

with conn:
  cursor.execute(insert_pgm_sql)

cursor.execute(f"DETACH DATABASE epgdb")
cursor.execute(f"DETACH DATABASE tvtokendb")
cursor.execute(f"DETACH DATABASE tvlikedb")
cursor.execute(f"DETACH DATABASE tvmldb")
conn.close()
