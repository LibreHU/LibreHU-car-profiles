# Car Info → LibreHU (work in progress)

Reads a **jadx "fallback" listing** of the stock Car Info app (never runs the app) and replays its code in a small
interpreter, to learn what each decoder does and write LibreHU profiles from it. The tools hold nothing of the app;
the repository keeps the app's archive (`tools/Car_Info_1.0.3991.2026-10-21-09-47.3259086a7.7z`, its publisher's, outside
the repository's licence) as the version they were checked against.

```bash
jadx -m fallback --no-res --no-inline-anonymous --no-move-inner-classes --no-inline-methods -d carinfo-fb Car_Info.apk
python3 -I resolve.py carinfo-fb <apk assets>/protocol resolve.json      # decoder chosen for every catalogue car
python3 -I infer.py carinfo-fb com.autoai.canbus.psa.protocol.RePsaProtocol 0x38   # signals of one message
python3 -I batch.py carinfo-fb resolve.json out 4                         # every decoder, one JSON each
python3 -I generate.py out resolve.json profiles --src carinfo-fb --brands ../../brands   # LibreHU profiles
java -jar librehu-car-tool.jar check ../../boxes profiles                 # checked by the real engine
```

| File | Role |
|---|---|
| `jvm.py` | interpreter of the listing: registers, Java int widths, float bits, arrays, objects, calls, if / goto / switch, lists / maps / sets and their iterators (Java's iteration order), `StringBuilder`, `TextUtils` |
| `resolve.py` | replays `ProtocolUtils.getProtocolBean(CanDescribe)` per car (box id = (catalogue id − 1) × 3 + 1, car code in hex) |
| `probe.py` | builds frames with the decoder's own `getPacket` (the command where its `parseRegisterCmdId` reads it: argument, first data byte, second argument or the byte written over), feeds `handlePacket`, or `handlePacket2` with the callback the decoder registered for that command (`isSupportHandlePacketV2`, Car Info's second way in), records what it reports |
| `infer.py` | bit flips on the bytes the decoder reads → which value moves; fits raw / signed / sign-magnitude / endian / factor / clamp, or a table |
| `batch.py` | all decoders in parallel |
| `generate.py` | one LibreHU profile per decoder: box type from its own frame (checksum checked), cars as variants with the car type replayed per car (`buildCarTypePacket`, `getCarTypeIntervalTime`), Car Info values mapped to LibreHU roles, steering wheel keys with their names, examples; noise dropped; decoders of the hand-made profiles left out; « NEVER TRIED ON A CAR » in each description; report next to the folder |
| `dbg.py` | call trace of one car's resolution |

State (2026-11-08): resolution gives a decoder for 6 658 of 6 970 catalogue entries (532 decoders); the 312 others have
none in Car Info itself (checked on Alfa MiTo / Raise: `AlfaRaiseManager` knows models 0, 4 and 6 only). Same result as
the hand analyses for PSA (111 / 111) and VW (174 / 174). Probing: **528 of 532 decoders give messages (4 861
messages)**; Mazda's output is noise (the same fields on its 256 commands, dropped by the generator); nothing from
`Panoramic360SerialProtocol` (empty) and `ReBaicM20Protocol` (empty `handlePacket`), nor yet from `HangDaoProtocol` and
`ReJacProtocolSingle`. Generator: **507 profiles, 5 319 cars**, all checked by the engine (`check`: 512 / 512 with the
box types); left out: 7 framings with no LibreHU box type yet, 8 decoders with nothing LibreHU reads, 10 of the
hand-made profiles. Never tried on a car.
