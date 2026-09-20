import sys, time
sys.path.insert(0, '.')
from backend.scanner import scan

for rows in (2000, 10000, 30000, 100000):
    path = rf"C:\wanted\scratch_xlsx_{rows}.xlsx"
    t0 = time.time()
    result = scan.scan_file(path, create_masked_copy=False)
    t1 = time.time()
    print(f"{rows} rows: {t1-t0:.2f}s, findings: {len(result.findings)}, error: {result.error}", flush=True)
