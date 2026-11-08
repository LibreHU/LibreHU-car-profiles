"""Generates LibreHU car profiles (format 2) from the probe of Car Info's decoders (batch.py output) and its catalogue
(resolve.py output): one profile per decoder, its cars as variants (with the car type its box needs, replayed by
jvm.py when the listing is given), the values it reports mapped to LibreHU roles, its steering wheel keys with their
names. Nothing of the app is run. Every profile says it was generated and never tried on a car.

    python3 -I generate.py <probe dir> <resolve.json> <out dir> [--src <jadx fallback dir>] [--brands <brands dir>]

The box type comes from the decoder's own frames (Hiworld 5A A5 / AA 55, Raise 2E, Raise FD with an 8- or 16-bit
sum); a decoder with another framing is left out (report.json says which): its box type is to be described first
(boxes/). Decoders of the hand-made profiles (brands/) are left out too. Probe output that looks like noise (the same
fields on every command, absurd factors) is dropped. Writes <out dir>/<make>/<id>.json and <out dir>-report.json.
"""
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ENGINE = ">=2.0"
APP = "Car Info 1.0.3991 (com.can.activity)"

# --- Box types, from the decoder's frame for command 0x55 and data 01 02 03 (batch.py "frame_example") ---------------


def box_type(f):
    """The LibreHU box type of a frame built by the decoder (checked with its checksum), or None."""
    if not f or any(b is None for b in f):
        return None
    d = [1, 2, 3]
    if f[:2] == [0x5A, 0xA5] and len(f) == 8 and f[2] == 3 and f[3] == 0x55 and f[4:7] == d:
        return "hiworld" if f[7] == (((3 + 0x55 + 6) & 0xFF) - 1) & 0xFF else None
    if f[:2] == [0xAA, 0x55] and len(f) == 8 and f[2] == 3 and f[3] == 0x55 and f[4:7] == d:
        return "hiworld-aa55" if f[7] == (((3 + 0x55 + 6) & 0xFF) - 1) & 0xFF else None
    if f[0] == 0x2E and len(f) == 7 and f[1] == 0x55 and f[2] == 3 and f[3:6] == d:
        return "raise" if f[6] == ((0x55 + 3 + 6) ^ 0xFF) & 0xFF else None
    if f[0] == 0xFD and len(f) == 7 and f[1] == 6 and f[2] == 0x55 and f[3:6] == d:
        return "raise-fd" if f[6] == (6 + 0x55 + 6) & 0xFF else None
    if f[0] == 0xFD and len(f) == 8 and f[1] == 7 and f[2] == 0x55 and f[3:6] == d:
        s = 7 + 0x55 + 6
        return "raise-fd2" if f[6:8] == [(s >> 8) & 0xFF, s & 0xFF] else None
    return None


def unframe(box, f):
    """(cmd, data) of a frame of [box], or None."""
    f = [b & 0xFF for b in f]
    if box in ("hiworld", "hiworld-aa55") and len(f) >= 5:
        n = f[2]
        return (f[3], f[4:4 + n]) if len(f) >= 5 + n else None
    if box == "raise" and len(f) >= 4:
        n = f[2]
        return (f[1], f[3:3 + n]) if len(f) >= 4 + n else None
    if box in ("raise-fd", "raise-fd2") and len(f) >= 4:
        n = f[1] - (3 if box == "raise-fd" else 4)
        return (f[2], f[3:3 + n]) if n >= 0 and len(f) >= 3 + n else None
    return None


# --- Car Info's values → LibreHU roles (CanRoles) -------------------------------------------------------------------

ROLES = {
    "DDef$BaseInfo.mLeftFrontDoor": "door.front_left", "DDef$BaseInfo.mRightFrontDoor": "door.front_right",
    "DDef$BaseInfo.mLeftBackDoor": "door.rear_left", "DDef$BaseInfo.mRightBackDoor": "door.rear_right",
    "DDef$BaseInfo.mTailBoxDoor": "door.trunk", "DDef$BaseInfo.mFrontBoxDoor": "door.hood",
    "DDef$BaseInfo.mBackCarState": "gear.reverse", "DDef$BaseInfo.mREV": "gear.reverse", "DDef$BaseInfo.mPark": "gear.park",
    "DDef$BaseInfo.mPStopBlockState": "handbrake", "DDef$BaseInfo.mACC": "ignition.acc", "DDef$BaseInfo.mIG": "ignition.on",
    "DDef$BaseInfo.mILLLight": "lights.parking", "DDef$BaseInfo.mLeftSafetyBelt": "seatbelt.driver",
    "DDef$BaseInfo.mSafetyBelt": "seatbelt.driver", "DDef$BaseInfo.mSpeed": "vehicle.speed", "DDef$BaseInfo.mEngineSpeed": "engine.rpm",
    "DDef$MiscInfo.speed": "vehicle.speed", "DDef$MiscInfo.ambientTemp": "outside.temp", "DDef$MiscInfo.rotationRate": "engine.rpm",
    "DDef$MiscInfo.cruisingRange": "fuel.range", "DDef$MiscInfo.instFuelCont": "fuel.instant", "DDef$MiscInfo.avgFuelCont": "fuel.average",
    "DDef$MiscInfo.odo": "vehicle.odometer", "DDef$MiscInfo.coolantTemp": "engine.coolant_temp", "DDef$MiscInfo.engineOilTemp": "engine.oil_temp",
    "DDef$MiscInfo.fuelPercentage": "fuel.level", "DDef$MiscInfo.throttlePos": "engine.throttle",
    "DDef$MiscInfo.mLeftFrontDoor": "door.front_left", "DDef$MiscInfo.mRightFrontDoor": "door.front_right",
    "DDef$MiscInfo.mLeftBackDoor": "door.rear_left", "DDef$MiscInfo.mRightBackDoor": "door.rear_right", "DDef$MiscInfo.mTailBoxDoor": "door.trunk",
    "DDef$MiscInfo.mLeftSafetyBelt": "seatbelt.driver",
    "DDef$CarInfo.mCurrentSpeed": "vehicle.speed", "DDef$CarInfo.mRotationlSpeed": "engine.rpm", "DDef$CarInfo.mTotalMileage": "vehicle.odometer",
    "DDef$CarInfo.mLeftFrontDoor": "door.front_left", "DDef$CarInfo.mRightFrontDoor": "door.front_right",
    "DDef$CarInfo.mLeftBackDoor": "door.rear_left", "DDef$CarInfo.mRightBackDoor": "door.rear_right",
    "DDef$CarInfo.mTailBoxDoor": "door.trunk", "DDef$CarInfo.mHoodBoxDoor": "door.hood", "DDef$CarInfo.mHandbrake": "handbrake",
    "DDef$CarInfo.mLeftTurnLight": "turn.left", "DDef$CarInfo.mRightTurnLight": "turn.right", "DDef$CarInfo.mFCoolantTemp": "engine.coolant_temp",
    "DDef$CarInfo.miOilTemp": "engine.oil_temp", "DDef$CarInfo.mBatteryVoltage": "battery.voltage", "DDef$CarInfo.mfVoltage": "battery.voltage",
    "DDef$CarInfo.mSafetyBelt": "seatbelt.driver",
    "HvacInfo.outsideTemp": "outside.temp", "HvacInfo.acOnOff": "hvac.ac", "HvacInfo.airOnOff": "hvac.power",
    "HvacInfo.airRecircOnOff": "hvac.recirculation", "HvacInfo.frontDefrostOnOff": "hvac.defrost_front",
    "HvacInfo.rearDefrostOnOff": "hvac.defrost_rear", "HvacInfo.dualOnOff": "hvac.dual", "HvacInfo.autoLight1": "hvac.auto",
    "HvacInfo.frontLeftTemp": "hvac.temp_left", "HvacInfo.frontRightTemp": "hvac.temp_right", "HvacInfo.frontWindLevel": "hvac.fan",
    "HvacInfo.flSeatWarmerLevel": "hvac.seat_heat_left", "HvacInfo.frSeatWarmerLevel": "hvac.seat_heat_right",
    "DDef$OutTemputerInfo.mOutCTemp": "outside.temp",
    "SteerWheelInfo.eps": "steering.angle",
    "LightInfo.leftDirectionIndicator": "turn.left", "LightInfo.rightDirectionIndicator": "turn.right",
    "DDef$VerInfo.mVersion": "box.version",
}
for pos, car in (("front_left", "frontLeft"), ("front_right", "frontRight"), ("rear_left", "rearLeft"), ("rear_right", "rearRight")):
    ROLES[f"TpmsInfo.{car}TirePreValue"] = f"tpms.{pos}.pressure"
    ROLES[f"TpmsInfo.{car}TireTempValue"] = f"tpms.{pos}.temperature"
ROLES["RadarInfo.radarShowOnOff"] = "radar.shown"

# Kept with their label only: Car Info's radar gives a distance step (0..max), LibreHU's radar roles a proximity in %.
LABEL_ONLY = {f"RadarInfo.{z}{c}Distance" for z in ("front", "rear") for c in ("Left", "LeftMid", "RightMid", "Right")} | \
    {f"RadarInfo.{z}{c}Distance" for z in ("left", "right") for c in ("Front", "FrontMid", "RearMid", "Rear")}

UNITS = {"vehicle.speed": "km/h", "engine.rpm": "rpm", "outside.temp": "°C", "engine.coolant_temp": "°C", "engine.oil_temp": "°C",
         "fuel.range": "km", "vehicle.odometer": "km", "fuel.instant": "L/100 km", "fuel.average": "L/100 km", "fuel.level": "%",
         "engine.throttle": "%", "battery.voltage": "V", "steering.angle": "°", "hvac.temp_left": "°C", "hvac.temp_right": "°C"}

# Car Info's key names (mstrKeyCode) → the names LibreHU's profiles use (TWRP and the service read them).
KEYS = {
    "Volume_add": "volume +", "Volume_del": "volume -", "Volume_mute": "mute", "Media_next": "next", "Media_pre": "previous",
    "Src_mode": "mode", "Speech": "voice", "Phone_dial": "answer", "Phone_hang": "hang up", "Up": "up", "Down": "down",
    "Left": "left", "Right": "right", "Src_home": "home", "Src_navi": "navigation", "Power": "power", "Back": "back",
    "Enter": "enter", "Ok": "ok", "Media_play": "play / pause", "Media_pause": "play / pause", "Menu": "menu",
    "Src_radio": "radio", "Src_music": "music", "Src_phone": "phone", "Src_setting": "settings", "Src_bt": "bluetooth",
}

# Car Info's file names (one per series) → the make. The Chinese makes are named from the protocol documents Car Info lists
# for them (« 东风风神 » for dffs…).
MAKES = {"citroen": "Citroën", "benz": "Mercedes-Benz", "vw": "Volkswagen", "volkswagen": "Volkswagen", "bmw": "BMW", "gmc": "GMC",
         "ds": "DS", "mg": "MG", "byd": "BYD", "baic": "BAIC", "jac": "JAC", "faw": "FAW", "gac": "GAC", "saic": "SAIC",
         "alfa": "Alfa Romeo", "landrover": "Land Rover", "mini": "MINI", "ssangyong": "SsangYong", "kia": "Kia",
         "amico": "AMICO", "bba": "BMW, Mercedes-Benz, Audi", "bj": "BAIC", "bjev": "BAIC BJEV", "cnhtc": "Sinotruk",
         "dffd": "Dongfeng Fengdu", "dffg": "Dongfeng Fengguang", "dffs": "Dongfeng Aeolus", "dffx": "Dongfeng Forthing",
         "dftl": "Dongfeng Tianlong", "gio": "GAC Trumpchi", "gpatton": "George Patton", "greatwall": "Great Wall",
         "hezhong": "Neta", "hongyan": "SAIC Hongyan", "ikco": "IKCO", "jiefang": "FAW Jiefang", "jmc": "JMC",
         "kinglong": "King Long", "knowbeans": "Zhidou", "leepmotor": "Leapmotor", "maple": "Maple", "nlmmotor": "New Longma",
         "oushang": "Changan Oshan", "phantom": "BAIC Huansu", "racing": "Ruichi", "saipa": "SAIPA", "samsung": "Renault Samsung",
         "senova": "BAIC Senova", "southeast": "Soueast", "swm": "SWM", "trumpchi": "GAC Trumpchi", "uaz": "UAZ",
         "vinfast": "VinFast", "weiwang": "BAIC Weiwang", "weltmeister": "WM Motor", "zhonghua": "Brilliance"}

# The folder of brands/ (one pack per folder) when LibreHU groups the makes.
FOLDERS = {"hyundai": "hyundai-kia", "kia": "hyundai-kia", "peugeot": "psa", "citroen": "psa", "ds": "psa", "vw": "volkswagen",
           "skoda": "volkswagen", "seat": "volkswagen"}

# Not cars: Car Info's rear seat screens, site machines and scooters.
NOT_CARS = {"other", "reardisplay", "klyde", "default"}


def make_of(xml):
    k = xml.rsplit(".", 1)[0].lower()
    if k.endswith("ver") and k != "landrover":  # the second file of a make (« nissanver.xml »)
        k = k[:-3]
    k = {"ssongyong": "ssangyong"}.get(k, k)
    return k, MAKES.get(k, k[:1].upper() + k[1:])


def trim(name):
    n = (name or "").strip()
    t = {"cfg_all": "all trims", "cfg_high": "high trim", "cfg_low": "low trim", "cfg_medium": "medium trim",
         "cfg_medium_low": "medium-low trim", "cfg_medium_high": "medium-high trim", "兼容": "all trims"}
    return t.get(n.lower(), t.get(n, n.replace("_", " ")))


def variant_name(row):
    k, make = make_of(row["xml"])
    model = (row.get("modelName") or "").replace("_", " ").strip()
    if k == "bba":  # one box for the three German makes: NTG (Mercedes-Benz), A4L / Q3 (Audi), CCC / CIC / NBT / EVO (BMW)
        make = "Mercedes-Benz" if model.lower().startswith("ntg") else "Audi" if model.lower().startswith("a") else "BMW"
    year = (row.get("yearName") or "").replace("_", "-").strip()
    return re.sub(r"\s+", " ", f"{make} {model} {year}, {trim(row.get('configName'))}").strip(" ,")


# --- One message of the probe → LibreHU signals ---------------------------------------------------------------------


def noisy(spec):
    f = spec.get("factor", 1.0)
    return f != 0 and abs(f) < 1e-3


def signal_of(role, spec, label):
    """A LibreHU signal from a probe spec, or None when the engine cannot read it the same way."""
    s = {"start_byte": int(spec.get("start_byte", 0))}
    kind = spec.get("kind")
    if kind == "complex":
        return None
    if kind == "flag" or (kind == "table" and set(map(str, spec.get("values", {}).values())) <= {"0", "1", "True", "False"} and "bit" in spec):
        bit = int(spec.get("bit", 0))
        if bit not in range(8):
            return None
        s["bits"] = {label: ({"bit": bit, "role": role} if role else bit)}
        return s
    if kind == "table":
        vals = {str(k): v for k, v in spec.get("values", {}).items()}
        if not vals or len(vals) > 64:
            return None
        if "mask" in spec and spec["mask"] not in (255,):
            s["mask"] = "0x%X" % int(spec["mask"])
        nums = [v for v in vals.values() if isinstance(v, (int, float))]
        if len(nums) == len(vals):
            # Numbers by raw value: kept when they are the raw value (a plain byte), else as labels.
            if all(float(v) == float(k) for k, v in vals.items()):
                if role:
                    s["role"] = role
                s["label"] = label
                return s
        s["values"] = {k: str(v) for k, v in vals.items()}
        s["label"] = label
        return s
    size = int(spec.get("size", 1))
    if size not in range(1, 9):
        return None
    if size > 1:
        s["size"] = size
        if spec.get("endian") == "little":
            s["endian"] = "little"
    bl = spec.get("bit_length")
    if bl and bl != size * 8:
        s["start_bit"] = int(spec.get("bit", 0))
        s["bit_length"] = int(bl)
    if noisy(spec):
        return None
    if spec.get("factor", 1.0) != 1.0:
        s["factor"] = round(float(spec["factor"]), 6)
    if spec.get("offset", 0.0):
        s["offset"] = round(float(spec["offset"]), 4)
    if spec.get("signed"):
        s["signed"] = True
    if spec.get("sign_magnitude"):
        s["sign_magnitude"] = True
    if "max_raw" in spec:
        s["max_value"] = spec["max_raw"]
    if role:
        s["role"] = role
        if UNITS.get(role):
            s["unit"] = UNITS[role]
    s["label"] = label
    return s


def wheel_keys(cmd, m):
    code = next((v for k, v in m.items() if k.endswith("WheelKeyInfo.mKeyCode")), None)
    if not code or code.get("kind") == "complex":
        return None
    wk = {"cmd": "0x%02X" % cmd, "code_byte": int(code.get("start_byte", 0))}
    st = next((v for k, v in m.items() if k.endswith("WheelKeyInfo.mKeyStatus")), None)
    if st and st.get("kind") == "table" and int(st.get("start_byte", -1)) != wk["code_byte"]:
        pressed = sorted(int(k) for k, v in st.get("values", {}).items() if v in (1, True, "1"))
        if pressed and len(pressed) < 255:
            wk["state_byte"] = int(st["start_byte"])
            wk["pressed"] = pressed[:8]
    names = next((v for k, v in m.items() if k.endswith("WheelKeyInfo.mstrKeyCode")), None)
    out, prev = {}, None
    if names and names.get("kind") == "table":
        for k in sorted(names.get("values", {}), key=int):
            v = names["values"][k]
            # A code the decoder does not know keeps the name of the one before: only the first of each run.
            if isinstance(v, str) and v != prev and int(k) > 0:
                out[str(int(k))] = KEYS.get(v, v.replace("_", " ").lower())
            prev = v
    if out:
        wk["names"] = out
    return wk


def label_of(field):
    f = re.sub(r"^m(by|b|i|f|str)?(?=[A-Z])", "", field)
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", f).lower()


def cmd_of(key):
    """A command of the probe ("0x38"; a Java byte the decoder registered signed: "0x-10" = 0xF0)."""
    return int(key.replace("0x-", "-0x"), 16) & 0xFF


def messages_of(probe):
    msgs, keys, used = {}, None, collections.Counter()
    raw = {k: v for k, v in (probe.get("messages") or {}).items() if isinstance(v, dict) and "undecided" not in v}
    # Noise: the same fields on most commands (a decoder the probe does not understand, as Mazda's).
    sets = collections.Counter(tuple(sorted(v)) for v in raw.values())
    if raw and sets.most_common(1)[0][1] > 32:
        return {}, None
    for key, m in sorted(raw.items(), key=lambda kv: cmd_of(kv[0])):
        cmd = cmd_of(key)
        if keys is None:
            keys = wheel_keys(cmd, m)
        signals = {}
        for fk, spec in m.items():
            if not isinstance(spec, dict):
                continue
            field = fk.split(":", 1)[-1]
            role = ROLES.get(field)
            if role is None and field not in LABEL_ONLY:
                continue
            key = role or field
            if used[(cmd, key)]:
                continue
            name = re.sub(r"[^a-z0-9_]", "_", (role or label_of(field.split(".", 1)[-1])).replace(".", "_").replace(" ", "_"))
            sig = signal_of(role, spec, label_of(field.split(".", 1)[-1]))
            if sig is None:
                continue
            used[(cmd, key)] += 1
            signals[name] = sig
        if signals:
            msgs["0x%02X" % cmd] = {"name": "Message 0x%02X" % cmd, "signals": signals}
    return msgs, keys


# --- Examples: a frame per message and what the engine must read in it ---------------------------------------------


def example_of(cmd, msg):
    for name, s in msg["signals"].items():
        if "bits" in s:
            label, b = next(iter(s["bits"].items()))
            bit = b["bit"] if isinstance(b, dict) else b
            data = [0] * (s["start_byte"] + 1)
            data[s["start_byte"]] = 1 << bit
            return {"cmd": cmd, "data": " ".join("%02X" % x for x in data), "expect": {label: True}}
        if "values" in s and "mask" not in s and "start_bit" not in s and s.get("size", 1) == 1:
            # A table: one of its raw values and the label the engine gives.
            k, v = next(iter(s["values"].items()))
            raw = int(k)
            if raw not in range(256):
                continue
            data = [0] * (s["start_byte"] + 1)
            data[s["start_byte"]] = raw
            return {"cmd": cmd, "data": " ".join("%02X" % x for x in data), "expect": {name: str(v)}}
        if "start_bit" in s and "values" not in s and "mask" not in s:
            # A bit field: its lowest bit set, the rest 0.
            size = s.get("size", 1)
            raw = 1 << s["start_bit"]
            data = [0] * (s["start_byte"] + size)
            bs = raw.to_bytes(size, "little" if s.get("endian") == "little" else "big")
            data[s["start_byte"]:s["start_byte"] + size] = list(bs)
            v = 1 * s.get("factor", 1.0) + s.get("offset", 0.0)
            if s.get("signed") and s["bit_length"] == 1:
                continue
            return {"cmd": cmd, "data": " ".join("%02X" % x for x in data), "expect": {name: round(v, 2)}}
        if "values" in s or "start_bit" in s or "mask" in s:
            continue
        size = s.get("size", 1)
        raw = 0x12 if size == 1 else 0x0123
        data = [0] * (s["start_byte"] + size)
        bs = raw.to_bytes(size, "little" if s.get("endian") == "little" else "big")
        data[s["start_byte"]:s["start_byte"] + size] = list(bs)
        v = raw * s.get("factor", 1.0) + s.get("offset", 0.0)
        if s.get("max_value") is not None and raw > s["max_value"]:
            continue
        return {"cmd": cmd, "data": " ".join("%02X" % x for x in data), "expect": {name: round(v, 2)}}
    return None


# --- Car types, replayed by jvm.py (buildCarTypePacket of the decoder, for each car) -------------------------------


def car_types(src, cls, rows, box):
    """car name → data of the car type message, and that message's command and interval; ({}, None, None) without."""
    if not src:
        return {}, None, None
    import jvm
    import probe
    import resolve as R

    idx = INDEX.get(src) or INDEX.setdefault(src, jvm.Index(src))
    out, cmds, every = {}, collections.Counter(), None
    d = None
    for row in rows:
        try:
            # One decoder for its cars: the car is read from the head unit's description at each call.
            if d is None:
                vm0 = R.CarVM(idx, {})
                d = probe.Decoder(idx, cls, R.describe(vm0, row["box"], row["series"], row["model"], row["year"], row["config"], row["code"]))
            d.vm.current = R.describe(d.vm, row["box"], row["series"], row["model"], row["year"], row["config"], row["code"])
            d.vm.steps = 0
            f = d.vm.invoke(d.obj, "buildCarTypePacket", [])
            if every is None:
                try:
                    d.vm.steps = 0
                    every = d.vm.invoke(d.obj, "getCarTypeIntervalTime", [])
                except Exception:
                    every = 0
        except Exception:
            continue
        if not isinstance(f, jvm.JArray):
            continue
        u = unframe(box, [x if isinstance(x, int) else 0 for x in f.items])
        if not u:
            continue
        cmds[u[0]] += 1
        out[variant_name(row)] = (u[0], u[1])
    if not cmds:
        return {}, None, None
    cmd = cmds.most_common(1)[0][0]
    return {k: d for k, (c, d) in out.items() if c == cmd}, cmd, every if isinstance(every, int) and every > 0 else None


INDEX = {}


# --- Main -----------------------------------------------------------------------------------------------------------


def hand_made(brands):
    """Decoder classes the hand-made profiles already cover (named in their descriptions)."""
    out = {"HdRenaultProtocolLNP002"}
    if brands and os.path.isdir(brands):
        for root, _, files in os.walk(brands):
            for f in files:
                if f.endswith(".json"):
                    t = json.load(open(os.path.join(root, f), encoding="utf-8")).get("description", "")
                    out.update(re.findall(r"\b([A-Z][A-Za-z0-9]*Protocol[A-Za-z0-9_]*)\b", t))
    return out


def main():
    a = sys.argv[1:]
    probe_dir, resolve_json, out_dir = a[0], a[1], a[2]
    src = a[a.index("--src") + 1] if "--src" in a else None
    brands = a[a.index("--brands") + 1] if "--brands" in a else None
    rows = [r for r in json.load(open(resolve_json, encoding="utf-8")) if r.get("protocol")]
    by_cls = collections.defaultdict(list)
    for r in rows:
        by_cls[r["protocol"]].append(r)
    skip = hand_made(brands)
    report = collections.defaultdict(list)
    made = 0
    cars = 0
    for f in sorted(os.listdir(probe_dir)):
        if not f.endswith(".json"):
            continue
        p = json.load(open(os.path.join(probe_dir, f), encoding="utf-8"))
        cls = p["class"]
        short = cls.rsplit(".", 1)[-1]
        if short in skip:
            report["hand-made profile"].append(short)
            continue
        box = box_type(p.get("frame_example"))
        if box is None:
            report["framing without a LibreHU box type"].append(short)
            continue
        msgs, keys = messages_of(p)
        if not msgs and not keys:
            report["nothing LibreHU reads"].append(short)
            continue
        crow = by_cls.get(cls, [])
        if not crow:
            report["no car in the catalogue"].append(short)
            continue
        mk = collections.Counter(make_of(r["xml"])[0] for r in crow).most_common(1)[0][0]
        if mk in NOT_CARS:
            report["not a car"].append(short)
            continue
        pid = re.sub(r"[^a-z0-9-]", "", f"{mk}-{short.lower().replace('protocol', '').strip('_')}")[:60]
        bauds = collections.Counter(r.get("baudrate") for r in crow if r.get("baudrate") in (9600, 19200, 38400, 57600, 115200))
        baud = bauds.most_common(1)[0][0] if bauds else 38400
        types, tcmd, every = car_types(src, cls, crow, box)
        link = {"ack": box in ("hiworld", "raise"), "send": []}
        if box in ("raise", "raise-fd"):
            link["send"].append({"name": "connect", "cmd": "0x81", "data": "01", "first_ms": 500, "every_ms": 0})
        if tcmd is not None and types:
            link["send"].append({"name": "car type", "cmd": "0x%02X" % tcmd, "data": "", "first_ms": 1000,
                                 "every_ms": int(every) if every and every >= 500 else (30000 if box == "hiworld" else 1000)})
        names = sorted({variant_name(r) for r in crow})
        variants = []
        for n in names:
            v = {"name": n}
            if n in types:
                v["send"] = {"car type": " ".join("%02X" % x for x in types[n])}
            variants.append(v)
        profile = {
            "format": "librehu-can-vehicle", "version": 2, "engine": ENGINE, "id": pid,
            "name": f"{make_of(crow[0]['xml'])[1]} ({short})",
            "description": f"Generated by LibreHU-car-profiles tools/carinfo from the decoder {short} of {APP}, replayed without "
                           f"running the app. NEVER TRIED ON A CAR: check every value before relying on it. Box: {box}.",
            "box": box, "baud": baud, "link": link, "variants": variants, "messages": msgs,
        }
        if keys:
            profile["wheel_keys"] = keys
            # The key message as a value too (the CAN tab shows it, the example checks it), as the hand-made PSA profile.
            ws = {"start_byte": keys["code_byte"], "label": "wheel key"}
            if keys.get("names"):
                ws["values"] = keys["names"]
            msgs.setdefault(keys["cmd"], {"name": "Wheel key", "signals": {}})["signals"].setdefault("wheel_key", ws)
        ex = [e for e in (example_of(k, m) for k, m in msgs.items()) if e][:4]
        if not ex:
            report["no example possible"].append(short)
            continue
        profile["examples"] = ex
        d = os.path.join(out_dir, FOLDERS.get(mk, mk))
        os.makedirs(d, exist_ok=True)
        json.dump(profile, open(os.path.join(d, pid + ".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        made += 1
        cars += len(variants)
        report["generated"].append(f"{FOLDERS.get(mk, mk)}/{pid} ({len(variants)} cars, {len(msgs)} messages{', keys' if keys else ''}{', car types' if types else ''})")
    rep = {k: v for k, v in report.items()}
    rep["summary"] = {"profiles": made, "cars": cars}
    # Next to the profiles' folder, not in it (the car tool checks every .json below it).
    json.dump(rep, open(out_dir.rstrip("/") + "-report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{made} profiles, {cars} cars")
    for k, v in report.items():
        print(f"  {k}: {len(v)}")


if __name__ == "__main__":
    main()
