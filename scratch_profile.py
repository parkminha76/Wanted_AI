import time, sys
sys.path.insert(0, '.')
from backend.scanner import scan
from backend.scanner.detectors import rules, models

path = r"C:\Users\playdata2\Downloads\DocXray_합성데이터_5MB.log"
with open(path, encoding="utf-8") as f:
    text = f.read()

def tick(label, t0):
    t1 = time.time()
    print(f"{label}: {t1-t0:.2f}s", flush=True)
    return t1

t = time.time()
rule_findings = rules.find_all(text)
t = tick(f"rules.find_all ({len(rule_findings)} hits)", t)

sentences = scan._sentence_index(text)
t = tick(f"_sentence_index ({len(sentences)} sentences)", t)

findings = scan._find_injections(text)
t = tick(f"_find_injections ({len(findings)} hits)", t)

print("DONE", flush=True)
