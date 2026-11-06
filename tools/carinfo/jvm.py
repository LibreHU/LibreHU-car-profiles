"""A small interpreter of jadx "fallback" listings (jadx -m fallback --no-inline-anonymous --no-move-inner-classes):
registers, constants, arithmetic with Java widths, arrays, objects and their fields, virtual / static / super calls,
if / goto / switch. It replays methods of a decompiled app on chosen inputs; nothing of the app is executed, and
anything it does not know (Android, I/O, threads) gives Unknown, which stops a run only when a branch needs it."""
import os
import re

MAX_STEPS = 400_000

_LISTS = ("java.util.ArrayList", "java.util.LinkedList", "java.util.Vector", "java.util.concurrent.CopyOnWriteArrayList")
_MAPS = ("android.util.SparseBooleanArray", "android.util.SparseIntArray", "android.util.SparseArray", "android.util.SparseLongArray",
         "java.util.HashMap", "java.util.LinkedHashMap", "java.util.TreeMap", "android.util.ArrayMap", "java.util.concurrent.ConcurrentHashMap",
         "java.util.Hashtable")
_SETS = ("java.util.HashSet", "java.util.LinkedHashSet", "java.util.TreeSet", "android.util.ArraySet")
NATIVE_KINDS = {**{t: "list" for t in _LISTS}, **{t: "map" for t in _MAPS}, **{t: "set" for t in _SETS}}
_DEFAULTS = {"android.util.SparseBooleanArray": 0, "android.util.SparseIntArray": 0, "android.util.SparseLongArray": 0}
MAX_DEPTH = 80


class Undecidable(Exception):
    pass


class _Unknown:
    def __repr__(self):
        return "?"


UNKNOWN = _Unknown()


class JObject:
    __slots__ = ("cls", "fields", "native")

    def __init__(self, cls, native=None):
        self.cls = cls
        self.fields = {}
        self.native = native

    def __repr__(self):
        return f"<{self.cls.rsplit('.', 1)[-1]}>"


class JArray:
    __slots__ = ("items", "kind", "origin")

    def __init__(self, items, kind="byte", origin=None):
        self.items = items
        self.kind = kind
        self.origin = origin  # per item: where it came from (a probe's data index), to know what a decoder reads

    def __repr__(self):
        return f"{self.kind}[{len(self.items)}]"


class Method:
    def __init__(self, cls, name, params, types, static, body):
        self.cls, self.name, self.params, self.types, self.static, self.body = cls, name, params, types, static, body
        self.ops = None
        self.labels = {}
        for i, l in enumerate(body):
            m = re.match(r"^(L[0-9a-f]+):$", l)
            if m:
                self.labels[m.group(1)] = i


class JClass:
    def __init__(self, name, sup, ifaces):
        self.name, self.sup, self.ifaces = name, sup, ifaces
        self.statics = {}
        self.static_names = set()
        self.methods = {}


HEAD = re.compile(r"^(?:public |private |protected |abstract |final |static |/\* \w+ \*/ )*(?:class|interface|enum) ([\w$]+)(?: extends ([\w.$]+))?(?: implements ([^{]+))? \{$")
FIELD = re.compile(r"^    (?:(?:public|private|protected|static|final|volatile|transient|/\* \w+ \*/) )*([\w.$\[\]<>?, ]+?) (\w+)(?: = (.+))?;$")
METH = re.compile(r"^    ((?:(?:public|private|protected|static|final|synchronized|abstract|native|strictfp|/\* \w+ \*/) )*)(?:<[^>]+> )?(?:([\w.$\[\]<>?, ]+?) )?([\w$<>]+)\((.*)\)(?: throws [\w., $]+)? \{$")


def _const(t):
    t = t.strip()
    if len(t) > 2 and t[0] == "(" and t[-1] == ")" and re.match(r"^\(-?[\d.]+[LfFdD]?\)$", t):
        t = t[1:-1]
    if t == "null":
        return None
    if t in ("true", "false"):
        return 1 if t == "true" else 0
    if t.startswith('"') and t.endswith('"'):
        return t[1:-1].encode().decode("unicode_escape", "replace") if "\\" in t else t[1:-1]
    m = re.match(r"^(-?\d+)L?~[fd](.*)$", t)
    if m:
        b = Bits(int(m.group(1)))
        try:
            b.f = float(m.group(2))
        except ValueError:
            b.f = float("nan")
        return b
    m = re.match(r"^(-?\d+)(?:L)?(?:\(.*\))?$", t)
    if m:
        return int(m.group(1))
    m = re.match(r"^(-?\d*\.\d+(?:[eE]-?\d+)?)[fFdD]?(?:\(.*\))?$", t)
    if m:
        return float(m.group(1))
    m = re.match(r"^'(.)'(?:\(.*\))?$", t)
    if m:
        return ord(m.group(1))
    return UNKNOWN


class Index:
    """The classes of a jadx output folder, read on demand."""

    def __init__(self, root):
        self.root = root.rstrip("/") + "/sources"
        self.cache = {}

    def path(self, fqn):
        pkg, _, simple = fqn.rpartition(".")
        return os.path.join(self.root, pkg.replace(".", "/"), simple + ".java")

    def get(self, fqn):
        if fqn in self.cache:
            return self.cache[fqn]
        p = self.path(fqn)
        c = self._parse(fqn, p) if os.path.exists(p) else None
        self.cache[fqn] = c
        return c

    def _parse(self, fqn, path):
        lines = open(path, encoding="utf-8", errors="replace").read().split("\n")
        pkg = fqn.rpartition(".")[0]
        cls = None
        i = 0
        while i < len(lines):
            l = lines[i]
            m = HEAD.match(l)
            if m and cls is None:
                sup = m.group(2)
                cls = JClass(fqn, sup, [x.strip() for x in (m.group(3) or "").split(",") if x.strip()])
                i += 1
                continue
            if cls is None:
                i += 1
                continue
            if l == "    static {":
                body, i = self._body(lines, i + 1)
                cls.methods.setdefault("<clinit>", []).append(Method(fqn, "<clinit>", [], [], True, body))
                continue
            m = METH.match(l)
            if m and not l.startswith("        "):
                mods, _ret, name, args = m.groups()
                simple = fqn.rpartition(".")[2]
                if name == simple or name == simple.rpartition("$")[2]:
                    name = "<init>"
                params, types = [], []
                for a in [x.strip() for x in re.split(r",(?![^<]*>)", args) if x.strip()]:
                    t, _, r = a.rpartition(" ")
                    types.append(t.split(" ")[-1])
                    params.append(r)
                body, i = self._body(lines, i + 1)
                cls.methods.setdefault(name, []).append(Method(fqn, name, params, types, "static" in mods, body))
                continue
            m = FIELD.match(l)
            if m and " static " in " " + l:
                cls.static_names.add(m.group(2))
                if m.group(3) is not None:
                    cls.statics[m.group(2)] = _const(m.group(3))
            i += 1
        return cls

    @staticmethod
    def _body(lines, i):
        body = []
        while i < len(lines) and lines[i] != "    }":
            l = re.sub(r"\s{2,}// (?:Catch|Error|Exception|TODO|Method).*$", "", lines[i])
            l = _ANNOT.sub(_annot, l)
            body.append(l.strip())
            i += 1
        return body, i + 1


_ANNOT = re.compile(r"(\d[L]?)\((?:-?0x[0-9a-f]+|-?\d+)(?:, (float|double):([^)]*))?\)")


def _annot(m):
    # "1141309440(0x44070000, float:540.0)": an int that may be the bits of a float: keep both ("1141309440~f540.0").
    if m.group(2):
        return f"{m.group(1)}~{m.group(2)[0]}{m.group(3)}"
    return m.group(1)


class Bits(int):
    """An int constant that is maybe the bits of a float / double (the listing does not say which): .f is that float."""
    f = 0.0


def _float(x):
    return x.f if isinstance(x, Bits) else float(x)


def _wrap(v, kind):
    if not isinstance(v, int) or isinstance(v, bool):
        return v
    if kind == "byte":
        return ((v + 128) & 0xFF) - 128
    if kind == "short":
        return ((v + 0x8000) & 0xFFFF) - 0x8000
    if kind == "char":
        return v & 0xFFFF
    if kind == "long":
        return ((v + (1 << 63)) & ((1 << 64) - 1)) - (1 << 63)
    return ((v + (1 << 31)) & 0xFFFFFFFF) - (1 << 31)


_EXPR_PATTERNS = [
    ("cast", re.compile(r"^\((byte|short|int|long|char|float|double|boolean)\) (\S+)$")),
    ("ocast", re.compile(r"^\(([\w.$]+(?:\[\])*)\) (\S+)$")),
    ("bin", re.compile(r"^(\S+) (\+|-|\*|/|%|&|\||\^|<<|>>>|>>) (\S+)$")),
    ("neg", re.compile(r"^-(\S+)$")),
    ("cmp", re.compile(r"^\((\S+) ([<>]) (\S+) \? 1 : \(\S+ == \S+ \? 0 : -1\)\)$")),
    ("inst", re.compile(r"^(\S+) instanceof ([\w.$]+)$")),
    ("newarr", re.compile(r"^new ([\w.$]+)\[([^\]]+)\](\[\])*$")),
    ("newarrinit", re.compile(r"^new ([\w.$]+)\[\]\{(.*)\}$")),
    ("new", re.compile(r"^new ([\w.$]+)$")),
    ("len", re.compile(r"^(\S+)\.length$")),
    ("aget", re.compile(r"^(r\d+)\[(\S+)\]$")),
    ("call", re.compile(r"^(super|r\d+|[\w$]+(?:\.[\w$]+)*)\.([\w$<>]+)\((.*)\)$")),
    ("iget", re.compile(r"^(r\d+)\.([\w$]+)$")),
    ("sget", re.compile(r"^([\w$]+(?:\.[\w$]+)+)\.([\w$]+)$")),
]
_EXPR_CACHE = {}


def _classify(e):
    r = _EXPR_CACHE.get(e)
    if r is not None:
        return r
    e2 = e.strip()
    r = ("other", (e2,))
    if len(e2) >= 2 and e2[0] == '"' and e2[-1] == '"' and '"' not in e2[1:-1].replace('\\"', ""):
        r = ("const", (_const(e2),))
    else:
        for tag, pat in _EXPR_PATTERNS:
            m = pat.match(e2)
            if m:
                if tag == "neg" and re.match(r"^-\d", e2):
                    continue
                g = m.groups()
                if tag == "call":
                    g = (g[0], g[1], tuple(_split(g[2])))
                r = (tag, g)
                break
    _EXPR_CACHE[e] = r
    return r


_CONST_CACHE = {}


def _const_c(t):
    r = _CONST_CACHE.get(t, _CONST_CACHE)
    if r is _CONST_CACHE:
        r = _const(t)
        _CONST_CACHE[t] = r
    return r


class VM:
    """Replays methods. [natives]: (class, method) → python function(vm, this, args), for what the app reaches
    outside itself (or what a run needs to see, as the inputs of a car)."""

    def __init__(self, index, natives=None):
        self.index = index
        self.natives = natives or {}
        self.statics = {}
        self.steps = 0
        self.depth = 0
        self.trace = []  # (object, field, value) of every field write, for probing
        self._chains = {}
        self.reads = set()  # origins of the array items read (see JArray.origin)

    # --- classes -------------------------------------------------------------------------------------------
    def chain(self, fqn):
        r = self._chains.get(fqn)
        if r is None:
            r = self._chains[fqn] = self._chain(fqn)
        return r

    def _chain(self, fqn):
        out = []
        while fqn:
            c = self.index.get(fqn)
            if c is None:
                out.append(fqn)
                break
            out.append(fqn)
            fqn = c.sup
        return out

    def is_a(self, obj, fqn):
        if not isinstance(obj, JObject):
            return False
        seen = set()
        todo = [obj.cls]
        while todo:
            c = todo.pop()
            if c == fqn:
                return True
            if c in seen:
                continue
            seen.add(c)
            k = self.index.get(c)
            if k:
                todo += ([k.sup] if k.sup else []) + k.ifaces
        return False

    def find(self, fqn, name, n, start_super=False):
        cls = fqn
        first = True
        while cls:
            k = self.index.get(cls)
            if k is None:
                return None
            if not (start_super and first):
                for m in k.methods.get(name, []):
                    if len(m.params) == n:
                        return m
            first = False
            cls = k.sup
        return None

    def owner(self, fqn, field):
        """The class that declares the static [field] read or written through [fqn] (maybe a parent class)."""
        for c in self.chain(fqn):
            k = self.index.get(c)
            if k is None:
                break
            if field in k.static_names:
                return c
        return fqn

    def static_get(self, fqn, field):
        fqn = self.owner(fqn, field)
        key = (fqn, field)
        if key not in self.statics:
            self.clinit(fqn)
            k = self.index.get(fqn)
            if key not in self.statics:
                self.statics[key] = k.statics.get(field, 0) if k and field in k.statics else (k.statics.get(field) if k else UNKNOWN)
        return self.statics[key]

    def clinit(self, fqn):
        if ("<clinit>", fqn) in self.statics:
            return
        self.statics[("<clinit>", fqn)] = True
        k = self.index.get(fqn)
        if k:
            for f, v in k.statics.items():
                self.statics.setdefault((fqn, f), v)
            for m in k.methods.get("<clinit>", []):
                try:
                    self.run(m, None, [])
                except Undecidable:
                    pass

    def new(self, fqn, *args):
        o = JObject(fqn)
        self.clinit(fqn)
        self.invoke(o, "<init>", list(args), fqn)
        return o

    # --- calls ---------------------------------------------------------------------------------------------
    def invoke(self, this, name, args, fqn=None, sup=False, static_cls=None):
        cls = static_cls or (fqn if sup else (this.cls if isinstance(this, JObject) else fqn))
        if cls is None:
            return self.outside(None, name, this, args)
        for c in self.chain(cls):
            f = self.natives.get((c, name)) or self.natives.get((c, name, len(args)))
            if f:
                return f(self, this, args)
        m = self.find(cls, name, len(args), start_super=sup)
        if m is None:
            return self.outside(cls, name, this, args)
        return self.run(m, this, args)

    def outside(self, cls, name, this, args):
        """What the app calls outside of its own code."""
        f = self.natives.get(("*", name))
        if f:
            return f(self, this, args)
        if name == "<init>":
            return None
        if cls in ("java.lang.Integer", "java.lang.Byte", "java.lang.Short", "java.lang.Long") and name == "valueOf":
            return args[0]
        if name in ("intValue", "byteValue", "shortValue", "longValue") and isinstance(this, int):
            return _wrap(this, name[:-5])
        if name == "booleanValue" and isinstance(this, int):
            return 1 if this else 0
        if cls == "java.lang.Boolean" and name == "valueOf":
            return args[0]
        if name in ("floatValue", "doubleValue") and isinstance(this, (int, float)):
            return float(this)
        if cls == "java.lang.System" and name == "arraycopy":
            src, sp, dst, dp, n = args
            if isinstance(src, JArray) and isinstance(dst, JArray) and all(isinstance(x, int) for x in (sp, dp, n)):
                if sp < 0 or dp < 0 or n < 0 or sp + n > len(src.items) or dp + n > len(dst.items):
                    raise Undecidable("arraycopy out of bounds")
                dst.items[dp:dp + n] = src.items[sp:sp + n]
                if src.origin is not None or dst.origin is not None:
                    if dst.origin is None:
                        dst.origin = [None] * len(dst.items)
                    dst.origin[dp:dp + n] = src.origin[sp:sp + n] if src.origin is not None else [None] * n
                return None
            raise Undecidable("arraycopy on unknown")
        if cls == "java.util.Arrays":
            a = args
            if name == "fill" and isinstance(a[0], JArray):
                if len(a) == 2:
                    a[0].items[:] = [a[1]] * len(a[0].items)
                elif all(isinstance(x, int) for x in a[1:3]):
                    a[0].items[a[1]:a[2]] = [a[3]] * (a[2] - a[1])
                return None
            if name == "equals":
                if isinstance(a[0], JArray) and isinstance(a[1], JArray):
                    return 1 if a[0].items == a[1].items else 0
                return 1 if a[0] is a[1] else 0
            if name == "copyOfRange" and isinstance(a[0], JArray) and isinstance(a[1], int) and isinstance(a[2], int):
                part = a[0].items[a[1]:a[2]]
                pad = a[2] - a[1] - len(part)
                org = (a[0].origin[a[1]:a[2]] + [None] * pad) if a[0].origin is not None else None
                return JArray(part + [0] * pad, a[0].kind, org)
            if name == "copyOf" and isinstance(a[0], JArray) and isinstance(a[1], int):
                part = a[0].items[:a[1]]
                pad = a[1] - len(part)
                org = (a[0].origin[:a[1]] + [None] * pad) if a[0].origin is not None else None
                return JArray(part + [0] * pad, a[0].kind, org)
            if name == "toString":
                return ""
        if cls == "java.lang.Math":
            a = args
            if name == "abs":
                return abs(a[0]) if isinstance(a[0], (int, float)) else UNKNOWN
            if name in ("min", "max"):
                return (min if name == "min" else max)(a) if all(isinstance(x, (int, float)) for x in a) else UNKNOWN
            if name == "round":
                return int(a[0] + 0.5) if isinstance(a[0], (int, float)) else UNKNOWN
        if cls == "java.lang.Float" and name in ("intBitsToFloat",):
            return UNKNOWN
        if name == "clone" and isinstance(this, JArray):
            return JArray(list(this.items), this.kind, list(this.origin) if this.origin is not None else None)
        if name == "length" and isinstance(this, str):
            return len(this)
        if isinstance(this, JObject) and this.native == "list":
            lst = this.fields.setdefault("_items", [])
            if name == "add":
                lst.append(args[-1]) if len(args) == 1 else lst.insert(args[0], args[1])
                return 1
            if name == "get":
                return lst[args[0]] if isinstance(args[0], int) and 0 <= args[0] < len(lst) else UNKNOWN
            if name == "size":
                return len(lst)
            if name == "clear":
                lst.clear()
                return None
            if name == "isEmpty":
                return 1 if not lst else 0
            if name == "contains":
                return 1 if args[0] in lst else 0
        if isinstance(this, JObject) and this.native == "map":
            d = this.fields.setdefault("_map", {})
            key = lambda k: k if isinstance(k, (int, str, float)) else id(k)
            if name in ("put", "append"):
                d[key(args[0])] = (args[0], args[1])
                return None
            if name in ("get", "getOrDefault"):
                k = key(args[0])
                if k in d:
                    return d[k][1]
                return args[1] if len(args) > 1 else _DEFAULTS.get(this.cls)
            if name in ("containsKey",):
                return 1 if key(args[0]) in d else 0
            if name == "indexOfKey":
                return list(d).index(key(args[0])) if key(args[0]) in d else -1
            if name == "size":
                return len(d)
            if name in ("keyAt", "valueAt"):
                items = sorted(d.values(), key=lambda kv: kv[0]) if this.cls.startswith("android.util.Sparse") else list(d.values())
                i = args[0]
                return items[i][0 if name == "keyAt" else 1] if isinstance(i, int) and 0 <= i < len(items) else UNKNOWN
            if name in ("remove", "delete"):
                d.pop(key(args[0]), None)
                return None
            if name == "clear":
                d.clear()
                return None
            if name == "isEmpty":
                return 1 if not d else 0
        if isinstance(this, JObject) and this.native == "set":
            st = this.fields.setdefault("_set", set())
            if name == "add":
                st.add(args[0])
                return 1
            if name == "contains":
                return 1 if args[0] in st else 0
            if name == "size":
                return len(st)
        return UNKNOWN

    # --- running -------------------------------------------------------------------------------------------
    def run(self, m, this, args):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            self.depth -= 1
            raise Undecidable("too deep")
        try:
            return self._run(m, this, args)
        except Undecidable as x:
            if not hasattr(x, "where"):
                x.where = f"{m.cls.rsplit('.', 1)[-1]}.{m.name}"
            raise
        finally:
            self.depth -= 1

    def _run(self, m, this, args):
        regs = {}
        ops = m.ops if m.ops is not None else _compile(m)
        pc = 0
        if ops and ops[0][0] == "this":
            regs[ops[0][1]] = this
            pc = 1
        for p, t, a in zip(m.params, m.types, args):
            regs[p] = a.f if (t in ("float", "double") and isinstance(a, Bits)) else a
        cls = m.cls

        def val(t):
            if t in regs:
                return regs[t]
            if t == "this":
                return this
            c = _const_c(t)
            if c is not UNKNOWN or t == "null":
                return c
            raise Undecidable(f"value {t}")

        n = len(ops)
        labels = m.labels
        while pc < n:
            self.steps += 1
            if self.steps > MAX_STEPS:
                raise Undecidable("steps")
            op = ops[pc]
            pc += 1
            tag = op[0]
            if tag == "skip":
                continue
            if tag == "assign":
                _, target, treg, expr, kind = op
                v = self.expr(expr, val, cls, this, regs, kind)
                if kind in ("float", "double") and isinstance(v, Bits):
                    v = v.f
                if treg:
                    regs[target] = _wrap(v, kind) if kind in ("byte", "short", "char", "int", "long") else v
                else:
                    self.store(target, v, val, kind)
                continue
            if tag == "if":
                _, a, o, b, L, line = op
                x, y = val(a), val(b)
                if x is UNKNOWN or y is UNKNOWN:
                    raise Undecidable(f"branch on unknown: {line}")
                if y == 0 and not isinstance(x, (int, float)):
                    x = 0 if x is None else 1
                if x == 0 and not isinstance(y, (int, float)):
                    y = 0 if y is None else 1
                if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                    if o == "==":
                        ok = x is y
                    elif o == "!=":
                        ok = x is not y
                    else:
                        raise Undecidable(line)
                elif o == "==":
                    ok = x == y
                elif o == "!=":
                    ok = x != y
                elif o == "<":
                    ok = x < y
                elif o == ">":
                    ok = x > y
                elif o == "<=":
                    ok = x <= y
                else:
                    ok = x >= y
                if ok:
                    pc = labels[L]
                continue
            if tag == "goto":
                pc = labels[op[1]]
                continue
            if tag == "call":
                self.expr(op[1], val, cls, this, regs, None)
                continue
            if tag == "switch":
                _, reg, cases, default, end = op
                x = val(reg)
                if x is UNKNOWN:
                    raise Undecidable("switch on unknown")
                L = cases.get(x, default)
                pc = labels[L] if L else end
                continue
            if tag == "ret":
                return None
            if tag == "retv":
                return val(op[1])
            if tag == "throw":
                raise Undecidable("throw")
            if tag == "fill":
                arr = regs.get(op[1])
                if isinstance(arr, JArray):
                    for i, x in enumerate(op[2][: len(arr.items)]):
                        arr.items[i] = _wrap(x, arr.kind) if arr.kind in ("byte", "short", "char", "int", "long") else x
                continue
        return None

    def store(self, target, v, val, kind):
        g = re.match(r"^(r\d+)\[(\S+)\]$", target)
        if g:
            arr, i = val(g.group(1)), val(g.group(2))
            if isinstance(arr, JArray) and isinstance(i, int) and 0 <= i < len(arr.items):
                arr.items[i] = _wrap(v, arr.kind) if arr.kind in ("byte", "short", "char", "int", "long") else v
                if arr.origin is not None:
                    arr.origin[i] = None
            return
        obj, _, field = target.rpartition(".")
        if re.match(r"^r\d+$", obj):
            o = val(obj)
            if isinstance(o, JObject):
                o.fields[field] = v
                self.trace.append((o, field, v))
            return
        self.statics[(self.owner(obj, field), field)] = v

    def expr(self, e, val, cls, this, regs, kind):
        tag, g = _classify(e)
        if tag == "const":
            return g[0]
        if tag == "iget":
            o = val(g[0])
            if isinstance(o, JObject):
                if g[1] in o.fields:
                    return o.fields[g[1]]
                return self.default_field(o, g[1])
            return UNKNOWN
        if tag == "cast":
            x = val(g[1])
            t = g[0]
            if x is UNKNOWN:
                return UNKNOWN
            if t in ("float", "double"):
                return float(x)
            if isinstance(x, float):
                x = int(x)
            return _wrap(x, t) if t != "boolean" else x
        if tag == "ocast":
            return val(g[1])
        if tag == "bin":
            a, op, b = val(g[0]), g[1], val(g[2])
            if a is UNKNOWN or b is UNKNOWN or not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
                return UNKNOWN
            if kind in ("float", "double") or isinstance(a, float) or isinstance(b, float):
                if op in ("+", "-", "*", "/", "%"):
                    a, b = (_float(a) if isinstance(a, int) else a), (_float(b) if isinstance(b, int) else b)
            else:
                a = int(a) if isinstance(a, Bits) else a
                b = int(b) if isinstance(b, Bits) else b
            k = kind or ("long" if (isinstance(a, int) and abs(a) > 0xFFFFFFFF) else "int")
            if op == "+":
                r = a + b
            elif op == "-":
                r = a - b
            elif op == "*":
                r = a * b
            elif op == "/":
                if b == 0:
                    raise Undecidable("division by zero")
                r = a / b if isinstance(a, float) or isinstance(b, float) else int(a / b)
            elif op == "%":
                if b == 0:
                    raise Undecidable("division by zero")
                r = a - int(a / b) * b if not isinstance(a, float) else a % b
            elif op in ("&", "|", "^"):
                a, b = int(a), int(b)
                r = a & b if op == "&" else a | b if op == "|" else a ^ b
            elif op == "<<":
                r = int(a) << (int(b) & (63 if k == "long" else 31))
            elif op == ">>":
                r = int(a) >> (int(b) & (63 if k == "long" else 31))
            else:
                bits = 64 if k == "long" else 32
                r = (int(a) & ((1 << bits) - 1)) >> (int(b) & (bits - 1))
            return r if isinstance(r, float) else _wrap(r, k if k in ("long",) else "int")
        if tag == "neg":
            x = val(g[0])
            return -x if isinstance(x, (int, float)) else UNKNOWN
        if tag == "cmp":
            a, b = val(g[0]), val(g[2])
            if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
                return UNKNOWN
            if isinstance(a, float) or isinstance(b, float):
                a, b = (_float(a) if isinstance(a, int) else a), (_float(b) if isinstance(b, int) else b)
            if g[1] == ">":
                return 1 if a > b else (0 if a == b else -1)
            return -1 if a < b else (0 if a == b else 1)
        if tag == "inst":
            return 1 if self.is_a(val(g[0]), g[1]) else 0
        if tag == "newarr":
            n = val(g[1])
            if not isinstance(n, int) or n < 0 or n > 100000:
                return UNKNOWN
            t = g[0]
            return JArray([0 if t in ("byte", "short", "int", "long", "char", "boolean") else (0.0 if t in ("float", "double") else None)] * n, t if t in ("byte", "short", "int", "long", "char", "float", "double", "boolean") else "obj")
        if tag == "newarrinit":
            return JArray([val(x) for x in g[1].split(",") if x.strip()], g[0])
        if tag == "new":
            t = g[0]
            o = JObject(t, native=NATIVE_KINDS.get(t))
            self.clinit(t)
            return o
        if tag == "len":
            a = val(g[0])
            return len(a.items) if isinstance(a, JArray) else (len(a) if isinstance(a, str) else UNKNOWN)
        if tag == "aget":
            a, i = val(g[0]), val(g[1])
            if isinstance(a, JArray) and isinstance(i, int):
                if 0 <= i < len(a.items):
                    if a.origin is not None and a.origin[i] is not None:
                        self.reads.add(a.origin[i])
                    return a.items[i]
                raise Undecidable("index out of bounds")
            return UNKNOWN
        if tag == "call":
            who, name, alist = g
            args = [val(x) for x in alist]
            if who == "super":
                sup = self.index.get(cls).sup if self.index.get(cls) else None
                return self.invoke(this, name, args, fqn=sup, sup=False, static_cls=sup)
            if who[0] == "r" and who[1:].isdigit():
                o = val(who)
                if name == "<init>":
                    if isinstance(o, JObject):
                        # Constructor of this object's class, or (a super(…) call from a constructor) of the parent.
                        target = o.cls
                        if o is this:
                            target = self.index.get(cls).sup if self.index.get(cls) else None
                        m2 = self.find(target, "<init>", len(args)) if target else None
                        f = self.natives.get((target, "<init>")) if target else None
                        if f:
                            return f(self, o, args)
                        if m2:
                            return self.run(m2, o, args)
                    return None
                if isinstance(o, JObject):
                    return self.invoke(o, name, args)
                return self.outside(None, name, o, args)
            # Static: a class name.
            k = self.index.get(who)
            f = None
            for c in self.chain(who):
                f = self.natives.get((c, name)) or self.natives.get((c, name, len(args)))
                if f:
                    break
            if f:
                return f(self, None, args)
            if k:
                mm = self.find(who, name, len(args))
                if mm:
                    self.clinit(who)
                    return self.run(mm, None, args)
            return self.outside(who, name, None, args)
        if tag == "sget":
            return self.static_get(g[0], g[1])
        e = g[0] if tag == "other" else e.strip()
        if e == "this":
            return this
        c = _const_c(e)
        if c is not UNKNOWN or e == "null":
            return c
        if e in regs:
            return regs[e]
        return UNKNOWN

    def default_field(self, o, f):
        return 0


def _compile(m):
    """Each line of a method, read once: what it does (the run then needs no pattern matching)."""
    body = m.body
    ops = []
    i = 0
    while i < len(body):
        line = body[i]
        i += 1
        if i == 1 and re.match(r"^r\d+ = this;?$", line):
            ops.append(("this", line.split(" ")[0]))
            continue
        if not line or re.match(r"^L[0-9a-f]+:$", line) or line.startswith(("//", "/*", "*", "@")):
            ops.append(("skip",))
            continue
        g = re.match(r"^goto (L[0-9a-f]+)$", line)
        if g:
            ops.append(("goto", g.group(1)))
            continue
        g = re.match(r"^if \((\S+) (==|!=|<|>|<=|>=) (\S+)\) goto (L[0-9a-f]+)$", line)
        if g:
            ops.append(("if",) + g.groups() + (line,))
            continue
        g = re.match(r"^switch\((\S+)\) \{$", line)
        if g:
            cases, default, j = {}, None, i
            while j < len(body) and body[j] != "}":
                c = re.match(r"^case (-?\d+): goto (L[0-9a-f]+);$", body[j])
                if c:
                    cases.setdefault(int(c.group(1)), c.group(2))
                d = re.match(r"^default: goto (L[0-9a-f]+);$", body[j])
                if d:
                    default = d.group(1)
                j += 1
            ops.append(("switch", g.group(1), cases, default, j + 1))
            continue
        if line == "return":
            ops.append(("ret",))
            continue
        g = re.match(r"^return (\S+)$", line)
        if g:
            ops.append(("retv", g.group(1)))
            continue
        if line.startswith("throw "):
            ops.append(("throw",))
            continue
        if "move-exception" in line or line.startswith("monitor-") or line == "}" or line.startswith("try {") or line.startswith("} catch") or line.startswith("case ") or line.startswith("default:"):
            ops.append(("skip",))
            continue
        g = re.match(r"^(r\d+) = \{x[0-9a-f]+: FILL_ARRAY_DATA , data: \[([^}\]]*)[}\]]", line)
        if g:
            ops.append(("fill", g.group(1), [_const(x) for x in g.group(2).split(",") if x.strip()]))
            continue
        g = re.match(r"^(?:[\w.$\[\]<>?, ]+ )?(r\d+|[\w$]+\.[\w$.]+|r\d+\[\S+\]) = (.+)$", line)
        if g:
            target, expr = g.groups()
            tm = re.match(r"^(byte|short|int|long|char|float|double|boolean) ", line)
            ops.append(("assign", target, bool(re.match(r"^r\d+$", target)), expr, tm.group(1) if tm else None))
            continue
        ops.append(("call", line))
    m.ops = ops
    return ops


def _split(a):
    out, depth, cur, quote, esc = [], 0, "", False, False
    for ch in a:
        if quote:
            cur += ch
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                quote = False
            continue
        if ch == '"':
            quote = True
            cur += ch
            continue
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        cur += ch
    if cur.strip():
        out.append(cur)
    return [x.strip() for x in out]
