# Shadow Hearts Randomizer

Randomizes Shadow Hearts and writes a new disc image plus a spoiler log. The clean image is only read, never
changed. Works with the USA (SLUS-20347), European (SLES-50822, English / French / German), Japanese
(SLPS-25041) and Japanese "PlayStation 2 the Best" (SLPS-73418) releases; the release is detected from the image.

## Run

Download `ShadowHeartsRandomizer.exe` from the
[Releases](https://github.com/JimmyMcThiccus/Shadow-Hearts-2001-Randomizer/releases) page and run it. You
need your own Shadow Hearts disc image; settings are saved in `settings.json` beside the exe.

From source:

```bash
.venv/Scripts/pythonw.exe run_gui.pyw
```

or from the command line:

```bash
.venv/Scripts/python.exe -m shrando.cli "<clean>.iso" "<out>.iso or folder" [--code SH1-...] [--seed S]
```

Setup once: `C:/Python314/python.exe -m venv .venv` then `.venv/Scripts/python.exe -m pip install -r requirements.txt`.
Build the exe: `.venv/Scripts/python.exe build.py` (writes `dist/ShadowHeartsRandomizer.exe`).

## What it changes

| Option | Where | Notes |
|---|---|---|
| Chests and invisible field items | field scripts in `MPS/*.MPS` (opcode 0x9C) | the "You've received X." text is rewritten (in the European release in all three languages' scripts, in the Japanese releases the 「X」を手に入れた。 text); chests whose message can't be matched, Lottery Tickets and items quests take away are left alone and listed in the log (the Third, Fifth and Seventh Keys are ordinary consumables and do move) |
| Shops | `ShopData` / `Goods00..25` in the executable | same slots per shop; the debug shop (13) is untouched |
| Drops | `monster_list` +0x1C item, +0x1D chance | key-item drops are kept |
| Monster stats | `monster_list` HP, MP, four stats, gold | Yuri's fusions are skipped |
| Encounters (experimental) | `MonsterSet_Tbl` | swaps non-boss monsters for ones of similar HP rank |

The settings code (`SH1-<options>-<seed>`) reproduces the same image. Each category has its own random
stream, so turning one off never changes the others.

## How the image is written

The executable keeps its size and is overwritten in place. Changed map files are written back in place when
they still fit their sectors; otherwise they are appended past the end of the image and `PKFINFO.TBL` is
repointed (the Shadow Hearts II `isopatch.py` method). Every changed file is read back and compared.

Research notes: `shrando/gamedata.py` (tables per release, the four item numberings) and `shrando/chests.py`
(map script format, the European language scripts).
