"""Shadow Hearts (USA) disc access: ISO9660 root directory, PKFINFO.TBL and in-place patching.

Adapted from the Shadow Hearts II tools (Sh2 Decomp/dc_patch/tools: iso.py, pkf.py, pkfresolve.py,
isopatch.py); SH1 uses the same PKFINFO format (2081 entries on the US disc).

PKFINFO.TBL: u16 count at 0, then 16-byte entries from offset 16: an 8-byte encoded name, u32 offset in
16-byte units from the parent's start, u32 size (bit 31 set: a directory, low bits = byte offset of its
child list).  FileIOLib::InitPkb replaces each root entry's offset with the disc LBA of <NAME>.PKB.
"""
import os
import shutil
import struct

SECTOR = 2048
_AL = "\0.0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_"


def decode_name(k):
    w0, l0, l1, l2 = struct.unpack(">4H", k)
    his = [w0 % 40, (w0 // 40) % 40, w0 // 1600]
    s = ""
    for hi, lo in zip(his, (l0, l1, l2)):
        u = (hi << 16) | lo
        for _ in range(4):
            d = u % 40
            u //= 40
            if d:
                s += _AL[d]
    return s


class FileRef:
    __slots__ = ("path", "index", "lba", "size")

    def __init__(self, path, index, lba, size):
        self.path, self.index, self.lba, self.size = path, index, lba, size


class Disc:
    """A disc image opened for reading, or for patching (writable=True)."""

    def __init__(self, path, writable=False):
        self.path = path
        self.f = open(path, "r+b" if writable else "rb")
        self.root = self._read_root()
        tlba, tsize = self.root["PKFINFO.TBL"]
        self.f.seek(tlba * SECTOR)
        self.tbl_raw = bytearray(self.f.read(tsize))
        self.entries = self._parse_table()
        self.files = self._walk()
        self.f.seek(0, 2)
        self.end = self.f.tell() // SECTOR
        self.dirty = False

    def close(self):
        self.f.close()

    # --- ISO9660 ---------------------------------------------------------------------------------
    def _read_root(self):
        self.f.seek(16 * SECTOR)
        pvd = self.f.read(SECTOR)
        assert pvd[1:6] == b"CD001", "not an ISO9660 image: %s" % self.path
        root = pvd[156:156 + 34]
        lba, size = struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0]
        self.f.seek(lba * SECTOR)
        d = self.f.read(size)
        out, i = {}, 0
        while i < len(d):
            n = d[i]
            if n == 0:
                i = (i // SECTOR + 1) * SECTOR
                continue
            flba, fsz = struct.unpack_from("<I", d, i + 2)[0], struct.unpack_from("<I", d, i + 10)[0]
            name = d[i + 33:i + 33 + d[i + 32]].decode("ascii", "replace").split(";")[0]
            out[name] = (flba, fsz)
            i += n
        return out

    def read_root_file(self, name):
        lba, size = self.root[name]
        self.f.seek(lba * SECTOR)
        return self.f.read(size)

    def write_root_file(self, name, data):
        """Overwrite a root-directory file (e.g. SLUS_203.47) in place; its size must not change."""
        lba, size = self.root[name]
        assert len(data) == size, "%s must keep its size (%d != %d)" % (name, len(data), size)
        self.f.seek(lba * SECTOR)
        self.f.write(data)

    # --- PKFINFO ---------------------------------------------------------------------------------
    def _parse_table(self):
        raw = self.tbl_raw
        n = struct.unpack_from("<H", raw, 0)[0]
        return [[bytes(raw[16 + i * 16:24 + i * 16])] + list(struct.unpack_from("<II", raw, 24 + i * 16))
                for i in range(n)]

    def _walk(self):
        """path -> FileRef, the way pkf.load walks the table (child lists located by directory sizes)."""
        E, n = self.entries, len(self.entries)
        isdir = lambda e: e[2] & 0x80000000
        cd = lambda e: (e[2] & 0x7FFFFFFF) // 16
        out = {}

        def walk_list(start, limit, prefix, base_lba):
            end, fc = start, None
            while end < min(limit, n):
                e = E[end]
                if isdir(e) and fc is None:
                    fc = start + cd(e)
                end += 1
                if fc is not None and end >= fc:
                    break
            idx = list(range(start, end))
            for k, i in enumerate(idx):
                e = E[i]
                p = prefix + "/" + decode_name(e[0])
                lba = base_lba + (e[1] >> 7)
                if isdir(e):
                    nxt = next((start + cd(E[j]) for j in idx[k + 1:] if isdir(E[j])), limit)
                    walk_list(start + cd(e), nxt, p, lba)
                else:
                    assert e[1] & 0x7F == 0, "%s is not sector aligned" % p
                    out[p] = FileRef(p, i, lba, e[2])

        root_end = next(cd(e) for e in E if isdir(e))
        for k in range(root_end):
            e = E[k]
            nm = decode_name(e[0])
            if isdir(e):
                nxt = next((cd(x) for x in E[k + 1:root_end] if isdir(x)), n)
                walk_list(cd(e), nxt, nm, self.root[nm + ".PKB"][0])
        return out

    def read(self, path):
        r = self.files[path]
        self.f.seek(r.lba * SECTOR)
        return self.f.read(r.size)

    def write(self, path, data):
        """Replace a PKB member: in place when it fits its old sectors, else appended past the end of the
        image and repointed (PKFINFO keeps its entry count, so the table is rewritten where it is)."""
        r = self.files[path]
        e = self.entries[r.index]
        pad = bytes(-len(data) % SECTOR)
        if (len(data) + SECTOR - 1) // SECTOR <= (r.size + SECTOR - 1) // SECTOR:
            self.f.seek(r.lba * SECTOR)
            self.f.write(data + pad)
        else:
            base = r.lba - (e[1] >> 7)
            at = self.end
            self.f.seek(at * SECTOR)
            self.f.write(data + pad)
            self.end += (len(data) + SECTOR - 1) // SECTOR
            e[1] = (at - base) << 7
            r.lba = at
        e[2] = len(data)
        r.size = len(data)
        self.dirty = True

    def commit(self):
        """Write back PKFINFO.TBL and the volume size, then verify every table entry still resolves."""
        if not self.dirty:
            return
        for i, (k, o, s) in enumerate(self.entries):
            self.tbl_raw[16 + i * 16:32 + i * 16] = k + struct.pack("<II", o, s)
        tlba, tsize = self.root["PKFINFO.TBL"]
        assert len(self.tbl_raw) == tsize
        self.f.seek(tlba * SECTOR)
        self.f.write(self.tbl_raw)
        self.f.seek(16 * SECTOR)
        pvd = bytearray(self.f.read(SECTOR))
        struct.pack_into("<I", pvd, 80, self.end)
        struct.pack_into(">I", pvd, 84, self.end)
        self.f.seek(16 * SECTOR)
        self.f.write(pvd)
        self.f.flush()
        self.dirty = False


def copy_image(src, dst, progress=None):
    """Copy the clean image to the output path (about 4 GB), reporting progress as a 0..1 fraction."""
    total = os.path.getsize(src)
    done = 0
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        while True:
            buf = fi.read(16 << 20)
            if not buf:
                break
            fo.write(buf)
            done += len(buf)
            if progress:
                progress(done / total)
    shutil.copystat(src, dst)
