"""Probes a Car Info decoder (a protocol class) on the listing: builds frames with the decoder's own getPacket, hands them
to handlePacket with a stand-in for the app's proxy, and records what the decoder reports (sendMsg2Proxy) and the fields
it writes. Nothing of the app is executed."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jvm import Index, VM, JObject, JArray, Undecidable, UNKNOWN
import resolve as R

PROXY = "stub.com.autoai.canbus.base.proxy.AProxy"


class Proxy:
    def __init__(self):
        self.sent = []       # (type, object)
        self.known = {}      # type → the last object reported with it (decoders keep and reuse them)
        self.registered = {}  # cmd → handler object
        self.out = []        # frames the decoder sends to the box


def natives(px):
    n = R.natives()
    def send(vm, t, a):
        px.sent.append((a[1], a[0]))
        if isinstance(a[0], JObject):
            px.known[(a[1], a[0].cls)] = a[0]
    n[(PROXY, "sendMsg2Proxy")] = send
    n[(PROXY, "registerCanMsg")] = lambda vm, t, a: px.registered.setdefault(a[0], []).append(a[1])
    for f in ("sendData2Can", "sendCanData", "sendData"):
        n[(PROXY, f)] = lambda vm, t, a: px.out.append(a[0])
    return n


class Decoder:
    def __init__(self, index, cls, describe=None):
        self.px = Proxy()
        self.vm = R.CarVM(index, natives(self.px))
        self.vm.current = describe or R.describe(self.vm, 1, 0, 0, 0, 0, 0)
        self.proxy = JObject(PROXY)
        self.cls = cls
        self.errors = []
        self.obj = JObject(cls)
        self.vm.clinit(cls)
        for step, fn in (("<init>", lambda: self.vm.invoke(self.obj, "<init>", [], cls)),
                         ("create", lambda: self.vm.invoke(self.obj, "create", [self.proxy]))):
            try:
                self.vm.steps = 0
                fn()
            except Undecidable as x:
                self.errors.append(f"{step}: {getattr(x, 'where', '?')}: {x}")

    def frame(self, cmd, data):
        self.vm.steps = 0
        f = self.vm.invoke(self.obj, "getPacket", [cmd, 0, JArray(list(data), "byte", list(range(len(data))))])
        return f

    def handle(self, frame):
        self.px.sent.clear()
        self.vm.trace.clear()
        self.vm.reads.clear()
        self.vm.steps = 0
        self.vm.invoke(self.obj, "handlePacket", [self.proxy, frame])
        # Everything ever reported, as it is now (a decoder may report a value only when it changes).
        return [(t, o) for (t, _), o in self.px.known.items()] + [x for x in self.px.sent if not isinstance(x[1], JObject)], list(self.vm.trace)


if __name__ == "__main__":
    src, cls, cmd = sys.argv[1], sys.argv[2], int(sys.argv[3], 0)
    data = bytes.fromhex(sys.argv[4]) if len(sys.argv) > 4 else bytes(8)
    d = Decoder(Index(src), cls)
    print("errors:", d.errors, "registered:", list(d.px.registered))
    f = d.frame(cmd, [b - 256 if b > 127 else b for b in data])
    print("frame:", f.items if isinstance(f, JArray) else f)
    try:
        sent, trace = d.handle(f)
    except Undecidable as x:
        print("undecided:", getattr(x, "where", "?"), x); sys.exit()
    for t, o in sent:
        print("sent", t, o, {k: v for k, v in (o.fields.items() if isinstance(o, JObject) else [])})
    for o, k, v in trace:
        print("  write", o, k, v)
