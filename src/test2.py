import sqlite3
import itertools
import json
import os
from tqdm import tqdm
import yaml

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
  absolute_defence_line TEXT,
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

with conn:
  for t in channels.keys():
    for s in channels[t]:
      cursor.execute("INSERT INTO channels VALUES(?,?,1)",[t,s])

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
    _scores = [(_fsk, _ws['score'] if _extract(_ws['word']) else 0, ) for _fsk, _fsv in adl_def['features'].items() for _ws in _fsv['words']]
    _scdic = dict()
    for _fea, _sc in _scores:
        _scdic[_fea] = _scdic.get(_fea, 0.0) + _sc
    _retdic = dict()
    for _fea, _sc in _scdic.items():
        if _sc == 0.0: continue
        if adl_def['features'][_fea].get('name') is None: continue
        _retdic[_fea] = {
          'name': adl_def['features'][_fea]['name'],
          'score': _sc,
        }
    return _retdic if len(_retdic) > 0 else None

cursor.execute("""
  CREATE TABLE IF NOT EXISTS absolute_defence_line (
    pgm_uid INTEGER NOT NULL,
    start_at INTEGER NOT NULL,
    absolute_defence_line TEXT NOT NULL,
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
    _adl = make_absolute_defence_line(_row)
    if _adl:
      cursor_w.execute("""
        INSERT INTO absolute_defence_line
        VALUES (?,?,?)
      """, [_row['pgm_uid'], _row['start_at'], json.dumps(_adl,ensure_ascii=False)])
  cursor_w.close()

from prepare_mecab import PrepareMecab
preparer = PrepareMecab()
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
      w1 = json.dumps(preparer.proc_tokens(preparer.call_mecab_api(row['pgm_title'])),ensure_ascii=False)
    elif row['pgm_title'] is not None and len(row['pgm_title'])>0:
      w1 = row['token_title_ipa']
    else:
      w1 = None
    if row['pgm_description'] != row['token_description'] and row['pgm_description'] is not None and len(row['pgm_description'])>0:
      w2 = json.dumps(preparer.proc_tokens(preparer.call_mecab_api(row['pgm_description'])),ensure_ascii=False)
    elif row['pgm_description'] is not None and len(row['pgm_description'])>0:
      w2 = row['token_description_ipa']
    else:
      w2 = None
    if row['extended'] != row['token_extended'] and row['extended'] is not None and len(row['extended'])>0:
      extended_all = " ".join(f"{k} {v}" for k, v in json.loads(row['extended']).items())
      w3 = json.dumps(preparer.proc_tokens(preparer.call_mecab_api(extended_all)),ensure_ascii=False)
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


#TODO イベントIDが一周回ったときの対処は、たぶん、start_at(またはbsdate)が８日以上差があるかどうか。
#なぜなら、EPG配信期間が８日間だから。
#レアケースなので、bsdateが違ったらもう別物とみなす。

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
  absolute_defence_line,
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
  epg.genres,
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
  adl.absolute_defence_line,
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
