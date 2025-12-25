from kv_parser import parse_kv

def load_soundscapes(path):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    text = text.replace("\\", "/")
    return parse_kv(text)
