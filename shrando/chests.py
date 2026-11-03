"""Treasure in the field scripts (MPS/<map>.MPS) and how to rewrite it.

A map file starts with an "MFID" header whose u32 list at +8 points at its chunks; the K2Script chunk
starts with "shscript1.03".  Script header H (K2Script::Init): +0x2C string-table offset, +0x30 string
count; string offsets are relative to H.  CMPS::Polling reads the whole file into one buffer, so a
string appended past the end of the file is still reachable through the table.

Commands are 8 bytes at H-relative 8-byte alignment: u16 op, u8 type0, u8 type1, s16 arg0, s16 arg1
(k2sd_readopt: type high nibble 0 = immediate, 6 = string-table index).  A chest is
    5A <str "You've received ">  5A <str item name>  5A <str ".">  ...
    04 ..  9C <code> <count>  05  06 ..  9D <code> <count>  05  30 1  31 <flag>
where 9C adds <count> of item <code> (script numbering, see gamedata) and 31 sets the opened flag.
Only chests whose name string is found are randomized; everything else is reported and left alone.
"""
import re
import struct

from . import gamedata as G

OP_GIVE, OP_MSG, OP_SETVAR = 0x9C, 0x5A, 0x31
T_STRING, T_FLAG = 0x60, 0x43
BACK_WINDOW = 40          # commands searched before a 9C for its message
FLAG_WINDOW = 10          # commands searched after a 9C for the opened flag


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def names_match(inv_name, msg_name):
    a, b = _norm(inv_name), _norm(msg_name)
    return a == b or (len(a) >= 8 and b.startswith(a[:8]))


class Script:
    def __init__(self, path, data):
        self.path = path
        self.data = bytearray(data)
        self.h = None
        offs = struct.unpack_from("<14I", data, 8) if data[:4] == b"MFID" else ()
        for o in offs:
            if o < len(data) and data[o:o + 8] == b"shscript":
                self.h = o
                break
        if self.h is None:
            return
        self.st_off, self.st_n = struct.unpack_from("<II", data, self.h + 0x2C)
        self.code_end = self.h + self.st_off

    def str_off(self, i):
        return struct.unpack_from("<I", self.data, self.h + self.st_off + 4 * i)[0]

    def string(self, i):
        o = self.h + self.str_off(i)
        return self.data[o:self.data.index(b"\0", o)].decode("latin1")

    def cmd(self, o):
        return struct.unpack_from("<HBBhh", self.data, o)

    def capacity(self, i):
        """Bytes available in place for string i: up to the next string (or table) start."""
        start = self.str_off(i)
        later = [self.str_off(k) for k in range(self.st_n) if self.str_off(k) > start]
        limit = min(later) if later else start + len(self.string(i)) + 1
        return limit - start

    def set_string(self, i, text):
        raw = text.encode("latin1") + b"\0"
        if len(raw) <= self.capacity(i):
            o = self.h + self.str_off(i)
            self.data[o:o + len(raw)] = raw
            return "in place"
        self.data += bytes(-len(self.data) % 4)
        at = len(self.data)
        self.data += raw
        struct.pack_into("<I", self.data, self.h + self.st_off + 4 * i, at - self.h)
        return "appended"

    def set_give(self, o, code):
        struct.pack_into("<h", self.data, o + 4, code)


class Chest:
    """One 9C give command in one map file."""

    def __init__(self, path, off, code, count, flag, name_str):
        self.path, self.off, self.code, self.count = path, off, code, count
        self.flag, self.name_str = flag, name_str      # name_str: string-table index or None
        self.item = G.script_to_item(code)


def scan(script, gd):
    """All flagged 9C gives in a script, with their message name string when one matches."""
    out = []
    if script.h is None:
        return out
    h, end = script.h, script.code_end
    for o in range(h, end, 8):
        op, t0, t1, code, count = script.cmd(o)
        if op != OP_GIVE or t0 or t1 or count <= 0 or not 0 < code < 400:
            continue
        flag = None
        for q in range(o + 8, min(end, o + 8 * FLAG_WINDOW), 8):
            c = script.cmd(q)
            if c[0] == OP_SETVAR and c[1] == T_FLAG:
                flag = c[3]
                break
        if flag is None:
            continue
        item = G.script_to_item(code)
        inv = gd.item_name(item)
        name_str = None
        for q in range(o - 8, max(h, o - 8 * BACK_WINDOW) - 1, -8):
            c = script.cmd(q)
            if c[0] == OP_MSG and c[1] == T_STRING and 0 <= c[3] < script.st_n:
                if names_match(inv, script.string(c[3])):
                    name_str = c[3]
                    break
        out.append(Chest(script.path, o, code, count, flag, name_str))
    return out


def quest_items(scripts):
    """Items a script takes away (9C with count <= 0): kept out of the shuffle so quests still work."""
    out = set()
    for s in scripts:
        if s.h is None:
            continue
        for o in range(s.h, s.code_end, 8):
            op, t0, t1, code, count = s.cmd(o)
            if op == OP_GIVE and not t0 and not t1 and count <= 0 and 0 < code < 400:
                out.add(G.script_to_item(code))
    return out
