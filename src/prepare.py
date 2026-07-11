import sqlite3
import itertools
import json
import os
from tqdm import tqdm
import yaml

from common_genre import GenreUtil
from common_mecab import MecabUtil

import re
import unicodedata

def normalize_zen_han_text(text: str) -> str:
    """英数と基本的な記号をASCIIに、半角カナを全角に統一。"""
    #unicodeのnormarize (NFKC)は囲み文字を処理してしまうため、自前の実装。
    if not text:
        return None

    # \u3000 (全角SP)
    # \uFF01 〜 \uFF5D (全角英数・記号)→全角チルダ(5E)、二重角かっこ《》(5F,60)を除く。
    # \uFF61 〜 \uFF9F (半角カナ・半角句読点)
    # ※ ¥u301C 波ダッシュはここでは変換しない(基本的には来ないはず)
    target_block = re.compile(r'[\u3000\uFF01-\uFF5D\uFF61-\uFF9F]+')

    def _replace(match):
        return unicodedata.normalize('NFKC', match.group(0))
    text = target_block.sub(_replace, text)
    text = text.replace('\uFF5E', '\u301C') # 全角チルダを波ダッシュに寄せる
    text = re.sub(r'^\s+', '', text)
    text = re.sub(r'\s+$', '', text)
    if len(text)==0:
       text = None
    return text

def normalize_zen_han_json(jsontext: str) -> str:
    if not jsontext:
        return None
    _json = json.loads(jsontext)
    _json_norm = {normalize_zen_han_text(_k) or '':normalize_zen_han_text(_v) or '' for _k,_v in _json.items()}
    return json.dumps(_json_norm, ensure_ascii=False)

db_path_like = "./db/tvlike.db"
db_path_token = "./db/tvtoken.db"
db_path_epg = "./db/epg.db"
db_path_ml = "./db/tvml.db"
db_path_mlw = "./db/tvmlw.db"
db_path_adl = "./db/adl.db"

with open(db_path_mlw,'w') as f:
    # ファイルがあれば切り捨てる
    pass

conn = sqlite3.connect(':memory:')
conn.row_factory = sqlite3.Row  # カラム名でアクセス可能にする
cursor = conn.cursor()

cursor.execute(f"ATTACH DATABASE ? AS epgdb", [db_path_epg])
cursor.execute(f"ATTACH DATABASE ? AS tvtokendb", [db_path_token])
cursor.execute(f"ATTACH DATABASE ? AS tvlikedb", [db_path_like])
cursor.execute(f"ATTACH DATABASE ? AS tvmldb", [db_path_mlw])
cursor.execute(f"ATTACH DATABASE ? AS adldb", [db_path_adl])

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
  service_name_norm TEXT NOT NULL,
  remote_control_key_id INTEGER,
  channel TEXT NOT NULL,
  channel_type TEXT NOT NULL,
  norm_title TEXT,
  norm_description TEXT,
  norm_extended TEXT,
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
  norm_title TEXT,
  norm_description TEXT,
  norm_extended TEXT,
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
conn.execute("""
  CREATE TABLE IF NOT EXISTS adldb.adl (
    adl_id INTEGER NOT NULL,
    adl_yaml TEXT,
    PRIMARY KEY (adl_id)
  )
""")
cursor.execute("SELECT adl_yaml FROM adldb.adl WHERE adl_id = 1")
adl_row = cursor.fetchone()
if adl_row:
  adl_def = yaml.safe_load(adl_row['adl_yaml'])
else:
  adl_def = {'features': {}}
del adl_row

genre_util = GenreUtil()

conn.create_function("MOD_GENRE", 1, genre_util.mod_genre)
conn.create_function("NORM_TEXT", 1, normalize_zen_han_text)
conn.create_function("NORM_JSON", 1, normalize_zen_han_json)

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
        if pg['norm_title'] and _w in pg['norm_title']:
            return True
        if pg['norm_description'] and _w in pg['norm_description']:
            return True
        if pg['norm_extended'] and _w in pg['norm_extended']:#TODO JSON 展開する
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
    SELECT *,
    NORM_TEXT(epg.pgm_title) AS norm_title,
    NORM_TEXT(epg.pgm_description) AS norm_description,
    NORM_JSON(epg.extended) AS norm_extended
    FROM epgdb.epg
    WHERE (norm_title IS NOT NULL AND norm_title != '')
    OR (norm_description IS NOT NULL AND norm_description != '')
    OR (norm_extended IS NOT NULL AND norm_extended != '')
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
      NORM_TEXT(epg.pgm_title) AS norm_title,
      NORM_TEXT(epg.pgm_description) AS norm_description,
      NORM_JSON(epg.extended) AS norm_extended,
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

  for batch in itertools.batched(tqdm(cursor), 256):
    flags = [{'title':-1,'description':-1,'extended':-1} for _ in range(len(batch))] # * N だと同じ参照になるのでrangeで回す
    texts = list()
    j = 0
    for _f, row in zip(flags, batch):
      if row['pgm_title'] != row['token_title'] and row['norm_title'] is not None and len(row['norm_title'])>0:
        texts.append(row['norm_title'].upper())
        _f['title'] = j
        j+=1
      if row['pgm_description'] != row['token_description'] and row['norm_description'] is not None and len(row['norm_description'])>0:
        texts.append(row['norm_description'].upper())
        _f['description'] = j
        j+=1
      if row['extended'] != row['token_extended'] and row['norm_extended'] is not None and len(row['norm_extended'])>0:
        extended_all = " ".join(f"{k} {v}" for k, v in json.loads(row['norm_extended']).items())
        texts.append(extended_all.upper())
        _f['extended'] = j
        j+=1
    tokenizeds_ipadic = mecab_util.call_mecab_api_batch(texts, dic='IPADic')
    tokenizeds_neologd = mecab_util.call_mecab_api_batch(texts, dic='NEOlogd')

    for _f, row in zip(flags, batch):
      if _f['title']>=0:
        w1a = json.dumps(mecab_util.proc_tokens(tokenizeds_ipadic[_f['title']]),ensure_ascii=False)
        w1b = json.dumps(mecab_util.proc_tokens(tokenizeds_neologd[_f['title']]),ensure_ascii=False)
      elif row['norm_title'] is not None and len(row['norm_title'])>0:
        w1a = row['token_title_ipa']
        w1b = row['token_title_neologd']
      else:
        w1a = None
        w1b = None
      if _f['description']>=0:
        w2a = json.dumps(mecab_util.proc_tokens(tokenizeds_ipadic[_f['description']]),ensure_ascii=False)
        w2b = json.dumps(mecab_util.proc_tokens(tokenizeds_neologd[_f['description']]),ensure_ascii=False)
      elif row['norm_description'] is not None and len(row['norm_description'])>0:
        w2a = row['token_description_ipa']
        w2b = row['token_description_neologd']
      else:
        w2a = None
        w2b = None
      if _f['extended']>=0:
        w3a = json.dumps(mecab_util.proc_tokens(tokenizeds_ipadic[_f['extended']]),ensure_ascii=False)
        w3b = json.dumps(mecab_util.proc_tokens(tokenizeds_neologd[_f['extended']]),ensure_ascii=False)
      elif row['norm_extended'] is not None and len(row['norm_extended'])>0:
        w3a = row['token_extended_ipa']
        w3b = row['token_extended_neologd']
      else:
        w3a = None
        w3b = None
      if (_f['title']>=0 or _f['description']>=0 or _f['extended']>=0):
        conn.execute("""
          INSERT INTO tvtokendb.tvtoken (
            asof,
            pgm_uid,
            start_at,
            pgm_title,
            pgm_description,
            extended,
            norm_title,
            norm_description,
            norm_extended,
            token_title_ipa,
            token_title_neologd,
            token_description_ipa,
            token_description_neologd,
            token_extended_ipa,
            token_extended_neologd
          ) VALUES (
            ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
          )
          ON CONFLICT(pgm_uid, start_at)
          DO UPDATE SET
            asof=EXCLUDED.asof,
            pgm_title=EXCLUDED.pgm_title,
            pgm_description=EXCLUDED.pgm_description,
            extended=EXCLUDED.extended,
            norm_title=EXCLUDED.norm_title,
            norm_description=EXCLUDED.norm_description,
            norm_extended=EXCLUDED.norm_extended,
            token_title_ipa=EXCLUDED.token_title_ipa,
            token_title_neologd=EXCLUDED.token_title_neologd,
            token_description_ipa=EXCLUDED.token_description_ipa,
            token_description_neologd=EXCLUDED.token_description_neologd,
            token_extended_ipa=EXCLUDED.token_extended_ipa,
            token_extended_neologd=EXCLUDED.token_extended_neologd
          """
          , [
            row['asof'], row['pgm_uid'], row['start_at'],
            row['pgm_title'], row['pgm_description'], row['extended'],
            row['norm_title'], row['norm_description'], row['norm_extended'],
            w1a, w1b, w2a, w2b, w3a, w3b
          ]
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
  service_name_norm,
  remote_control_key_id,
  channel,
  channel_type,
  norm_title,
  norm_description,
  norm_extended,
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
  epg.start_at-epg.duration AS end_at ,
  epg.duration,
  epg.pgm_title,
  epg.pgm_description,
  MOD_GENRE(epg.genres) AS genres,
  epg.extended,
  epg.service_type,
  epg.service_name,
  NORM_TEXT(epg.service_name) AS service_name_norm,
  epg.remote_control_key_id,
  epg.channel,
  epg.channel_type,
  tvtoken.norm_title,
  tvtoken.norm_description,
  tvtoken.norm_extended,
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
FROM epgdb.epg AS epg
LEFT OUTER JOIN tvlikedb.tvlike AS tvlike
ON epg.pgm_uid = tvlike.pgm_uid
AND epg.start_at > tvlike.start_at - 8*24*60*60*1000  -- TODO 番組がずれたけどlikeしなおしてない場合の救済が必要。単純に前後８日で結合すれば良いのでは
AND epg.start_at < tvlike.start_at + 8*24*60*60*1000  -- TODO 番組がずれたけどlikeしなおしてない場合の救済が必要。単純に前後８日で結合すれば良いのでは
AND epg.pgm_title = tvlike.pgm_title
LEFT OUTER JOIN tvtokendb.tvtoken AS tvtoken
ON epg.pgm_uid = tvtoken.pgm_uid
AND epg.start_at > tvtoken.start_at - 8*24*60*60*1000
AND epg.start_at < tvtoken.start_at + 8*24*60*60*1000
AND epg.pgm_title = tvtoken.pgm_title
LEFT OUTER JOIN absolute_defence_line AS adl
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
cursor.execute(f"DETACH DATABASE adldb")
conn.close()
