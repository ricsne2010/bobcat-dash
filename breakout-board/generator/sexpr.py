"""Tiny S-expression reader/writer for KiCad files."""
import re

TOKEN = re.compile(r'\(|\)|"(?:\\.|[^"\\])*"|[^\s()"]+')


class Sym(str):
    """An unquoted atom (keyword or number) - written back without quotes."""


def parse(text):
    stack, cur = [], []
    for m in TOKEN.finditer(text):
        t = m.group(0)
        if t == "(":
            stack.append(cur); cur = []
        elif t == ")":
            done = cur; cur = stack.pop(); cur.append(done)
        elif t.startswith('"'):
            cur.append(t[1:-1].replace('\\"', '"').replace("\\\\", "\\"))
        else:
            cur.append(Sym(t))
    return cur[0]


def dump(x, indent=0):
    if isinstance(x, list):
        if not x:
            return "()"
        simple = all(not isinstance(i, list) for i in x)
        if simple and len(x) < 12:
            return "(" + " ".join(dump(i) for i in x) + ")"
        pad = "\t" * (indent + 1)
        head = dump(x[0])
        rest = "\n".join(pad + dump(i, indent + 1) for i in x[1:])
        return f"({head}\n{rest}\n" + "\t" * indent + ")"
    if isinstance(x, Sym):
        return str(x)
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, (int, float)):
        return repr(round(x, 4)) if isinstance(x, float) else str(x)
    s = str(x).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return '"' + s + '"'


def find(node, key):
    return [c for c in node if isinstance(c, list) and c and c[0] == key]


def first(node, key):
    r = find(node, key)
    return r[0] if r else None
