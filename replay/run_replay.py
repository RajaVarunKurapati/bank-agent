"""
CLI: replay a saved capability with input params. No LLM involved.

  python replay/run_replay.py <artifact.json> member_id=12345
"""
import sys, os, json, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from replay.replay import replay

if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python replay/run_replay.py <artifact.json> key=value ...")
    artifact = sys.argv[1]
    params = {}
    for kv in sys.argv[2:]:
        k, _, v = kv.partition("=")
        params[k] = v

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    evidence_dir = os.path.join("evidence", f"replay_{stamp}")
    result = replay(artifact, params, evidence_dir=evidence_dir, headless=False)
    print(json.dumps(result, indent=2))
    print(f"\nEvidence: {evidence_dir}")