import sqlite3
import json
import os
import yaml

from prepare_core import PrepareCore

class Prepare2(PrepareCore):

    def stream_static_data(self):
        """
        固定情報を1件ずつ返すジェネレータ
        """
        i = 0
        if os.path.isfile("./static_tokens.yaml"):
            with open("./static_tokens.yaml", "r") as f:
                static_tokens_conf = yaml.safe_load(f)
            multiple = static_tokens_conf.get('multiple',1)
            for k in static_tokens_conf.get('tokens',{}).keys():
                for ts in static_tokens_conf['tokens'][k]:
                    for j in range(multiple):
                        i+=1
                        yield i, ts, k

    def main(self):
        # self.init_out_table()
        conn=sqlite3.connect(self.db_path_ml)
        conn.row_factory = sqlite3.Row

        try:
            with conn:
                conn.execute("delete from tvml where src=9")
                # conn.execute("delete from tvml where src=1")
                for _id, _tokens, _interaction in self.stream_static_data():
                    print(f"{_tokens}")
                    pgm = dict()
                    pgm['words1'] = json.dumps(self.proc_tokens(self.call_mecab_api(_tokens)),ensure_ascii=False)
                    pgm['words2'] = "[]"
                    pgm['is_blocked'] = 0
                    pgm['src']=9
                    pgm['pgm_uid']=_id
                    pgm['asof']='000000000000'
                    pgm['tuner']='x'
                    pgm['bsdate']='00000000'
                    pgm['station_id']='x'
                    pgm['station_name']='x'
                    pgm['pgm_station_name']='x'
                    pgm['pid']=None
                    pgm['event_id']=None
                    pgm['pg_start']='000000000000'
                    pgm['pg_end']='000000000000'
                    pgm['pg_title']=_tokens
                    pgm['pg_detail']=''
                    pgm['genre']=''
                    pgm['link']=None
                    pgm['interaction']=_interaction
                    # print(pgm)
                    inpgm={ f"{n}":pgm.get(n) for n in self.inskeys }
                    conn.execute(self.inssql, inpgm)
                for pgm in self.stream_interactions():
                    print(f"{pgm['pg_title']} {pgm['pg_detail']}")
                    pgm['words1'] = json.dumps(self.proc_tokens(self.call_mecab_api(pgm['pg_title'])),ensure_ascii=False)
                    pgm['words2'] = json.dumps(self.proc_tokens(self.call_mecab_api(pgm['pg_detail'])),ensure_ascii=False)
                    pgm['is_blocked'] = 0
                    pgm['src']=1
                    inpgm={ f"{n}":pgm.get(n) for n in self.inskeys }
                    conn.execute(self.inssql, inpgm)
        finally:
            conn.close()

if __name__ == "__main__":
    prepare2 = Prepare2()
    prepare2.main()
