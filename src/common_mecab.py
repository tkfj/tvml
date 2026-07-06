import os
import requests

class MecabUtil:
    def __init__(self):
        self.MECAB_API_URL = os.getenv("MECAB_API_URL")
        self.session = requests.Session()

    def call_mecab_api(self,text):
        text = text.upper()
        text = text.replace("(","（")
        text = text.replace(")","）")
        text = text.replace("[","［")
        text = text.replace("]","］")
        response = self.session.post(self.MECAB_API_URL, json={"text": text})
        tokens = response.json().get("analysis")
        # # 無視された空白を補完するための処理
        # # 連続する名詞を複合名詞として結合する処理で、過剰に結合させないため
        # if tokens:
        #     p = 0
        #     tokens2 = []
        #     for token in tokens:
        #         w = token['surface']
        #         l = len(w)
        #         p1 = text.find(w, p)
        #         if p1 < 0:
        #             print(f"Error: token '{w}' not found in text starting from position {p}", file=sys.stderr)
        #         elif p1 > p:
        #             tokens2.append({
        #                 'surface': text[p:p1],
        #                 'pos': '空白記号',
        #                 'pos_detail1': '*',
        #                 'pos_detail2': '*',
        #                 'pos_detail3': '*',
        #                 'conjugated_type': '*',
        #                 'conjugated_form': '*',
        #                 'base_form': text[p:p1],
        #                 'reading': text[p:p1],
        #                 'pronunciation': text[p:p1],
        #             })
        #             # token['gap'] = text[p:p1]
        #         else:
        #             # token['gap'] = None
        #             pass
        #         p = p1 + l
        #         tokens2.append(token)
        #     tokens = tokens2
        #     bef_token = None
        #     tokens2=[]
        #     for token in tokens:
        #         if token['pos'] == '名詞' \
        #             and (token['pos_detail1']=='接尾' or token['pos_detail2']=='接尾' or token['pos_detail3']=='接尾') \
        #             and (token['pos_detail1']=='助数詞' or token['pos_detail2']=='助数詞' or token['pos_detail3']=='助数詞') \
        #             and bef_token and bef_token['pos']=='名詞' \
        #             and (bef_token['pos_detail3']=='数' or bef_token['pos_detail3']=='数' or bef_token['pos_detail3']=='数'):
        #             bef_token['surface'] = bef_token['surface'] + token['surface'] if bef_token['surface'] !='*' else token['surface']
        #             bef_token['pos'] = '名詞'
        #             bef_token['pos_detail1'] = '固有名詞'
        #             bef_token['pos_detail2'] = '一般'
        #             bef_token['pos_detail3'] = '*'
        #             bef_token['conjugated_type'] = '*'
        #             bef_token['conjugated_form'] = '*'
        #             bef_token['base_form'] = bef_token['base_form'] + token['base_form'] if bef_token['base_form'] !='*' else token['base_form']
        #             bef_token['reading'] = bef_token['reading'] + token['reading'] if bef_token['reading'] !='*' else token['reading']
        #             bef_token['pronunciation'] = bef_token['pronunciation'] + token['pronunciation'] if bef_token['pronunciation'] !='*' else token['pronunciation']
        #         elif token['pos'] == '名詞' \
        #             and (token['pos_detail1']=='接尾' or token['pos_detail2']=='接尾' or token['pos_detail3']=='接尾') \
        #             and bef_token and bef_token['pos']=='名詞':
        #             bef_token['surface'] = bef_token['surface'] + token['surface'] if bef_token['surface'] !='*' else token['surface']
        #             bef_token['pos'] = '名詞'
        #             bef_token['pos_detail1'] = '固有名詞'
        #             bef_token['pos_detail2'] = '一般'
        #             bef_token['pos_detail3'] = '*'
        #             bef_token['conjugated_type'] = '*'
        #             bef_token['conjugated_form'] = '*'
        #             bef_token['base_form'] = bef_token['base_form'] + token['base_form'] if bef_token['base_form'] !='*' else token['base_form']
        #             bef_token['reading'] = bef_token['reading'] + token['reading'] if bef_token['reading'] !='*' else token['reading']
        #             bef_token['pronunciation'] = bef_token['pronunciation'] + token['pronunciation'] if bef_token['pronunciation'] !='*' else token['pronunciation']
        #         else:
        #             if bef_token:
        #                 tokens2.append(bef_token)
        #             bef_token = token
        #     if bef_token:
        #         tokens2.append(bef_token)
        #     tokens = tokens2
        return tokens

    def proc_one_token(self, token):
        if token['pos'] == '感動詞'\
            and (token['base_form'] not in ['おはよう','おやすみ','こんにちは','こんばんは']):
            return None
        if token['pos'] not in ['名詞','動詞','形容詞']:
            return None
        # if (token['pos_detail1']=='形容動詞語幹' or token['pos_detail2']=='形容動詞語幹' or token['pos_detail3']=='形容動詞語幹'):
        #     return None
        if (token['pos_detail1']=='非自立' or token['pos_detail2']=='非自立' or token['pos_detail3']=='非自立'):
            return None
        if token['pos']=='動詞' \
            and token['base_form'] in ['する','れる','られる','ある','なる','いる','いく','いう','せる']:
            return None
        if token['pos']=='名詞' \
            and token['base_form'] in [
                'デジタルリマスター','リマスター',
                '字幕スーパー','レターボックスサイズ',
                'シリーズ','版','部','シーズン',# 'セレクション', セレクションはショッピング系の重要ワードのため残す
                '人気',
                'テレビ','TV','番組','今回','国民的','人気','このあと','この後',
                '［無料］','［デ］','［二］','［解］','［字］','［SS］'
            ]:
            return 
        if token['pos']=='名詞' \
            and token['pos_detail1'] == 'サ変接続' \
            and token['base_form'] == '*':
            # 記号
            return 
        if token['surface'] == "・" and token['base_form'] == "・":
            # 記号ではなく名詞/数になることがある
            return
        # print(token)
        return token['base_form'] if token['base_form'] !='*' else token['surface']

    def proc_tokens(self, tokenized):
        sentence = []
        for token in tokenized:
            s = self.proc_one_token(token)
            if s:
                sentence.append(s)
        return sentence
