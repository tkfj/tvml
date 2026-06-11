import sqlite3
import json

from prepare_core import PrepareCore

class Prepare2(PrepareCore):

    def main(self):
        # self.init_out_table()
        conn=sqlite3.connect(self.db_path_ml)
        conn.row_factory = sqlite3.Row

        try:
            with conn:
                for pgm in self.stream_interactions():
                    print(pgm['pg_title'])
                    pgm['words1'] = json.dumps(self.proc_one(self.call_mecab_api(pgm['pg_title'])),ensure_ascii=False)
                    print(pgm['pg_detail'])
                    pgm['words2'] = json.dumps(self.proc_one(self.call_mecab_api(pgm['pg_detail'])),ensure_ascii=False)
                    pgm['src']=1
                    inpgm={ f"{n}":pgm.get(n) for n in self.inskeys }
                    conn.execute(self.inssql, inpgm)
        finally:
            conn.close()

if __name__ == "__main__":
    prepare2 = Prepare2()
    prepare2.main()
