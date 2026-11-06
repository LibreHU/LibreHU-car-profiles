# Car Info → LibreHU (work in progress)

Reads a **jadx "fallback" listing** of the stock Car Info app (never runs the app) and replays its code in a small
interpreter, to learn what each decoder does and write LibreHU profiles from it. No content of the app is in this repo:
bring your own APK and decompile it yourself.

```bash
jadx -m fallback --no-res --no-inline-anonymous --no-move-inner-classes --no-inline-methods -d carinfo-fb Car_Info.apk
python3 -I resolve.py carinfo-fb <apk assets>/protocol resolve.json      # decoder chosen for every catalogue car
python3 -I infer.py carinfo-fb com.autoai.canbus.psa.protocol.RePsaProtocol 0x38   # signals of one message
python3 -I batch.py carinfo-fb resolve.json out 4                         # every decoder, one JSON each
```

| File | Role |
|---|---|
| `jvm.py` | interpreter of the listing: registers, Java int widths, float bits, arrays, objects, calls, if / goto / switch, lists / maps |
| `resolve.py` | replays `ProtocolUtils.getProtocolBean(CanDescribe)` per car (box id = (catalogue id − 1) × 3 + 1, car code in hex) |
| `probe.py` | builds frames with the decoder's own `getPacket`, feeds `handlePacket`, records what it reports |
| `infer.py` | bit flips on the bytes the decoder reads → which value moves; fits raw / signed / sign-magnitude / endian / factor / clamp, or a table |
| `batch.py` | all decoders in parallel |
| `dbg.py` | call trace of one car's resolution |

State (2026-11-06): resolution gives a decoder for 6 658 of 6 970 catalogue entries (532 decoders); same result as the
hand analyses for PSA (111 / 111) and VW (174 / 174). Probing gives, for RePsaProtocol, the same messages as the
hand-written `psa-raise` profile. Not done yet: profile writer (box family / framing, roles, key names, car type), car
types and ACK, checks against the LibreHU engine.
