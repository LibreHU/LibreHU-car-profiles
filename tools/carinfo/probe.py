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
        # Car Info's second way in (JancarRx.toDoWork): a decoder with isSupportHandlePacketV2() gets each message of a
        # command it registered (registerCanMsg(cmd, callback)) through handlePacket2(proxy, data, cmd, callback),
        # its own handlePacket being empty.
        self.v2 = False
        try:
            self.vm.steps = 0
            self.v2 = self.vm.invoke(self.obj, "isSupportHandlePacketV2", []) in (1, True)
        except Exception:
            pass

    def _build(self, layout, cmd, data):
        """getPacket with the command where this protocol takes it: as its first argument (most), as the first data
        byte (getPacket writes no command: Simple's 55 AA …), as the second argument, or written over the byte
        parseRegisterCmdId reads ("patch": the box's frames differ from the head unit's, as Simple Audi's)."""
        sc = cmd - 256 if cmd > 127 else cmd
        a, b, d = {"arg": (cmd, 0, list(data)), "data": (cmd, 0, [sc] + list(data)), "sub": (0, cmd, list(data)),
                   "patch": (cmd, 0, list(data))}[layout]
        self.vm.steps = 0
        f = self.vm.invoke(self.obj, "getPacket", [a, b, JArray(d, "byte", list(range(len(d))))])
        if layout == "patch" and isinstance(f, JArray):
            k = self._cmd_index(len(f.items))
            if k is not None and 0 <= k < len(f.items):
                items = list(f.items)
                items[k] = sc
                f = JArray(items, "byte", list(range(len(items))))
        return f

    def _cmd_index(self, n):
        """Which byte of a frame parseRegisterCmdId reads: asked with a frame whose bytes are their own index."""
        if getattr(self, "cmd_index", None) is None:
            got = self._cmd_of(JArray([i & 0x7F for i in range(n)], "byte", list(range(n))))
            self.cmd_index = got if isinstance(got, int) else -1
        return self.cmd_index if self.cmd_index >= 0 else None

    def _cmd_of(self, f):
        try:
            self.vm.steps = 0
            return self.vm.invoke(self.obj, "parseRegisterCmdId", [f, 0])
        except Exception:
            return None

    def frame(self, cmd, data):
        # The protocol's own parseRegisterCmdId says where the command must be: found once, then kept.
        if getattr(self, "layout", None) is None:
            first = None
            for layout in ("arg", "data", "sub", "patch"):
                try:
                    f = self._build(layout, cmd, data)
                except Undecidable:
                    continue
                if first is None:
                    first = (layout, f)
                got = self._cmd_of(f) if isinstance(f, JArray) else None
                if got is None or got == cmd:
                    self.layout = layout
                    return f
            self.layout = first[0] if first else "arg"
            return first[1] if first else self._build("arg", cmd, data)
        return self._build(self.layout, cmd, data)

    def handle(self, frame):
        self.px.sent.clear()
        self.vm.trace.clear()
        self.vm.reads.clear()
        self.vm.steps = 0
        callbacks = []
        if self.v2:
            cmd = self.vm.invoke(self.obj, "parseRegisterCmdId", [frame, 0])
            callbacks = [c for c in self.px.registered.get(cmd, []) if isinstance(c, JObject)]
            self.vm.steps = 0
            for cb in callbacks:
                self.vm.invoke(self.obj, "handlePacket2", [self.proxy, frame, cmd, cb])
        if not callbacks:
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
