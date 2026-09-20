import sys, time
sys.path.insert(0, '.')
from backend.scanner import scan
from backend.scanner.parser import parse, locate
from backend.scanner.masking import mask

path = r"C:\wanted\scratch_xlsx_10000.xlsx"

def tick(label, t0):
    t1 = time.time()
    print(f"{label}: {t1-t0:.2f}s", flush=True)
    return t1

t = time.time()
doc = parse.load(path)
t = tick(f"parse.load", t)

result = scan.scan_text(doc.raw_text, meta={"filename": path, "file_type": doc.file_type, "spans": doc.spans})
t = tick(f"scan_text ({len(result.findings)} findings)", t)

locate.fill_coords(doc, result.findings)
t = tick("locate.fill_coords", t)

masked_path = mask.build_file(path, doc, result.findings, policy=None)
t = tick(f"mask.build_file -> {masked_path}", t)

print("DONE", flush=True)
