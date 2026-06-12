import json

with open(r"C:\Users\wutao\AppData\Local\YuntaoCode\runs.json", encoding="utf-8") as f:
    data = json.load(f)

runs = data.get("runs", [])
runs_sorted = sorted(runs, key=lambda x: x.get("created_at", ""), reverse=True)

for r in runs_sorted[:1]:
    rid = r.get("id", "")[:12]
    created = r.get("created_at", "")[:19]
    mode = r.get("mode", "")
    user = r.get("user_content", "")[:80]
    print(f"=== [{rid}] {created} mode={mode} ===")
    print(f"User: {user}")
    print()
    
    events = r.get("events", [])
    for e in events:
        evt = e.get("event", "")
        if evt == "content":
            delta = e.get("delta", "")
            if "scan_folder" in delta or "filesystem" in delta:
                print(f"  CONTENT: {delta[:300]}")
        elif evt == "tool":
            tool = e.get("tool", "")
            status = e.get("status", "")
            inp = e.get("input", {})
            error = str(e.get("error", ""))
            print(f"  TOOL [{status}]: {tool}")
            if inp:
                print(f"    input: {json.dumps(inp, ensure_ascii=False)[:300]}")
            if error and error != "None":
                print(f"    error: {error[:200]}")
