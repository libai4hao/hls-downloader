import requests, struct, sys, os, re, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

BASE = "https://halas-monsl.mushroomtrack.com/hls/L5XLkVjOpKO_fzZ3NODtcA/1794079359/18000/18450/"
M3U8 = BASE + "18450.m3u8"
HERE = os.path.dirname(os.path.abspath(__file__))
SEGDIR = os.path.join(os.path.dirname(HERE), "downloads", "segs")
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

# re-parse to get fresh key (token may have rotated)
m3 = requests.get(M3U8, headers=HDR, timeout=30).text
lines = m3.splitlines()
key_uri = None
iv = None
segs = []
for ln in lines:
    if ln.startswith("#EXT-X-KEY"):
        m_uri = re.search(r'URI="([^"]+)"', ln)
        m_iv = re.search(r'IV=(0x[0-9A-Fa-f]+)', ln)
        if m_uri: key_uri = m_uri.group(1)
        if m_iv: iv = int(m_iv.group(1), 16)
    elif ln and not ln.startswith("#"):
        segs.append(ln)

os.makedirs(SEGDIR, exist_ok=True)
key = requests.get(BASE + key_uri, headers=HDR, timeout=30).content
ivb = iv.to_bytes(16, "big")
log(f"key={key.hex()} iv={hex(iv)} segments={len(segs)}")

def unpad(data):
    if not data:
        return data
    n = data[-1]
    if 1 <= n <= 16 and data[-n:] == bytes([n]) * n:
        return data[:-n]
    return data

def fetch(i, retries=6):
    p = os.path.join(SEGDIR, f"{i:05d}.ts")
    if os.path.exists(p) and os.path.getsize(p) > 0:
        return i, "exists"
    last = None
    for attempt in range(retries):
        try:
            data = requests.get(BASE + segs[i], headers=HDR, timeout=60).content
            dec = Cipher(algorithms.AES(key), modes.CBC(ivb)).decryptor()
            plain = dec.update(data) + dec.finalize()
            plain = unpad(plain)
            with open(p, "wb") as f:
                f.write(plain)
            return i, "ok"
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    return i, f"FAIL {type(last).__name__}: {str(last)[:80]}"

# determine missing
missing = [i for i in range(len(segs)) if not (os.path.exists(os.path.join(SEGDIR, f"{i:05d}.ts")) and os.path.getsize(os.path.join(SEGDIR, f"{i:05d}.ts")) > 0)]
log(f"missing={len(missing)}: {[f'{i:05d}' for i in missing]}")

with ThreadPoolExecutor(max_workers=16) as ex:
    futs = {ex.submit(fetch, i): i for i in missing}
    for fut in as_completed(futs):
        i, st = fut.result()
        if st != "ok" and st != "exists":
            log(f"seg {i:05d}: {st}")

# final check
still = [i for i in range(len(segs)) if not (os.path.exists(os.path.join(SEGDIR, f"{i:05d}.ts")) and os.path.getsize(os.path.join(SEGDIR, f"{i:05d}.ts")) > 0)]
log(f"still missing: {len(still)} -> {[f'{i:05d}' for i in still]}")
