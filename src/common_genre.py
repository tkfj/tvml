import itertools
import json
import yaml

def _init_genres():
    with open("conf/genres.yaml", "r", encoding="utf-8") as f:
      genres_conf = yaml.safe_load(f)
    return (
      { _gi: _gn for _gi, _gn in genres_conf.get('lv1').items() },
      { _gi: _gn for _gi, _gn in genres_conf.get('lv2').items() },
      list(itertools.chain(
        [ f"genre1_{_gi}" for _gi in genres_conf.get('lv1').keys() ],
        [ f"genre2_{_gi}" for _gi in genres_conf.get('lv2').keys() ],
      )),
    )

class GenreUtil:
  def __init__(self):
      (
        self.genres1,
        self.genres2,
        self.featurenames,
      ) = _init_genres()

  def get_genre_name(self, lv1:int, lv2:int = None):
      l1s = f"{lv1:02d}"
      name1 = self.genres1.get(l1s, "??")
      if lv2 is not None:
          l2s = f"{lv1:02d}{lv2:02d}"
          name2 = self.genres2.get(l2s, "???")
          return name1, name2
      else:
          return name1

  def mod_genre(self, jsonstr:str) -> str:
      """sqlite3関数ジャンルコードにテキストラベルを付与"""
      if jsonstr is None:
          return None
      _json = json.loads(jsonstr)
      for g in _json:
          gn1, gn2 = self.get_genre_name(g['lv1'], g['lv2'])
          g['lv1_label'] = gn1
          g['lv2_label'] = gn2
      return json.dumps(_json, ensure_ascii=False)

  def generate_features(self, jsonstr:str):
      _json = json.loads(jsonstr or '[]')
      g1dic = dict.fromkeys([f"{g['lv1']:02d}" for g in _json], 1)
      g2dic = dict.fromkeys([f"{g['lv1']:02d}{g['lv2']:02d}" for g in _json], 1)
      return list(itertools.chain(
        [g1dic.get(_k,0) for _k in self.genres1.keys()],
        [g2dic.get(_k,0) for _k in self.genres2.keys()],
      ))
