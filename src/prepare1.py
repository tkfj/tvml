import sqlite3
import json

from prepare_core import PrepareCore

class Prepare1(PrepareCore):

    def main(self):
        self.init_out_table()
        conn=sqlite3.connect(self.db_path_ml)
        conn.row_factory = sqlite3.Row

        try:
            with conn:
                for pgm in self.stream_programs():
                    print(pgm['pg_title'])
                    pgm['words1'] = json.dumps(self.proc_tokens(self.call_mecab_api(pgm['pg_title'])),ensure_ascii=False)
                    print(pgm['pg_detail'])
                    pgm['words2'] = json.dumps(self.proc_tokens(self.call_mecab_api(pgm['pg_detail'])),ensure_ascii=False)
                    pgm['src']=0
                    inpgm={ f"{n}":pgm.get(n) for n in self.inskeys }
                    conn.execute(self.inssql, inpgm)
        finally:
            conn.close()

if __name__ == "__main__":
    prepare1 = Prepare1()
    prepare1.main()
