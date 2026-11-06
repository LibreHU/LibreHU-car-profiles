"""Infers the signals of each message of a Car Info decoder from probes (probe.Decoder): which bits of the data move
which reported value, and how (unsigned / signed, big / little endian, factor, offset, or a table of values)."""
import os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jvm import JObject, JArray, Undecidable, UNKNOWN

DATA_LEN = 24
SAMPLES = 24


def _short(c):
    return c.rsplit(".", 1)[-1]


def snapshot(sent, trace):
    """What a packet reported: every scalar of the sent objects (one level of nesting, arrays) and every field written."""
    out = {}

    def put(key, v):
        if isinstance(v, bool):
            v = int(v)
        if isinstance(v, (int, float, str)) or v is None:
            out[key] = v

    def walk(prefix, o, depth):
        for f, v in o.fields.items():
            if f.startswith("_"):
                continue
            k = f"{prefix}.{f}"
            if isinstance(v, JArray):
                if len(v.items) <= 64:
                    for i, x in enumerate(v.items):
                        if isinstance(x, JObject) and depth < 1:
                            walk(f"{k}[{i}]", x, depth + 1)
                        else:
                            put(f"{k}[{i}]", x)
            elif isinstance(v, JObject):
                if depth < 1:
                    walk(k, v, depth + 1)
            else:
                put(k, v)

    for t, o in sent:
        if isinstance(o, JObject):
            walk(f"{t}:{_short(o.cls)}", o, 0)
        else:
            put(f"{t}:value", o)
    for o, f, v in trace:
        put(f"w:{_short(o.cls)}.{f}", v)
    return out


def run(dec, cmd, data, reads=None):
    f = dec.frame(cmd, [b - 256 if b > 127 else b for b in data])
    if not isinstance(f, JArray):
        raise Undecidable("no frame")
    sent, trace = dec.handle(f)
    if reads is not None:
        reads |= {r for r in dec.vm.reads if isinstance(r, int)}
    return snapshot(sent, trace), bool(dec.px.sent or trace)


def raw(data, start, n, endian):
    b = data[start:start + n]
    if endian == "little":
        b = b[::-1]
    v = 0
    for x in b:
        v = (v << 8) | x
    return v


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def fit(samples, bits):
    """samples: [(data, value)]; bits: [(byte, bit)] that move the value. Returns a signal description or None."""
    bytes_ = sorted({b for b, _ in bits})
    lo, hi = bytes_[0], bytes_[-1]
    n = hi - lo + 1
    if n > 4 or not all(_num(v) for _, v in samples):
        return None
    if n == 1:
        bb = sorted(bit for b, bit in bits)
        first, length = bb[0], bb[-1] - bb[0] + 1
    else:
        first, length = 0, 8 * n
    cands = []
    for endian in (("big", "little") if n > 1 else ("big",)):
        for signed in (False, True):
            for sm in ((False, True) if not signed else (False,)):
                def rv(d):
                    r = raw(d, lo, n, endian)
                    if n == 1:
                        r = (r >> first) & ((1 << length) - 1)
                    w = length if n == 1 else 8 * n
                    if sm:
                        mag = r & ((1 << (w - 1)) - 1)
                        return -mag if r >> (w - 1) else mag
                    if signed and r >> (w - 1):
                        r -= 1 << w
                    return r
                pts = [(rv(d), v) for d, v in samples]
                c = _line(pts)
                if c:
                    a, b, share = c
                    cands.append({"start_byte": lo, "size": n, "bit": first, "bit_length": length, "endian": endian,
                                  "signed": signed, "sign_magnitude": sm, "factor": a, "offset": b, "_share": share})
    if not cands:
        return None
    # The plainest description: unsigned, big endian, no sign-magnitude.
    cands.sort(key=lambda c: (-c["_share"], c["sign_magnitude"], c["signed"], c["endian"] != "big"))
    best = dict(cands[0])
    best.pop("_share")
    return best


def _interval(on):
    """value = trunc(a * raw) (Java's (int) cast): the a that fits every point, from the bounds each point sets."""
    lo, hi = -1e18, 1e18
    for x, y in on:
        if x == 0:
            if y != 0:
                return None
            continue
        # trunc(a*x) == y  ⇔  a*x ∈ [y, y+1) for y > 0, (y-1, y] for y < 0, (-1, 1) for y == 0
        if y > 0:
            l, h = y / x, (y + 1) / x
        elif y < 0:
            l, h = (y - 1) / x, y / x
        else:
            l, h = -1 / x, 1 / x
        l, h = min(l, h), max(l, h)
        lo, hi = max(lo, l), min(hi, h)
    if lo > hi:
        return None
    m = (lo + hi) / 2
    # As few digits as the bounds allow.
    for d in range(1, 9):
        r = round(m, d)
        if lo <= r <= hi:
            return r
    return round(m, 9)


def _line(pts):
    """value = a * raw + b on most points (the rest: clamped or invalid values); ints may be truncated."""
    xs = {x for x, _ in pts}
    if len(xs) < 3:
        return None
    ints = all(isinstance(y, int) for _, y in pts)
    tol = lambda y: (1.0 if ints else 1e-3 * max(1.0, abs(y)))
    best = None
    pts_u = sorted(set(pts))
    # Lines through pairs of points (a few), kept when most points sit on them; then refined by least squares.
    import itertools
    pairs = list(itertools.combinations(pts_u, 2))
    if len(pairs) > 300:
        pairs = random.Random(7).sample(pairs, 300)
    ys = [y for _, y in pts]
    ends = {min(ys), max(ys)}
    for (x1, y1), (x2, y2) in pairs:
        if x1 == x2:
            continue
        a = (y2 - y1) / (x2 - x1)
        b = y1 - a * x1
        on = [(x, y) for x, y in pts if abs(a * x + b - y) <= tol(y) + 1e-9]
        if len(on) < 3 or len({x for x, _ in on}) < 3:
            continue
        n = len(on)
        mx = sum(x for x, _ in on) / n
        my = sum(y for _, y in on) / n
        sxx = sum((x - mx) ** 2 for x, _ in on)
        if sxx:
            a2 = sum((x - mx) * (y - my) for x, y in on) / sxx
            b2 = my - a2 * mx
            if all(abs(a2 * x + b2 - y) <= tol(y) + 1e-9 for x, y in on):
                a, b = a2, b2
        if a == 0:
            continue
        share = n / len(pts)
        off = {y for x, y in pts if abs(a * x + b - y) > tol(y) + 1e-9}
        # The points off the line: clamped (the extremes) or one invalid value.
        if ints and abs(b) < 1:
            r = _interval(on)
            if r is not None:
                a, b = r, 0.0
        if (share >= 0.6 or (len({x for x, _ in on}) >= 6 and (off <= ends or len(off) == 1))) and (best is None or share > best[2]):
            best = (round(a, 6), round(b, 4), share)
    return best


def message(dec, cmd, rnd):
    """The signals of one message: {output key: description}."""
    base_list = [bytes(DATA_LEN), bytes([0xFF]) * DATA_LEN] + [bytes(rnd.randrange(256) for _ in range(DATA_LEN)) for _ in range(3)]
    influence = {}
    handled = False
    seen_keys = set()
    for base in base_list:
        reads = set()
        try:
            s0, h = run(dec, cmd, base, reads)
        except Undecidable:
            continue
        handled |= h
        seen_keys |= set(s0)
        for i in sorted(reads):
            for bit in range(8):
                d = bytearray(base)
                d[i] ^= 1 << bit
                try:
                    s0, _ = run(dec, cmd, base)  # back to the base (decoders that act on a change)
                    s1, _ = run(dec, cmd, bytes(d))
                except Undecidable:
                    continue
                for k in set(s0) | set(s1):
                    if s0.get(k) != s1.get(k):
                        influence.setdefault(k, set()).add((i, bit))
    if not handled:
        return None
    # Keep a written field only when no reported value shows the same thing.
    keys = [k for k in influence if not k.startswith("w:")] or list(influence)
    used = sorted({b for k in keys for b, _ in influence[k]})
    # One batch of random frames for every value (half of them small numbers: other bytes 00 or FF).
    batch = []
    for t in range(SAMPLES * 2):
        d = bytearray(rnd.randrange(256) for _ in range(DATA_LEN))
        if t % 2:
            fill = rnd.choice((0, 0xFF))
            for i in used:
                if rnd.random() < 0.5:
                    d[i] = fill
        try:
            s, _ = run(dec, cmd, bytes(d))
        except Undecidable:
            continue
        batch.append((bytes(d), s))
    tables = {}
    sigs = {}
    def table_of(b0):
        if b0 not in tables:
            tables[b0] = []
            for v in range(256):
                d = bytearray(DATA_LEN)
                d[b0] = v
                try:
                    run(dec, cmd, bytes(d))  # twice: decoders that act on a change
                    s, _ = run(dec, cmd, bytes(d))
                except Undecidable:
                    continue
                tables[b0].append((v, s))
        return tables[b0]

    for k in keys:
        bits = influence[k]
        byte_set = sorted({b for b, _ in bits})
        if len(byte_set) == 1:
            b0 = byte_set[0]
            mask = sum(1 << b for _, b in bits)
            desc = from_table(b0, mask, [(v, s[k]) for v, s in table_of(b0) if k in s])
            if desc is None:
                continue
        else:
            samples = [(d, s[k]) for d, s in batch if k in s]
            desc = fit(samples, bits) if samples else None
            if desc is None:
                desc = {"bytes": byte_set, "bits": sorted(bits)[:24], "kind": "complex"}
        sigs[k] = desc
    return sigs


def from_table(b0, mask, rows):
    """A one-byte value from all 256 values of its byte: a number (raw, factor, offset, clamp) or a table."""
    full = dict(rows)
    # Bits that change nothing once the others are known (a decoder that acts on any change of the byte): out.
    for b in range(8):
        bit = 1 << b
        if mask & bit and all(full.get(v ^ bit, y) == y for v, y in full.items()):
            mask &= ~bit
    if not mask or len({y for _, y in rows}) < 2:
        return None
    lsb = (mask & -mask).bit_length() - 1
    width = mask.bit_length() - lsb
    contiguous = mask >> lsb == (1 << width) - 1
    by_raw = {}
    for v, y in rows:
        if contiguous:
            r = (v & mask) >> lsb
        else:
            r = v & mask
        by_raw.setdefault(r, set()).add(y if not isinstance(y, float) else round(y, 6))
    if any(len(ys) > 1 for ys in by_raw.values()) or not by_raw:
        # Depends on more than these bits (another flag of the byte): plain table of the whole byte.
        return {"start_byte": b0, "mask": 255, "kind": "table", "values": {v: y for v, y in rows}}
    pts = sorted((r, next(iter(ys))) for r, ys in by_raw.items())
    base = {"start_byte": b0}
    if contiguous and width < 8:
        base.update(bit=lsb, bit_length=width)
    elif not contiguous:
        base.update(mask=mask)
    if contiguous and len(pts) > 2 and all(_num(y) for _, y in pts):
        for signed, sm in ((False, False), (True, False), (False, True)):
            def conv(r):
                if sm:
                    m = r & ((1 << (width - 1)) - 1)
                    return -m if r >> (width - 1) else m
                if signed and r >> (width - 1):
                    return r - (1 << width)
                return r
            q = [(conv(r), y) for r, y in pts]
            (x1, y1), (x2, y2) = q[0], q[1]
            if x1 == x2:
                continue
            a = (y2 - y1) / (x2 - x1)
            b = y1 - a * x1
            on = [abs(a * x + b - y) < 1e-6 * max(1, abs(y)) for x, y in q]
            if all(on) and a:
                return dict(base, factor=round(a, 6), offset=round(b, 6), signed=signed, sign_magnitude=sm)
            # A number up to a limit (radar levels, …): linear on the values below the first one off the line.
            n_on = next((i for i, o in enumerate(on) if not o), len(on))
            if a and n_on >= 3 and not signed and not sm:
                rest = {y for _, y in q[n_on:]}
                if len(rest) == 1:
                    return dict(base, factor=round(a, 6), offset=round(b, 6), max_raw=q[n_on - 1][0], above=rest.pop())
    if len(pts) <= 2 and all(_num(y) for _, y in pts) and contiguous and width == 1:
        return dict(base, kind="flag", values={r: y for r, y in pts})
    return dict(base, kind="table", values={r: y for r, y in pts})


def decoder(dec, cmds=None, seed=1):
    rnd = random.Random(seed)
    out = {}
    for cmd in (cmds or sorted(dec.px.registered)):
        try:
            m = message(dec, cmd, rnd)
        except Undecidable:
            m = None
        if m:
            out[cmd] = m
    return out


if __name__ == "__main__":
    import json
    from jvm import Index
    import probe
    src, cls = sys.argv[1], sys.argv[2]
    cmds = [int(x, 0) for x in sys.argv[3:]] or None
    d = probe.Decoder(Index(src), cls)
    res = decoder(d, cmds)
    for cmd, sigs in res.items():
        print(f"0x{cmd:02X}")
        for k, v in sorted(sigs.items()):
            if k.startswith("w:"):
                continue
            print("   ", k, json.dumps(v, ensure_ascii=False)[:200])
