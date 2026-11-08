import requests, struct, sys, os, re, time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

BASE = "https://halas-monsl.mushroomtrack.com/hls/L5XLkVjOpKO_fzZ3NODtcA/1794079359/18000/18450/"
M3U8 = BASE + "18450.m3u8"
HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(os.path.dirname(HERE), "downloads")
OUT_TS = os.path.join(OUTDIR, "video.ts")
SEGDIR = os.path.join(OUTDIR, "segs")
WORKERS = 16
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

# ---- parse m3u8 ----
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

log(f"segments={len(segs)}  key_uri={key_uri}  iv={hex(iv)}")

# ---- key ----
key = requests.get(BASE + key_uri, headers=HDR, timeout=30).content
assert len(key) == 16, f"key size {len(key)}"
log(f"key={key.hex()}")
ivb = iv.to_bytes(16, "big")

os.makedirs(SEGDIR, exist_ok=True)

def unpad(data):
    if not data:
        return data
    n = data[-1]
    if 1 <= n <= 16 and data[-n:] == bytes([n]) * n:
        return data[:-n]
    return data

def fetch_seg(i):
    s = segs[i]
    p = os.path.join(SEGDIR, f"{i:05d}.ts")
    if os.path.exists(p) and os.path.getsize(p) > 0:
        return i, True  # already done
    data = requests.get(BASE + s, headers=HDR, timeout=60).content
    dec = Cipher(algorithms.AES(key), modes.CBC(ivb)).decryptor()
    plain = dec.update(data) + dec.finalize()
    plain = unpad(plain)
    with open(p, "wb") as f:
        f.write(plain)
    return i, False

# ---- download all concurrently ----
t0 = time.time()
done = 0
with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    futs = {ex.submit(fetch_seg, i): i for i in range(len(segs))}
    for fut in as_completed(futs):
        done += 1
        if done % 100 == 0 or done == len(segs):
            el = time.time() - t0
            log(f"downloaded {done}/{len(segs)}  ({el:.0f}s)")
log(f"all segments ready in {time.time()-t0:.0f}s")

# ---- concat in order ----
t0 = time.time()
with open(OUT_TS, "wb") as out:
    for i in range(len(segs)):
        p = os.path.join(SEGDIR, f"{i:05d}.ts")
        with open(p, "rb") as f:
            out.write(f.read())
log(f"concat done in {time.time()-t0:.0f}s -> {OUT_TS} ({os.path.getsize(OUT_TS)/1024/1024:.0f} MB)")
