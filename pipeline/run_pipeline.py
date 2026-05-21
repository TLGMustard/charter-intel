import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import s3_extract, s4_verify, s5_score

s3 = s3_extract.run()
print(f"\n=== S3 ({len(s3['facts'])} facts) ===")
for f in s3["facts"]:
    print(f"  {f['fact_key']:45s} value={str(f['value']):20s} conf={f['confidence']}, src={f['source_class']}")

s4 = s4_verify.run(s3)
ok = [f for f in s4["facts"] if f.get("in_main_analysis")]
blocked = [f for f in s4["facts"] if not f.get("in_main_analysis")]
print(f"\n=== S4 (in_main={len(ok)}, blocked={len(blocked)}) ===")
for f in s4["facts"]:
    print(f"  {'✓' if f.get('in_main_analysis') else '✗'} {f['fact_key']}")

s5 = s5_score.run(s4)
print(f"\n=== S5 ===")
print(f"  Composite : {s5['composite']}")
print(f"  Tier      : {s5['tier']} — {s5['tier_label']}")
print(f"\n  {'Dimension':<30} {'Score':>6}  {'Weight':>7}  Driver")
for dim, d in s5["dimensions"].items():
    print(f"  {dim:<30} {d['score']:>6.1f}  {d['weight']:>7.2f}  {d['driver']}")
