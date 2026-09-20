import time, sys
sys.path.insert(0, '.')
from backend.scanner import scan

path = r"C:\Users\playdata2\Downloads\DocXray_합성데이터_5MB.log"
with open(path, encoding="utf-8") as f:
    text = f.read()

t0 = time.time()
result = scan.scan_text(text, meta={"filename": "log.txt", "file_type": "txt"})
t1 = time.time()
print(f"scan_text: {t1-t0:.2f}s, findings: {len(result.findings)}")
