"""Static game tables in SLUS_203.47 (NTSC-U retail) and the names they point at.

Addresses are retail VAs from the decomp (build/extract/symbols.txt); file offset = VA - 0x1FFF80.
Name strings below 0x200000 live in COMMON/CMNMSG0.BIN, which K2Main::SetBtlmsg copies to 0x180000.

The game uses four different numberings for the same items:
  inventory (BtlAddItem)      0 weapon, 1 armor, 2 accessory, 3 item, 4 key
  shop goods (ShopMenu)       u16 kind 0 item, 2 weapon, 3 armor, 4 accessory; u16 id
  monster drop (AddMonItem)   u8 1..0x40 item, +0x40 accessory, +0x80 weapon, +0xB0 armor, +0xD0 key
  field script (opcode 0x9C)  s16 <100 item, 100.. accessory, 200.. weapon, 300.. armor
Here an item is (kind, id) with kind one of KINDS.
"""
import re
import struct

ELF_DELTA = 0x1FFF80
MSG_BASE = 0x180000

KINDS = ("item", "weapon", "armor", "accessory")

NAME_TABLES = {  # kind: (VA, entries)
    "weapon": (0x4B0360, 49),
    "armor": (0x4B0430, 25),
    "accessory": (0x4B04A0, 65),
    "item": (0x4B05B0, 63),
    "key": (0x4B06B0, 68),
}
MON_NAMETBL = (0x4B07C0, 189)

SHOP_DATA = (0x4CDB70, 26)        # {char* name, u32 count, Goods* list, u32 pic}
SHOP_KIND = {0: "item", 2: "weapon", 3: "armor", 4: "accessory"}
SHOP_KIND_CODE = {v: k for k, v in SHOP_KIND.items()}
DEBUG_SHOPS = {13}                # 193 goods: every item in the game

MONSTER_LIST = (0x4B3210, 188, 0x28)   # GetNpcCharParam(id) = &monster_list[id - 50]
MONSTER_ID0 = 50
MON_HP, MON_MP, MON_STATS, MON_DROP, MON_DROP_PCT, MON_GOLD = 0x0A, 0x0C, 0x10, 0x1C, 0x1D, 0x20
BOSSLIST = (0x4BE810, 43)

MONSTER_SET = (0x4973B0, 188, 12)      # u16 formation, u16 monster id x5 (0xFFFF empty)

BAD_NAMES = {"", "------", "????????", "Dummy"}
KEEP_NAMES = re.compile(r"\bKey\b|Lottery Ticket")


def drop_to_item(b):
    if b == 0:
        return None
    if b <= 0x40:
        return ("item", b)
    if b <= 0x80:
        return ("accessory", b - 0x40)
    if b <= 0xB0:
        return ("weapon", b - 0x80)
    if b <= 0xC8:
        return ("armor", b - 0xB0)
    return ("key", b - 0xD0)


def item_to_drop(it):
    kind, i = it
    return {"item": 0, "accessory": 0x40, "weapon": 0x80, "armor": 0xB0}[kind] + i


def script_to_item(code):
    if code < 100:
        return ("item", code)
    if code < 200:
        return ("accessory", code - 100)
    if code < 300:
        return ("weapon", code - 200)
    return ("armor", code - 300)


def item_to_script(it):
    kind, i = it
    return {"item": 0, "accessory": 100, "weapon": 200, "armor": 300}[kind] + i


class Elf:
    """SLUS_203.47 as a mutable byte buffer addressed by VA."""

    def __init__(self, data):
        self.data = bytearray(data)

    def off(self, va):
        o = va - ELF_DELTA
        assert 0x80 <= o < len(self.data), hex(va)
        return o

    def u8(self, va):
        return self.data[self.off(va)]

    def u16(self, va):
        return struct.unpack_from("<H", self.data, self.off(va))[0]

    def s32(self, va):
        return struct.unpack_from("<i", self.data, self.off(va))[0]

    def u32(self, va):
        return struct.unpack_from("<I", self.data, self.off(va))[0]

    def put(self, fmt, va, *v):
        struct.pack_into(fmt, self.data, self.off(va), *v)

    def cstr(self, va):
        o = self.off(va)
        return self.data[o:self.data.index(b"\0", o)].decode("latin1")


class Monster:
    def __init__(self, mid, va, name, hp, mp, stats, drop, drop_pct, gold):
        self.id, self.va, self.name = mid, va, name
        self.hp, self.mp, self.stats = hp, mp, stats
        self.drop, self.drop_pct, self.gold = drop, drop_pct, gold
        self.boss = False


class Shop:
    def __init__(self, index, va, name, goods_va, goods):
        self.index, self.va, self.name, self.goods_va, self.goods = index, va, name, goods_va, goods


class GameData:
    """Reads every table the randomizer touches; write_* methods put changes back into self.elf."""

    def __init__(self, slus, cmnmsg):
        self.elf = Elf(slus)
        self.msg = cmnmsg
        self.names = {k: [self.name_at(self.elf.u32(va + 4 * i)) for i in range(n)]
                      for k, (va, n) in NAME_TABLES.items()}
        va, n = MON_NAMETBL
        self.mon_names = [self.name_at(self.elf.u32(va + 4 * i)) for i in range(n)]
        self.monsters = self._read_monsters()
        self.shops = self._read_shops()
        self.monster_sets = self._read_monster_sets()

    def name_at(self, p):
        if p == 0:
            return ""
        if p >= 0x200000:
            return self.elf.cstr(p)
        o = p - MSG_BASE
        return self.msg[o:self.msg.index(b"\0", o)].decode("latin1")

    def item_name(self, it):
        if it is None:
            return "(nothing)"
        kind, i = it
        names = self.names[kind]
        return names[i] if 0 <= i < len(names) else "%s #%d" % (kind, i)

    def valid_items(self, kind):
        return [(kind, i) for i, nm in enumerate(self.names[kind]) if i > 0 and nm not in BAD_NAMES]

    # --- monsters ----------------------------------------------------------------------------------
    def _read_monsters(self):
        base, n, size = MONSTER_LIST
        bva, bn = BOSSLIST
        bosses = {self.elf.u8(bva + i) for i in range(bn)}
        out = []
        for i in range(n):
            va = base + size * i
            e = self.elf
            nidx = e.u16(va)
            m = Monster(MONSTER_ID0 + i, va,
                        self.mon_names[nidx] if nidx < len(self.mon_names) else "",
                        e.u16(va + MON_HP), e.u16(va + MON_MP),
                        [e.u16(va + MON_STATS + 2 * k) for k in range(4)],
                        e.u8(va + MON_DROP), e.u8(va + MON_DROP_PCT), e.s32(va + MON_GOLD))
            m.boss = m.id in bosses
            out.append(m)
        return out

    def monster(self, mid):
        return self.monsters[mid - MONSTER_ID0]

    def write_monster(self, m):
        e = self.elf
        e.put("<H", m.va + MON_HP, max(1, min(0xFFFF, m.hp)))
        e.put("<H", m.va + MON_MP, max(0, min(0xFFFF, m.mp)))
        for k, s in enumerate(m.stats):
            e.put("<H", m.va + MON_STATS + 2 * k, max(0, min(0xFFFF, s)))
        e.put("<B", m.va + MON_DROP, m.drop)
        e.put("<B", m.va + MON_DROP_PCT, max(0, min(100, m.drop_pct)))
        e.put("<i", m.va + MON_GOLD, max(0, m.gold))

    # --- shops -------------------------------------------------------------------------------------
    def _read_shops(self):
        base, n = SHOP_DATA
        out = []
        for s in range(n):
            va = base + 16 * s
            name_p, count, goods_va, _pic = (self.elf.u32(va + 4 * k) for k in range(4))
            goods = []
            for i in range(count):
                kind, gid = self.elf.u16(goods_va + 4 * i), self.elf.u16(goods_va + 4 * i + 2)
                goods.append((SHOP_KIND.get(kind, "kind%d" % kind), gid))
            out.append(Shop(s, va, self.name_at(name_p), goods_va, goods))
        return out

    def write_shop(self, shop):
        for i, (kind, gid) in enumerate(shop.goods):
            self.elf.put("<HH", shop.goods_va + 4 * i, SHOP_KIND_CODE[kind], gid)

    # --- encounter groups --------------------------------------------------------------------------
    def _read_monster_sets(self):
        base, n, size = MONSTER_SET
        return [list(struct.unpack_from("<6H", self.elf.data, self.elf.off(base + size * i))) for i in range(n)]

    def write_monster_set(self, i, row):
        base, _n, size = MONSTER_SET
        self.elf.put("<6H", base + size * i, *row)
