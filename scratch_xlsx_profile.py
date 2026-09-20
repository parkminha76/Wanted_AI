import sys, time
sys.path.insert(0, '.')
from backend.scanner import scan
from backend.scanner.parser import parse

path = r"C:\wanted\scratch_xlsx_10000.xlsx"

def tick(label, t0):
    t1 = time.time()
    print(f"{label}: {t1-t0:.2f}s", flush=True)
    return t1

t = time.time()
doc = parse.load(path)
t = tick(f"parse.load (text len={len(doc.raw_text)}, spans={len(doc.spans)})", t)

result = scan.scan_text(doc.raw_text, meta={"filename": path, "file_type": doc.file_type, "spans": doc.spans})
t = tick(f"scan_text ({len(result.findings)} findings)", t)
print("DONE", flush=True)
