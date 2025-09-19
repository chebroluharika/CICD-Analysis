import json
import time
from pathlib import Path

from main import analyze_with_ai

log_folder = Path("./download_failed_logs")

limit = 10

results = []
for log_file in list(log_folder.glob("*.log"))[:limit]:
    print(f"Analyzing {log_file}")
    start_time = time.time()
    result = analyze_with_ai(log_file, model="gemma3:1b", log_url="test")
    end_time = time.time()
    print(f"Time taken: {end_time - start_time} seconds for {log_file}")

    results.append(
        {
            "log_file": str(log_file),
            "time_taken": end_time - start_time,
            "result": result,
        }
    )

    with open("results.json", "w") as f:
        json.dump(results, f)

