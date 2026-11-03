"""Command line: python -m shrando.cli <clean.iso> <out.iso | out folder> [--code SH1-...] [--seed S]

The image may be the USA, European or Japanese (also "PlayStation 2 the Best") release; the region is detected
from it.  Given a folder, the image and spoiler log get their usual names in it.
"""
import argparse
import os
import random
import sys

from .randomize import REGIONS, Randomizer, Settings, identify, out_name, spoiler_name


def main(argv=None):
    ap = argparse.ArgumentParser(description="Shadow Hearts randomizer (USA, Europe, Japan)")
    ap.add_argument("iso", help="clean Shadow Hearts image")
    ap.add_argument("out", help="randomized image to write, or a folder for it and the spoiler log")
    ap.add_argument("--code", help="settings code from the GUI or a spoiler log")
    ap.add_argument("--seed", help="seed (default: random)")
    a = ap.parse_args(argv)
    s = Settings.from_code(a.code) if a.code else Settings()
    if a.seed:
        s.seed = a.seed
    if not s.seed:
        s.seed = "%08d" % random.randrange(10 ** 8)
    region, _ = identify(a.iso)
    print("disc:", REGIONS[region])
    if os.path.isdir(a.out):
        safe = "".join(ch for ch in s.seed if ch.isalnum() or ch in "-_") or "seed"
        out = os.path.join(a.out, out_name(region, 0, safe))
        spoiler = os.path.join(a.out, spoiler_name(region, safe))
    else:
        out = a.out
        spoiler = os.path.splitext(a.out)[0] + "_spoiler.txt"
    if os.path.normcase(os.path.abspath(out)) == os.path.normcase(os.path.abspath(a.iso)):
        sys.exit("the output would overwrite the clean image")
    last = [None]

    def progress(f, msg):
        line = "%3d%% %s" % (f * 100, msg)
        if line != last[0]:
            print("\r%-40s" % line, end="", flush=True)
            last[0] = line

    log = Randomizer(a.iso, s, progress).run(out)
    print()
    with open(spoiler, "w", encoding="utf-8") as f:
        f.write(log)
    print("wrote", out, "and", spoiler)
    print("code", s.to_code())


if __name__ == "__main__":
    sys.exit(main())
