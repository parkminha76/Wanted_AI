import sys, time, random
sys.path.insert(0, '.')
import openpyxl

def make_xlsx(path, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["이름", "전화번호", "이메일", "주소", "비고"])
    for i in range(rows):
        ws.append([
            f"테스트고객{i:06d}",
            f"010-{i%10000:04d}-{(i*3)%10000:04d}",
            f"user{i}@example.com",
            f"경기도 가상시 테스트로 {i%999}",
            f"메모 {i} 특이사항 없음",
        ])
    wb.save(path)

for rows in (2000, 10000, 30000, 100000):
    path = f"/tmp_xlsx_{rows}.xlsx" if False else rf"C:\wanted\scratch_xlsx_{rows}.xlsx"
    t0 = time.time()
    make_xlsx(path, rows)
    print(f"generated {rows} rows ({(rows+1)} incl header): {time.time()-t0:.2f}s -> {path}", flush=True)
