"""Probes every decoder Car Info picks (resolve.py output) and writes one JSON per decoder.
Usage: python3 -I batch.py <jadx-fallback-dir> <resolve.json> <out dir> [jobs] [class filter]"""
import json, os, signal, sys, time, traceback
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jvm, probe, infer, resolve as R

TIME_LIMIT = 900


class Timeout(Exception):
    pass


def _alarm(*_):
    raise Timeout()


def one(job):
    src, out, cls, car = job
    path = os.path.join(out, cls + ".json")
    if os.path.exists(path):
        return cls, "cached"
    t = time.time()
    res = {"class": cls, "car": car}
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(TIME_LIMIT)
    try:
        idx = jvm.Index(src)
        vm0 = R.CarVM(idx, {})
        d = probe.Decoder(idx, cls, R.describe(vm0, car["box"], car["series"], car["model"], car["year"], car["config"], car["code"]))
        res["errors"] = d.errors
        res["registered"] = sorted(k for k in d.px.registered if isinstance(k, int))
        cmds = res["registered"]
        if not cmds:
            # Nothing registered: which commands does handlePacket act on?
            cmds = []
            for c in range(256):
                try:
                    _, h = infer.run(d, c, bytes(infer.DATA_LEN))
                    _, h2 = infer.run(d, c, bytes([0xFF]) * infer.DATA_LEN)
                except jvm.Undecidable:
                    continue
                if h or h2:
                    cmds.append(c)
            res["handled"] = cmds
        f = d.frame(0x55, [1, 2, 3])
        res["frame_example"] = [x & 0xFF if isinstance(x, int) else None for x in f.items] if isinstance(f, jvm.JArray) else None
        msgs = {}
        for c in cmds:
            try:
                m = infer.message(d, c, __import__("random").Random(c))
            except jvm.Undecidable as x:
                msgs[f"0x{c:02X}"] = {"undecided": f"{getattr(x, 'where', '?')}: {x}"[:200]}
                continue
            if m:
                msgs[f"0x{c:02X}"] = {k: v for k, v in m.items()}
        res["messages"] = msgs
    except Timeout:
        res["timeout"] = True
    except Exception as x:
        res["crash"] = f"{type(x).__name__}: {x}"[:300]
        res["trace"] = traceback.format_exc()[-1500:]
    finally:
        signal.alarm(0)
    res["seconds"] = round(time.time() - t, 1)
    json.dump(res, open(path, "w"), ensure_ascii=False, indent=0, default=str)
    return cls, res.get("crash") or ("timeout" if res.get("timeout") else f"{len(res.get('messages', {}))} msgs {res['seconds']}s")


def main():
    src, rj, out = sys.argv[1:4]
    jobs = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    flt = sys.argv[5] if len(sys.argv) > 5 else ""
    os.makedirs(out, exist_ok=True)
    rows = json.load(open(rj))
    first = {}
    for e in rows:
        p = e.get("protocol")
        if p and flt in p and p not in first:
            first[p] = {k: e[k] for k in ("box", "series", "model", "year", "config", "code")}
    work = [(src, out, c, car) for c, car in sorted(first.items())]
    print(len(work), "decoders", flush=True)
    with Pool(jobs, maxtasksperchild=4) as pool:
        for i, (cls, st) in enumerate(pool.imap_unordered(one, work)):
            print(f"[{i + 1}/{len(work)}] {cls.rsplit('.', 1)[-1]}: {st}", flush=True)


if __name__ == "__main__":
    main()
