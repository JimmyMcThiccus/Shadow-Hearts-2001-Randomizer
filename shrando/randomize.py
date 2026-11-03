"""Seeded randomization of a Shadow Hearts disc image (USA, European or Japanese release).

Each category draws from its own RNG (seed + category name), so switching one category on or off never
changes what another produces.  Key items and items scripts take away are never moved.
"""
import base64
import collections
import dataclasses
import hashlib
import random
import re
import struct

from . import chests as C
from . import gamedata as G
from .disc import Disc, copy_image

VERSION = 3
REGIONS = {"US": "USA", "EU": "Europe", "JP": "Japan", "JP-Best": "Japan (PlayStation 2 the Best)"}
_OUT_REGION = {"US": "USA", "EU": "Europe", "JP": "Japan", "JP-Best": "Japan) (PlayStation 2 the Best"}


def identify(path):
    """(region, 0) for a clean Shadow Hearts image (0: the game has one disc), else raise ValueError."""
    try:
        d = Disc(path)
    except (AssertionError, KeyError, IndexError, struct.error) as e:
        raise ValueError("%s is not a Shadow Hearts disc image (%s)" % (path, e))
    try:
        for region, layout in G.LAYOUTS.items():
            if layout.exe in d.root:
                return region, 0
    finally:
        d.close()
    raise ValueError("%s is not a Shadow Hearts disc image this randomizer knows" % path)


def out_name(region, disc, seed):
    return "Shadow Hearts (%s) [Rando %s].iso" % (_OUT_REGION[region], seed)


def spoiler_name(region, seed):
    return "Shadow Hearts (%s) [Rando %s] spoiler.txt" % (_OUT_REGION[region], seed)


@dataclasses.dataclass
class Settings:
    seed: str = ""
    # chests
    chests: bool = True
    chest_mode: str = "shuffle"        # shuffle: swap existing contents | random: any item
    chest_mix_kinds: bool = True       # a weapon chest may hold an item, and so on
    # shops
    shops: bool = True
    shop_mode: str = "kind"            # kind: same kind per slot | any: any kind
    shop_keep_healing: bool = True     # every shop that sold Thera Leaf still does
    # monster drops
    drops: bool = True
    drop_mix_kinds: bool = True
    drop_fill_empty: bool = False      # monsters that dropped nothing get a drop too
    drop_rate: int = 100               # percent of the original chance
    # monster stats
    stats: bool = False
    stat_variance: int = 20            # +/- percent on HP, MP and the four battle stats
    gold_rate: int = 100               # percent of the original gold
    # encounters (experimental)
    encounters: bool = False
    encounter_spread: int = 10         # how far (in the monster strength ranking) a swap may reach

    # The code packs every option into 9 bytes: version, a flag word, then the four numbers.
    _FLAGS = ("chests", "chest_mix_kinds", "shops", "shop_keep_healing", "drops", "drop_mix_kinds",
              "drop_fill_empty", "stats", "encounters")
    _CHOICES = (("chest_mode", ("shuffle", "random")), ("shop_mode", ("kind", "any")))
    _NUMBERS = (("drop_rate", "H"), ("stat_variance", "B"), ("gold_rate", "H"), ("encounter_spread", "B"))

    def to_code(self):
        bits = 0
        for i, k in enumerate(self._FLAGS):
            bits |= bool(getattr(self, k)) << i
        for j, (k, opts) in enumerate(self._CHOICES):
            bits |= opts.index(getattr(self, k)) << (len(self._FLAGS) + j)
        blob = struct.pack("<BH" + "".join(f for _, f in self._NUMBERS), VERSION, bits,
                           *(getattr(self, k) for k, _ in self._NUMBERS))
        return "SH1-%s-%s" % (base64.urlsafe_b64encode(blob).decode().rstrip("="), self.seed)

    @classmethod
    def from_code(cls, code, allow_old=False):
        """allow_old: accept an older version's code for its options only (the layout has not changed
        since version 1); used to restore the last settings, never to reproduce an old seed."""
        m = re.fullmatch(r"SH1-([A-Za-z0-9_-]{12})-(.*)", code.strip())
        if not m:
            raise ValueError("not a Shadow Hearts randomizer code")
        blob = base64.urlsafe_b64decode(m.group(1))
        vals = struct.unpack("<BH" + "".join(f for _, f in cls._NUMBERS), blob)
        if vals[0] != VERSION and not (allow_old and 1 <= vals[0] < VERSION):
            raise ValueError("code is from randomizer version %s, this is %s" % (vals[0], VERSION))
        s = cls(seed=m.group(2))
        for i, k in enumerate(cls._FLAGS):
            setattr(s, k, bool(vals[1] >> i & 1))
        for j, (k, opts) in enumerate(cls._CHOICES):
            setattr(s, k, opts[vals[1] >> (len(cls._FLAGS) + j) & 1])
        for (k, _), v in zip(cls._NUMBERS, vals[2:]):
            setattr(s, k, v)
        return s


def rng(settings, category):
    h = hashlib.sha256(("%s/%s" % (settings.seed, category)).encode()).digest()
    return random.Random(int.from_bytes(h[:8], "little"))


class Log:
    def __init__(self):
        self.sections = collections.OrderedDict()

    def add(self, section, line):
        self.sections.setdefault(section, []).append(line)

    def text(self, header):
        out = [header, ""]
        for k, v in self.sections.items():
            out += ["== %s ==" % k] + v + [""]
        return "\n".join(out)


class Randomizer:
    def __init__(self, src_iso, settings, progress=None):
        self.src, self.s = src_iso, settings
        self.progress = progress or (lambda frac, msg: None)
        self.log = Log()

    # -- the pools ------------------------------------------------------------------------------------
    def _pools(self, gd, fixed):
        return {k: [it for it in gd.valid_items(k) if it not in fixed] for k in G.KINDS}

    def _random_item(self, r, pools, kind, mix):
        if mix:
            kind = r.choices(G.KINDS, weights=[len(pools[k]) for k in G.KINDS])[0]
        return r.choice(pools[kind])

    # -- categories -----------------------------------------------------------------------------------
    def do_chests(self, gd, scripts, pools, fixed):
        r = rng(self.s, "chests")
        all_chests = [c for s in scripts.values() for c in C.scan(s, gd)]
        groups = collections.OrderedDict()           # (flag, item) -> chests sharing one opened flag
        for c in all_chests:
            groups.setdefault((c.flag, c.item), []).append(c)
        # a name string shared by two groups forces them to the same item
        by_str = {}
        merged = {}
        for key, cs in groups.items():
            root = key
            for c in cs:
                if c.name_str is not None:
                    root = by_str.setdefault((c.path, c.block, c.name_str), root)
            merged.setdefault(root, []).extend(cs)
        usable, skipped = [], []
        for key, cs in merged.items():
            item = cs[0].item
            if item in fixed or any(c.name_str is None for c in cs) or len({c.item for c in cs}) > 1:
                skipped.append((key, cs))
            else:
                usable.append((key, cs))
        if self.s.chest_mode == "shuffle":
            contents = [cs[0].item for _, cs in usable]
            if not self.s.chest_mix_kinds:
                by_kind = collections.defaultdict(list)
                for it in contents:
                    by_kind[it[0]].append(it)
                for v in by_kind.values():
                    r.shuffle(v)
                new = [by_kind[it[0]].pop() for it in contents]
            else:
                new = contents[:]
                r.shuffle(new)
        else:
            new = [self._random_item(r, pools, cs[0].item[0], self.s.chest_mix_kinds) for _, cs in usable]
        for (key, cs), it in zip(usable, new):
            code = G.item_to_script(it)
            name = gd.item_name(it)
            done_str = set()
            for c in cs:
                s = scripts[c.path]
                b = s.blocks[c.block]
                b.set_give(c.off, code)
                if (c.path, c.block, c.name_str) not in done_str:
                    # each language's script gets the item's name in that language
                    names = gd.lang_names[b.lang] if b.lang < len(gd.lang_names) else gd.names
                    b.set_string(c.name_str, C.message_name(gd.item_name(it, names), s.encoding))
                    done_str.add((c.path, c.block, c.name_str))
            maps = sorted({c.path[4:-4] for c in cs})
            self.log.add("Chests", "%-9s  %-22s -> %-22s  %s" % (
                key[0], gd.item_name(cs[0].item), name, " ".join(maps)))
        for key, cs in skipped:
            self.log.add("Chests left as they were", "%-9s  %-22s  %s" % (
                key[0], gd.item_name(cs[0].item), " ".join(sorted({c.path[4:-4] for c in cs}))))

    def do_shops(self, gd, pools):
        r = rng(self.s, "shops")
        seen = set()
        healing = ("item", 1)                       # Thera Leaf
        for shop in gd.shops:
            if shop.index in G.DEBUG_SHOPS or shop.goods_va in seen or len(shop.goods) <= 1:
                continue
            seen.add(shop.goods_va)
            old = list(shop.goods)
            new, used = [], set()
            keep = self.s.shop_keep_healing and healing in old
            for kind, gid in old:
                if kind not in G.KINDS or (kind, gid) in self.fixed:
                    new.append(None)
                    continue
                for _ in range(50):
                    it = self._random_item(r, pools, kind, self.s.shop_mode == "any")
                    if it not in used and it != healing:
                        break
                used.add(it)
                new.append(it)
            new = [o if n is None else n for o, n in zip(old, new)]
            if keep:
                new[old.index(healing)] = healing
            shop.goods = new
            gd.write_shop(shop)
            self.log.add("Shops", "shop %2d: %s" % (shop.index, ", ".join(gd.item_name(it) for it in new)))

    def do_drops(self, gd, pools):
        r = rng(self.s, "drops")
        for m in gd.monsters:
            if not m.name or m.name in G.BAD_NAMES:
                continue
            old = G.drop_to_item(m.drop)
            if old is not None and (old[0] == "key" or old in self.fixed):
                continue
            if old is None and not self.s.drop_fill_empty:
                continue
            kind = old[0] if old else "item"
            it = self._random_item(r, pools, kind, self.s.drop_mix_kinds)
            m.drop = G.item_to_drop(it)
            pct = m.drop_pct if old else 10
            m.drop_pct = max(1, min(100, pct * self.s.drop_rate // 100))
            gd.write_monster(m)
            self.log.add("Drops", "%-20s %-20s -> %-20s %3d%%" % (m.name, gd.item_name(old), gd.item_name(it), m.drop_pct))

    def do_stats(self, gd):
        r = rng(self.s, "stats")
        v = self.s.stat_variance / 100.0
        for m in gd.monsters:
            if not m.name or m.name in G.BAD_NAMES or m.hp == 0:   # hp 0: Yuri's fusions
                continue
            f = lambda x: int(round(x * r.uniform(1 - v, 1 + v))) if x else x
            m.hp, m.mp = f(m.hp), f(m.mp)
            m.stats = [f(s) for s in m.stats]
            m.gold = m.gold * self.s.gold_rate // 100
            gd.write_monster(m)
            self.log.add("Monster stats", "%-20s HP %5d MP %4d stats %s gold %d" % (m.name, m.hp, m.mp, m.stats, m.gold))

    def do_encounters(self, gd):
        r = rng(self.s, "encounters")
        normal = [m for m in gd.monsters if m.name and m.name not in G.BAD_NAMES and not m.boss and m.hp > 0]
        ranked = sorted(normal, key=lambda m: (m.hp, m.id))
        rank = {m.id: i for i, m in enumerate(ranked)}
        spread = max(1, self.s.encounter_spread)
        for i, row in enumerate(gd.monster_sets):
            ids = [x for x in row[1:] if x != 0xFFFF]
            if not ids or any(x not in rank for x in ids):
                continue                              # bosses, story fights, empty groups
            swap = {}
            for x in dict.fromkeys(ids):
                lo, hi = max(0, rank[x] - spread), min(len(ranked) - 1, rank[x] + spread)
                swap[x] = ranked[r.randint(lo, hi)].id
            new = [row[0]] + [swap.get(x, x) if x != 0xFFFF else x for x in row[1:]]
            gd.write_monster_set(i, new)
            self.log.add("Encounters", "group %3d: %s -> %s" % (
                i, ", ".join(gd.monster(x).name for x in ids), ", ".join(gd.monster(swap[x]).name for x in ids)))

    # -- the whole run --------------------------------------------------------------------------------
    def run(self, out_iso):
        s = self.s
        self.region, _ = identify(self.src)
        layout = G.LAYOUTS[self.region]
        self.progress(0.0, "Copying the disc image")
        copy_image(self.src, out_iso, lambda f: self.progress(0.85 * f, "Copying the disc image"))
        disc = Disc(out_iso, writable=True)
        try:
            self.progress(0.86, "Reading game data")
            gd = G.GameData(disc.read_root_file(layout.exe), [disc.read(p) for p in layout.messages], self.region)
            scripts = {p: C.Script(p, disc.read(p), layout.encoding)
                       for p in sorted(x for x in disc.files if x.startswith("MPS/"))}
            # never moved: items scripts take away in this release or the US one (except the numbered keys,
            # which are plain consumables) and Lottery Tickets
            fixed = {it for it in C.quest_items(scripts.values()) | G.US_QUEST_ITEMS if it not in G.FREE_ITEMS} | (
                {G.LOTTERY_TICKET} & set(gd.valid_items("item")))
            self.fixed = fixed
            pools = self._pools(gd, fixed)
            originals = {p: bytes(sc.data) for p, sc in scripts.items()}
            if s.chests:
                self.progress(0.88, "Chests")
                self.do_chests(gd, scripts, pools, fixed)
            if s.shops:
                self.progress(0.90, "Shops")
                self.do_shops(gd, pools)
            if s.drops:
                self.progress(0.91, "Monster drops")
                self.do_drops(gd, pools)
            if s.stats:
                self.progress(0.92, "Monster stats")
                self.do_stats(gd)
            if s.encounters:
                self.progress(0.93, "Encounters")
                self.do_encounters(gd)
            self.progress(0.95, "Writing the disc image")
            disc.write_root_file(layout.exe, bytes(gd.elf.data))
            changed = [p for p, sc in scripts.items() if bytes(sc.data) != originals[p]]
            for p in changed:
                disc.write(p, bytes(scripts[p].data))
            disc.commit()
        finally:
            disc.close()
        self.progress(0.98, "Checking the result")
        self.verify(out_iso, gd, {p: bytes(scripts[p].data) for p in changed})
        self.progress(1.0, "Done")
        return self.log.text("Shadow Hearts Randomizer\nDisc: %s\nCode: %s\n" % (REGIONS[self.region], s.to_code()))

    def verify(self, out_iso, gd, files):
        """Re-open the written image and check every file we changed reads back as written."""
        exe = gd.layout.exe
        d = Disc(out_iso)
        try:
            assert d.read_root_file(exe) == bytes(gd.elf.data), "%s did not read back" % exe
            for p, data in files.items():
                assert d.read(p) == data, "%s did not read back" % p
        finally:
            d.close()
