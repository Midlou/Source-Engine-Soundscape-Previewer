import re

TOKEN_RE = re.compile(r'"([^"]*)"|([{}])')

def parse_kv(text):
    tokens = TOKEN_RE.findall(text)
    tokens = [t[0] or t[1] for t in tokens]

    stack = [{}]
    key_stack = []

    i = 0
    while i < len(tokens):
        token = tokens[i]

        if token == "{":
            obj = {}
            parent = stack[-1]

            key = key_stack.pop()
            parent.setdefault(key, []).append(obj)

            stack.append(obj)

        elif token == "}":
            stack.pop()

        else:
            # string
            if i + 1 < len(tokens) and tokens[i + 1] == "{":
                key_stack.append(token)
            else:
                key = token
                value = tokens[i + 1]
                current = stack[-1]

                if key in current:
                    if isinstance(current[key], list):
                        current[key].append(value)
                    else:
                        current[key] = [current[key], value]
                else:
                    current[key] = value
                i += 1

        i += 1

    return stack[0]
