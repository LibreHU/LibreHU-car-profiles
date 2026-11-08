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
| `batch.py` | all decoders in parallel (`RX_BOX=receive.json`: frames built as the box sends them for the box types getPacket does not build) |
| `receive.py` | the box → head unit direction: frames of each candidate framing handed to the decoder's own deframer (`parsePacket`, with its `isPacketHeader` / `parsePacketLength` / `isValidPacket`); accepted = the whole frame taken |
| `generate.py` | one LibreHU profile per decoder: box type from its own frame (checksum checked) when its deframer takes it from the box too (`--receive`), else the one it takes, or a framing of its own with an `out` (`OWN_FRAMINGS`: Besturn X80, Haima S5); cars as variants with the car type replayed per car (`buildCarTypePacket`, `getCarTypeIntervalTime`), Car Info values mapped to LibreHU roles, steering wheel keys with their names, examples; noise dropped; decoders of the hand-made profiles left out; « NEVER TRIED ON A CAR » in each description; report next to the folder |
| `dbg.py` | call trace of one car's resolution |

State (2026-11-08): resolution gives a decoder for 6 658 of 6 970 catalogue entries (532 decoders); the 312 others have
none in Car Info itself (checked on Alfa MiTo / Raise: `AlfaRaiseManager` knows models 0, 4 and 6 only). Same result as
the hand analyses for PSA (111 / 111) and VW (174 / 174). Probing: **528 of 532 decoders give messages**. Mazda
(`ReMazdaProtocol`, Raise): its decoder reads every frame whose length byte is 0 or 12..120 as A/C info, whatever the
command; the generator now drops a field read at the same place on most commands, and keeps a field found on many
commands only where its place is its own: A/C 0x21, outside temperature 0x27, doors 0x40, radar, keys. Box → head unit
(`receive.py`, every decoder): 502 of the 503 published profiles verified; Haima S5 fixed (its box sends `FC LEN CMD`,
not `FD`); 6 framings the engine 2.7 reads (box types `cyt-55-fixed`, `cyt-55`, `simple-aa55-len`, X80's own). Generator:
**510 profiles, 5 356 cars** (6 115 with the hand-made ones, 111 makes), all checked by the engine 2.7 (`check`:
528 / 528). Left out: `KlydeRentProtocol` (scooters), 7 decoders with nothing LibreHU reads (`ReBaicM20Protocol` and
`Panoramic360SerialProtocol` empty, `HangDaoProtocol`, `ReJacProtocolSingle`, `OdJacShaiLingProtocol`, two rear
screens / machines), 4 series that are no cars. Make names: from the protocol documents Car Info lists (« 东风风神 » →
Dongfeng Aeolus…), `MAKES` in `generate.py`. Never tried on a car.
