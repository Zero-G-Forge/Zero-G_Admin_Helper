## ==========================================
## ZERO-G ADMIN HELPER - EPB CORE
## Read-only helpers for .epb blueprint files.
## Unpacks the ZIP payload and lists device
## records (portal pads, LCD text, names).
## Does not write or change any file.
## ==========================================

# region Imports

import struct
import zipfile
from io import BytesIO

# endregion


# region Constants

## Empyrion footer after the ZIP EOCD.
TRAILER = b"\x00\x00\x00\x00\x01\x00"

## Property value types in the payload.
TYPE_INT32 = 0
TYPE_STRING = 1
TYPE_BYTE = 2
TYPE_FLOAT = 3
TYPE_COLOR = 5

## First matching key set wins for kind.
KIND_KEYS = [
    ("portal", ("SS", "PF", "Entity")),
    ("lcd", ("Text",)),
    ("trader", ("Type", "Restock")),
    ("dialog", ("Dlg",)),
    ("signal", ("Name", "State")),
    ("light", ("Intens",)),
    ("circuit", ("Func", "OpName")),
    ("loot", ("LootId",)),
]

# endregion


# region Unpack

## Split one .epb into header, ZIP bytes, and trailer.
def split_epb(data):
    zip_off = data.find(b"PK\x03\x04")
    if zip_off < 6:
        raise ValueError("no ZIP local header")
    prefix = data[zip_off - 2:zip_off]
    if prefix != b"\x00\x01":
        raise ValueError("missing 00 01 before ZIP")
    if data[-6:] != TRAILER:
        raise ValueError("unexpected 6-byte trailer")
    size_off = zip_off - 6
    stored = struct.unpack_from("<I", data, size_off)[0]
    zip_bytes = data[zip_off:-6]
    if stored != len(zip_bytes):
        raise ValueError("wrapper ZIP size mismatch")
    header = data[:size_off]
    return header, zip_bytes, TRAILER


## Unpack the single deflate member named "0".
def unzip_payload(zip_bytes):
    stream = BytesIO(zip_bytes)
    with zipfile.ZipFile(stream) as zf:
        names = zf.namelist()
        if names != ["0"]:
            raise ValueError("unexpected ZIP members")
        info = zf.getinfo("0")
        payload = zf.read("0")
        if info.compress_type != zipfile.ZIP_DEFLATED:
            raise ValueError("ZIP member is not deflate")
        return payload, info

# endregion


# region Field parse

## Read a 7-bit length used by long LCD strings.
def read_varint(buf, pos):
    shift = 0
    val = 0
    while pos < len(buf):
        b = buf[pos]
        pos += 1
        val |= (b & 0x7F) << shift
        if b & 0x80 == 0:
            return val, pos
        shift += 7
        if shift > 28:
            break
    raise ValueError("bad varint")


## True when raw bytes look like a field name.
def is_key(raw):
    if not (1 <= len(raw) <= 24):
        return False
    first = raw[0]
    letter = ((65 <= first <= 90) or (97 <= first <= 122))
    if not letter:
        return False
    for c in raw:
        ok = ((65 <= c <= 90) or (97 <= c <= 122) or (48 <= c <= 57) or c == 95)
        if not ok:
            return False
    return True


## Read one typed field and return the new pos.
def parse_field(buf, pos):
    if pos + 2 > len(buf):
        raise ValueError("short field")
    typ = buf[pos]
    klen = buf[pos + 1]
    pos += 2
    known = (TYPE_INT32, TYPE_STRING, TYPE_BYTE, TYPE_FLOAT, TYPE_COLOR)
    if typ not in known:
        raise ValueError("unknown type")
    if pos + klen > len(buf):
        raise ValueError("short key")
    raw = buf[pos:pos + klen]
    pos += klen
    if not is_key(raw):
        raise ValueError("bad key")
    key = raw.decode("ascii")
    if typ == TYPE_INT32:
        if pos + 4 > len(buf):
            raise ValueError("short int32")
        val = struct.unpack_from("<I", buf, pos)[0]
        pos += 4
    elif typ == TYPE_STRING:
        n, pos = read_varint(buf, pos)
        if pos + n > len(buf):
            raise ValueError("short string")
        chunk = buf[pos:pos + n]
        val = chunk.decode("utf-8", "replace")
        pos += n
    elif typ == TYPE_BYTE:
        if pos >= len(buf):
            raise ValueError("short byte")
        val = buf[pos]
        pos += 1
    elif typ == TYPE_FLOAT:
        if pos + 4 > len(buf):
            raise ValueError("short float")
        val = struct.unpack_from("<f", buf, pos)[0]
        pos += 4
    else:
        if pos + 4 > len(buf):
            raise ValueError("short color")
        val = buf[pos:pos + 4].hex()
        pos += 4
    return key, typ, val, pos


## Pick a kind from the field names we found.
def classify(fields):
    keys = {item["key"] for item in fields}
    for kind, need in KIND_KEYS:
        if keys.intersection(need):
            return kind
    return "other"


## Make a short text preview for the table.
def record_text(fields):
    names = ("Text", "Name", "Dlg", "Ent")
    for item in fields:
        if item["key"] in names:
            val = item["value"]
            if isinstance(val, str):
                return val
    return ""


## Turn fields into one display string.
def format_fields(fields):
    parts = []
    for item in fields:
        typ = item["type"]
        val = item["value"]
        if typ == TYPE_STRING:
            shown = " ".join(val.split())
        elif typ == TYPE_FLOAT:
            shown = f"{val:.4g}"
        elif typ == TYPE_INT32 and val > 0xFFFF:
            shown = hex(val)
        else:
            shown = str(val)
        parts.append(item["key"] + "=" + shown)
    return ", ".join(parts)

# endregion


# region List records

## Open a .epb and list device records.
## Offsets are in the unpacked payload.
## This function never writes to disk.
def list_device_records(path):
    data = open(path, "rb").read()
    header, zip_bytes, _ = split_epb(data)
    payload, _ = unzip_payload(zip_bytes)
    records = []
    used = bytearray(len(payload))
    pos = 0
    end = len(payload) - 3
    while pos < end:
        if used[pos] or payload[pos] != 0x01:
            pos += 1
            continue
        count = struct.unpack_from("<H", payload, pos + 1)[0]
        if not (1 <= count <= 16):
            pos += 1
            continue
        cur = pos + 3
        fields = []
        try:
            for _ in range(count):
                key, typ, val, cur = parse_field(payload, cur)
                fields.append({"key": key, "type": typ, "value": val})
        except ValueError:
            pos += 1
            continue
        if not fields:
            pos += 1
            continue
        records.append({"offset": pos, "kind": classify(fields), "fields": fields, "text": record_text(fields)})
        for i in range(pos, cur):
            used[i] = 1
        pos = cur
    return records

# endregion
