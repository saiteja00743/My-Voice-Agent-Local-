"""
Robust XTTS-v2 model downloader with chunked retry.
Downloads directly via requests with resume support — bypasses HF rate limits.
"""
import os, sys, time, pathlib, requests

CHUNK = 1024 * 1024  # 1 MB chunks
MAX_RETRIES = 10
RETRY_WAIT = 5  # seconds between retries

# All XTTS-v2 files on HuggingFace
REPO = "tts-hub/XTTS-v2"
FILES = [
    "config.json",
    "vocab.json",
    "speakers_xtts.pth",
    "mel_stats.pth",
    "model.pth",       # ~1.8 GB — the big one
    "dvae.pth",
    "xtts_v2.0_license.txt",
    "README.md",
]

BASE_URL = f"https://huggingface.co/{REPO}/resolve/main"
# Cache dir that TTS library expects
CACHE_DIR = pathlib.Path.home() / ".cache" / "huggingface" / "hub" / \
            "models--tts-hub--XTTS-v2" / "snapshots" / "main"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def human(n):
    for u in ["B","KB","MB","GB"]:
        if n < 1024: return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"

def download_file(filename):
    url = f"{BASE_URL}/{filename}"
    dest = CACHE_DIR / filename
    
    # Skip if already fully downloaded (size > 0 and matches)
    headers = {}
    start = 0
    if dest.exists() and dest.stat().st_size > 0:
        start = dest.stat().st_size
        headers["Range"] = f"bytes={start}-"
        print(f"  Resuming {filename} from {human(start)}")
    else:
        print(f"  Downloading {filename} ...")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(url, headers=headers, stream=True, timeout=30)
            if r.status_code == 416:  # Range not satisfiable = already complete
                print(f"  ✓ {filename} already complete")
                return True
            if r.status_code not in (200, 206):
                print(f"  ✗ HTTP {r.status_code} — retrying ({attempt}/{MAX_RETRIES})")
                time.sleep(RETRY_WAIT)
                continue

            total = int(r.headers.get("content-length", 0)) + start
            mode = "ab" if start > 0 else "wb"
            downloaded = start
            t0 = time.time()

            with open(dest, mode) as f:
                for chunk in r.iter_content(CHUNK):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        elapsed = time.time() - t0 or 0.001
                        speed = (downloaded - start) / elapsed
                        pct = (downloaded / total * 100) if total else 0
                        print(f"\r  {filename}: {human(downloaded)}/{human(total)} "
                              f"({pct:.1f}%) @ {human(speed)}/s    ", end="", flush=True)
            print(f"\n  ✓ {filename} done ({human(downloaded)})")
            return True

        except (requests.RequestException, IOError) as e:
            print(f"\n  ! Error: {e} — retrying in {RETRY_WAIT}s ({attempt}/{MAX_RETRIES})")
            time.sleep(RETRY_WAIT)
            # Update resume position
            if dest.exists():
                start = dest.stat().st_size
                headers["Range"] = f"bytes={start}-"

    print(f"  ✗ FAILED after {MAX_RETRIES} attempts: {filename}")
    return False

print("\n=== XTTS-v2 Model Downloader ===")
print(f"Saving to: {CACHE_DIR}\n")

failed = []
for f in FILES:
    ok = download_file(f)
    if not ok:
        failed.append(f)
    print()

if failed:
    print(f"\n✗ Some files failed: {failed}")
    print("Re-run this script to retry.")
    sys.exit(1)
else:
    print("\n✓ ALL FILES DOWNLOADED! You can now launch the app.")
    sys.exit(0)
