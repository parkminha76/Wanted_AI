import time, sys
sys.path.insert(0, '.')
from backend.scanner import scan
from backend.scanner.detectors import rules

path = r"C:\Users\playdata2\Downloads\DocXray_합성데이터_5MB.log"
with open(path, encoding="utf-8") as f:
    text = f.read()

def tick(label, t0):
    t1 = time.time()
    print(f"{label}: {t1-t0:.2f}s", flush=True)
    return t1

t = time.time()
rule_hits = rules.find_all(text)
findings = [scan._raw_to_finding(d, "rule") for d in rule_hits]
t = tick(f"rules ({len(findings)} findings)", t)

findings2, filtered_out = scan._apply_classifier_filters(findings, text)
t = tick(f"_apply_classifier_filters ({len(findings2)} kept, {len(filtered_out)} filtered)", t)

findings3, place_mentions = scan._split_place_mentions(findings2, text)
t = tick(f"_split_place_mentions ({len(findings3)} left)", t)

scan._promote_hidden_injections(findings3)
t = tick("_promote_hidden_injections", t)

deduped = scan._dedupe(findings3)
t = tick(f"_dedupe ({len(deduped)} kept)", t)

print("DONE", flush=True)
