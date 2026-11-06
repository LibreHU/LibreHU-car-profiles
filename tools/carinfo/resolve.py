"""Which decoder Car Info picks for each car of its catalogue: replays tool.ProtocolUtils.getProtocolBean(CanDescribe)
on the listing (jadx fallback) for every Series / Model / ModelYear / Config / CanBox of assets/protocol/*.xml.
Usage: python3 -I resolve.py <jadx-fallback-dir> <assets/protocol dir> <out.json>"""
import json, os, sys, xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jvm import Index, VM, JObject, Undecidable, UNKNOWN

DESC = "com.autoai.canbus.base.bean.CanDescribe"
UTILS = "com.autoai.canbus.tool.ProtocolUtils"


def natives():
    nothing = lambda vm, this, args: None
    zero = lambda vm, this, args: 0
    singletons = {}

    def single(name):
        def get(vm, this, args):
            if name not in singletons:
                singletons[name] = JObject("stub." + name)
            return singletons[name]
        return get

    def create(vm, this, args):
        name = args[0]
        if not isinstance(name, str) or vm.index.get(name) is None:
            return None
        return vm.new(name)

    n = {
        ("com.autoai.canbus.base.utils.ReflectionUtils", "createInstance"): create,
        ("java.lang.System", "exit"): nothing,
        ("android.os.SystemProperties", "get"): lambda vm, t, a: a[1] if len(a) > 1 else "",
        ("android.os.SystemProperties", "getInt"): lambda vm, t, a: a[1] if len(a) > 1 else 0,
    }
    for logger in ("com.autoai.canbus.base.utils.JLog", "android.util.Log", "com.jancar.sdk.utils.Logcat"):
        for f in ("d", "e", "i", "w", "v"):
            n[(logger, f)] = nothing
    n[("com.autoai.canbus.base.platform.XxxPlatform", "getInstance")] = single("com.autoai.canbus.base.platform.XxxPlatform")
    n[("stub.com.autoai.canbus.base.platform.XxxPlatform", "getCanDescribe")] = lambda vm, t, a: vm.current

    def bean(vm, this, args):
        """The platform keeps the ProtocolBean that ProtocolUtils.getProtocolBean chose for the car (its feature
        bits say, for example, whether the car has a panoramic camera)."""
        d = args[0] if args else vm.current
        beans = vm.__dict__.setdefault("beans", {})
        if id(d) not in beans:
            beans[id(d)] = UNKNOWN  # a nested call while it is being made
            steps = vm.steps
            try:
                beans[id(d)] = vm.run(vm.find(UTILS, "getProtocolBean", 1), None, [d])
            except Undecidable:
                pass
            vm.steps = steps
        return beans[id(d)]
    n[("stub.com.autoai.canbus.base.platform.XxxPlatform", "getProtocolBean")] = bean
    for s in ("com.autoai.canbus.base.jancartools.HandlerMainServer",
              "com.autoai.canbus.base.protocol.manager.JancarGlobalDataManager"):
        n[(s, "get")] = single(s)
    return n


class CarVM(VM):
    def outside(self, cls, name, this, args):
        r = super().outside(cls, name, this, args)
        # A singleton of the head unit (settings, radar…): 0 / "" (stock settings).
        if r is UNKNOWN and isinstance(this, JObject) and this.cls.startswith("stub."):
            return 0
        if r is UNKNOWN and name in ("append",):
            return this
        if r is UNKNOWN and name == "toString":
            return ""
        if r is UNKNOWN and name in ("equals",) and isinstance(this, str):
            return 1 if this == args[0] else 0
        return r


def describe(vm, box, series, model, year, config, code):
    d = JObject(DESC)
    d.fields.update(boxID=box, seriesID=series, modelID=model, modelYearID=year, configID=config, carCode=code)
    return d


def resolve(vm, d):
    vm.current = d
    m = vm.find(UTILS, "getProtocolBean", 1)
    vm.steps = 0
    bean = vm.run(m, None, [d])
    if not isinstance(bean, JObject):
        return None
    f = bean.fields
    return {k: f.get(k) for k in ("protocol", "baudrate", "file", "protocolTty3") if f.get(k) not in (None, UNKNOWN, 0, "")}


def box_id(xml_id):
    """The catalogue numbers the boxes 1, 2, 3…; the app's CanDescribe.boxID is (n - 1) * 3 + 1 (ProtocolFragment)."""
    return (xml_id - 1) * 3 + 1 if xml_id > 0 else 0


def _hex(t):
    try:
        return int(t, 16)  # the car code is read in hexadecimal (ProtocolFragment)
    except ValueError:
        return 0


def catalogue(folder):
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".xml"):
            continue
        root = ET.parse(os.path.join(folder, name)).getroot()
        if root.tag != "Series":
            continue
        sid = int(root.get("id"))
        for mo in root.findall("Model"):
            for y in mo.findall("ModelYear"):
                for c in y.findall("Config"):
                    for b in c.findall("CanBox"):
                        code = (b.text or "0").strip()
                        yield {
                            "xml": name, "series": sid, "seriesName": root.get("name"),
                            "model": int(mo.get("id")), "modelName": mo.get("name") or mo.get("description"),
                            "year": int(y.get("id")), "yearName": y.get("name") or y.get("description"),
                            "config": int(c.get("id")), "configName": c.get("name") or c.get("description"),
                            "box": box_id(int(b.get("id"))), "boxName": b.get("name"), "baud": b.get("baudrate"),
                            "doc": b.get("file"), "code": _hex(code),
                        }


def main():
    src, xmls, out = sys.argv[1:4]
    vm = CarVM(Index(src), natives())
    rows, fails = [], {}
    for e in catalogue(xmls):
        vm.statics = {}  # every car from a fresh start (managers keep state in statics)
        try:
            r = resolve(vm, describe(vm, e["box"], e["series"], e["model"], e["year"], e["config"], e["code"]))
        except Undecidable as x:
            r = {"undecided": f"{getattr(x, 'where', '?')}: {x}"[:160]}
        except Exception as x:  # a bug of this interpreter: keep going, report it
            r = {"error": f"{type(x).__name__}: {x}"[:160]}
        e.update(r or {})
        rows.append(e)
        k = r.get("undecided") or r.get("error") if r else None
        if k:
            fails[k] = fails.get(k, 0) + 1
    json.dump(rows, open(out, "w"), ensure_ascii=False, indent=0)
    ok = sum(1 for r in rows if r.get("protocol"))
    print(f"{len(rows)} catalogue entries, decoder found for {ok}")
    for k, v in sorted(fails.items(), key=lambda x: -x[1])[:25]:
        print(f"{v:6}  {k}")


if __name__ == "__main__":
    main()
