import time, sys
sys.path.insert(0, '.')
from backend.scanner import scan

path = r"C:\Users\playdata2\Downloads\DocXray_합성데이터_5MB.log"

t0 = time.time()
result = scan.scan_file(path, create_masked_copy=False)
t1 = time.time()
print(f"scan_file: {t1-t0:.2f}s, findings: {len(result.findings)}, error: {result.error}")
