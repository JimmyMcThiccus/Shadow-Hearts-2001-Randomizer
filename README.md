# Shadow Hearts Randomizer

Randomizes Shadow Hearts (USA, SLUS-20347) and writes a new disc image plus a spoiler log. The clean image is
only read, never changed.

## Run

```bash
.venv/Scripts/pythonw.exe run_gui.pyw
```

or from the command line:

```bash
.venv/Scripts/python.exe -m shrando.cli "<clean>.iso" "<out>.iso" [--code SH1-...] [--seed S]
```

Setup once: `C:/Python314/python.exe -m venv .venv` then `.venv/Scripts/python.exe -m pip install -r requirements.txt`.

## What it changes

| Option | Where | Notes |
|---|---|---|
| Chests | field scripts in `MPS/*.MPS` (opcode 0x9C) | the "You've received X." text is rewritten; chests whose message can't be matched, Lottery Tickets, keys and items quests take away are left alone and listed in the log |
| Shops | `ShopData` / `Goods00..25` in SLUS_203.47 | same slots per shop; the debug shop (13) is untouched |
| Drops | `monster_list` +0x1C item, +0x1D chance | key-item drops are kept |
| Monster stats | `monster_list` HP, MP, four stats, gold | Yuri's fusions are skipped |
| Encounters (experimental) | `MonsterSet_Tbl` | swaps non-boss monsters for ones of similar HP rank |

The settings code (`SH1-<options>-<seed>`) reproduces the same image. Each category has its own random
stream, so turning one off never changes the others.

## How the image is written

`SLUS_203.47` keeps its size and is overwritten in place. Changed map files are written back in place when
they still fit their sectors; otherwise they are appended past the end of the image and `PKFINFO.TBL` is
repointed (the Shadow Hearts II `isopatch.py` method). Every changed file is read back and compared.

Research notes: `shrando/gamedata.py` (tables, the four item numberings) and `shrando/chests.py` (map script
format).
