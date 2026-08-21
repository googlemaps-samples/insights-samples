import os
import json
from collections import defaultdict

def get_eval_stats(root_dir):
    stats = {
        "total_queries": 0,
        "total_evals": 0,
        "persona_coverage": defaultdict(lambda: {"queries": 0, "evals": 0}),
        "verification_status": defaultdict(int)
    }

    # Count SQL files
    queries_dir = os.path.join(root_dir, "assets", "queries")
    if os.path.exists(queries_dir):
        for root, dirs, files in os.walk(queries_dir):
            if "evals" in root: continue
            for f in files:
                if f.endswith(".sql"):
                    stats["total_queries"] += 1
                    persona = os.path.basename(root) if os.path.basename(root) != "queries" else "general"
                    stats["persona_coverage"][persona]["queries"] += 1

    # Parse JSON evals
    evals_dir = os.path.join(queries_dir, "evals")
    if os.path.exists(evals_dir):
        for root, dirs, files in os.walk(evals_dir):
            for f in files:
                if f.endswith(".json"):
                    stats["total_evals"] += 1
                    try:
                        with open(os.path.join(root, f), 'r') as jf:
                            data = json.load(jf)
                            persona = data.get("persona", "unknown")
                            status = data.get("verification", {}).get("status", "UNKNOWN")
                            stats["persona_coverage"][persona]["evals"] += 1
                            stats["verification_status"][status] += 1
                    except:
                        pass
    return stats

def print_report(name, stats):
    print(f"=== {name} SQL Health Report ===")
    print(f"Overall Coverage: {stats['total_evals']}/{stats['total_queries']} "
          f"({(stats['total_evals']/stats['total_queries']*100 if stats['total_queries'] > 0 else 0):.1f}%)")
    
    print("\nPersona Breakdown:")
    for p, counts in stats["persona_coverage"].items():
        if p == "general": continue
        cov = (counts['evals']/counts['queries']*100 if counts['queries'] > 0 else 0)
        print(f" - {p:25} : {counts['evals']}/{counts['queries']} ({cov:.1f}%)")
    
    print("\nVerification Status:")
    for status, count in stats["verification_status"].items():
        print(f" - {status:10}: {count}")
    print("-" * 40)

if __name__ == "__main__":
    for stage in ["rmi-sql", "rmi-sql-preview", "rmi-sql-experimental"]:
        if os.path.exists(stage):
            s = get_eval_stats(stage)
            if s["total_queries"] > 0:
                print_report(stage.upper(), s)
