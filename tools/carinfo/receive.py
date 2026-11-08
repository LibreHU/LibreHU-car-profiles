"""Which framings a Car Info decoder accepts from the box: the box → head unit direction, checked with the decoder's own
deframer (parsePacket, with its isPacketHeader / parsePacketLength / isValidPacket), never with getPacket, which builds
the head unit → box direction. A frame of each candidate framing (registered command, data 01 02 03 …) is handed to
parsePacket; accepted = true returned and the whole frame consumed.

Usage: python3 -I receive.py <jadx-fallback-dir> <resolve.json> <out.json> [jobs] [class filter]
"""
import json
import os
import signal
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jvm  # noqa: E402
import probe  # noqa: E402
import resolve as R  # noqa: E402

TIME_LIMIT = 300


def frames(cmd, n=6):
    """Box → head unit frames of each candidate framing, for command [cmd] and [n] data bytes."""
    d = [(i + 1) & 0xFF for i in range(n)]
    s = sum(d)
    out = {
        "hiworld": [0x5A, 0xA5, n, cmd] + d + [(n + cmd + s - 1) & 0xFF],
        "hiworld-aa55": [0xAA, 0x55, n, cmd] + d + [(n + cmd + s - 1) & 0xFF],
        "raise": [0x2E, cmd, n] + d + [((cmd + n + s) ^ 0xFF) & 0xFF],
        "raise-fd": [0xFD, n + 3, cmd] + d + [(n + 3 + cmd + s) & 0xFF],
        "raise-fd2": [0xFD, n + 4, cmd] + d + [((n + 4 + cmd + s) >> 8) & 0xFF, (n + 4 + cmd + s) & 0xFF],
        # CYT (BYD): 8 bytes, 55 then 6 data bytes then AA; no length, no checksum.
        "cyt-55-fixed": [0x55] + [(i + 1) for i in range(6)] + [0xAA],
        # CYT (Ford): CMD LEN DATA, no head, no checksum.
        "cyt-55": [cmd, n] + d,
        # Simple (Audi): AA 55 LEN DATA CS, the length is the command; CS = (LEN + ΣD) - 1.
        "simple-aa55-len": [0xAA, 0x55, cmd] + [(i + 1) & 0xFF for i in range(cmd)] + [(cmd + sum((i + 1) & 0xFF for i in range(cmd)) - 1) & 0xFF],
    }
    return out


class Timeout(Exception):
    pass


def _alarm(*_):
    raise Timeout()


def accepts(d, f):
    """True when the decoder's parsePacket takes [f] as one whole valid packet."""
    sf = [b - 256 if b > 127 else b for b in f]
    buf = jvm.JArray(sf, "byte", list(range(len(sf))))
    off, ln, pl = jvm.JArray([0], "int"), jvm.JArray([len(f)], "int"), jvm.JArray([0], "int")
    d.vm.steps = 0
    try:
        r = d.vm.invoke(d.obj, "parsePacket", [buf, off, ln, pl])
    except jvm.Undecidable as x:
        return f"undecided: {x}"[:120]
    return (r in (1, True)) and off.items[0] == len(f)


def one(job):
    src, cls, car = job
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(TIME_LIMIT)
    res = {"class": cls}
    try:
        idx = jvm.Index(src)
        vm0 = R.CarVM(idx, {})
        d = probe.Decoder(idx, cls, R.describe(vm0, car["box"], car["series"], car["model"], car["year"], car["config"], car["code"]))
        regs = sorted(k for k in d.px.registered if isinstance(k, int)) or [0x55]
        ok, odd = [], {}
        for name in frames(0x55):
            # The decoder's own commands: a deframer may check them; the Simple (Audi) command is a length (≤ 32).
            tried = [c for c in regs if name != "simple-aa55-len" or 0 < c <= 32][:3] or [0x55]
            for c in tried:
                if name == "cyt-55-fixed" and c != 0x55:
                    continue
                a = accepts(d, frames(c)[name])
                if a is True:
                    ok.append(name)
                    break
                if isinstance(a, str):
                    odd[name] = a
        res["accepts"] = ok
        if odd:
            res["undecided"] = odd
    except Timeout:
        res["timeout"] = True
    except Exception as x:  # noqa: BLE001 (a decoder the interpreter cannot run is a result too)
        res["crash"] = f"{type(x).__name__}: {x}"[:200]
    finally:
        signal.alarm(0)
    return res


def main():
    src, rj, out = sys.argv[1:4]
    jobs = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    flt = sys.argv[5] if len(sys.argv) > 5 else ""
    first = {}
    for e in json.load(open(rj, encoding="utf-8")):
        p = e.get("protocol")
        if p and flt in p and p not in first:
            first[p] = {k: e[k] for k in ("box", "series", "model", "year", "config", "code")}
    work = [(src, c, car) for c, car in sorted(first.items())]
    results = {}
    with Pool(jobs, maxtasksperchild=8) as pool:
        for i, r in enumerate(pool.imap_unordered(one, work)):
            results[r["class"]] = r
            print(f"[{i + 1}/{len(work)}] {r['class'].rsplit('.', 1)[-1]}: {r.get('accepts', r.get('crash') or 'timeout')}", flush=True)
    json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
