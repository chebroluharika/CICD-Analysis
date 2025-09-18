import os
import uuid
import datetime
import tempfile
import re
import urllib.request
import json
import csv
import html
import requests
import asyncio
from fastapi import FastAPI, Query, BackgroundTasks, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel
from bs4 import BeautifulSoup
from urllib.error import URLError
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from pathlib import Path
from typing import List

# --- MongoDB Imports ---
from motor.motor_asyncio import AsyncIOMotorClient

# --- LlamaIndex RAG imports ---
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, Settings
from llama_index.core.node_parser import SentenceSplitter
from llama_index.llms.ollama import Ollama
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

# ========== CONFIG ==========

BASE_URL = "http://magna002.ceph.redhat.com/cephci-jenkins/results/openstack"
REPORT_DIR = "./reports"
LOG_DOWNLOAD_DIR = "./download_failed_logs"
os.makedirs(REPORT_DIR, exist_ok=True)
os.makedirs(LOG_DOWNLOAD_DIR, exist_ok=True)

# --- MongoDB Configuration ---
# You can set this with an environment variable or change it here
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB_NAME = "log_analysis_feedback"
MONGO_COLLECTION_NAME = "feedback"

# --- Local Feedback File Configuration ---
FEEDBACK_FILE = "feedback.csv"

# Global variable for MongoDB client
mongo_client = None

# ========== FASTAPI INIT ==========

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# --- Database Connection Lifecycle ---
@app.on_event("startup")
async def startup_db_client():
    """Connects to MongoDB on application startup."""
    global mongo_client
    mongo_client = AsyncIOMotorClient(MONGO_URI)
    print("Connected to MongoDB")

@app.on_event("shutdown")
async def shutdown_db_client():
    """Closes the MongoDB connection on application shutdown."""
    global mongo_client
    if mongo_client:
        mongo_client.close()
        print("Disconnected from MongoDB")

# ========== MODELS ==========

class AnalysisRequest(BaseModel):
    source: str
    ceph_version: str
    rhel_version: str
    test_area: str
    build: str
    jenkins_build: str

progress_data = {}

# ========== DIRECTORY UTILS ==========

def clean_links(soup):
    return sorted([
        a['href'].strip('/')
        for a in soup.find_all('a', href=True)
        if a['href'].endswith('/') and not a['href'].startswith('?')
    ])

def extract_metadata_from_path(path):
    parts = path.split('/')
    ibm_version = parts[1] if len(parts) > 1 else "Unknown"
    rh_build = parts[-2] if len(parts) > 2 else "Unknown"
    distro = next((p for p in parts if p.lower().startswith('rhel-')), "Unknown").upper()
    test_type = 'Sanity' if 'Sanity' in parts else 'Regression'
    return {
        "ibm_version": ibm_version,
        "rh_build": rh_build,
        "distro": distro,
        "test_type": test_type
    }

# ========== LOG COLLECTION ==========

def collect_logs_with_failed_check(base_url, max_depth=3):
    all_logs = []
    failed_logs = []

    def crawl(url, depth):
        if depth > max_depth:
            return
        try:
            html = urllib.request.urlopen(url).read()
            soup = BeautifulSoup(html, "html.parser")
            for link in soup.find_all("a", href=True):
                href = link["href"]
                full_url = urllib.request.urljoin(url, href)
                if href.endswith(".log"):
                    all_logs.append(full_url)
                if (link.text.strip().lower() == "failed") and ("color: red" in link.get("style", "").lower()):
                    log_link = link.get("href")
                    if log_link and log_link.endswith(".log"):
                        failed_url = urllib.request.urljoin(url, log_link)
                        failed_logs.append(failed_url)
                if href.endswith("/") and not href.startswith("?") and href != "../":
                    crawl(full_url, depth + 1)
        except Exception as e:
            print(f"Error accessing {url}: {e}")

    crawl(base_url, 0)
    import pdb; pdb.set_trace()
    return all_logs, list(set(failed_logs))

def download_log_file(url, save_path):
    if os.path.exists(save_path):
        return True
    try:
        with urllib.request.urlopen(url) as response, open(save_path, 'wb') as out_file:
            out_file.write(response.read())
        return True
    except Exception as e:
        print(f"Failed to download {url}: {e}")
        return False

# ========== AI/RAG ANALYSIS ==========

def analyze_with_ai(log_path, model, log_url):
    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()[-10000:]
            log_content = ''.join(lines)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_log_path = os.path.join(temp_dir, "temp_log.log")
            with open(temp_log_path, 'w') as temp_f:
                temp_f.write(log_content)

            Settings.llm = Ollama(model=model, temperature=0.1, request_timeout=120)
            Settings.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5")
            Settings.node_parser = SentenceSplitter(chunk_size=1024, chunk_overlap=100, include_metadata=False)
            documents = SimpleDirectoryReader(input_files=[temp_log_path], file_metadata=lambda _: {"skip_embedding": True}).load_data()
            index = VectorStoreIndex.from_documents(documents, show_progress=False)
            query_engine = index.as_query_engine(similarity_top_k=3, response_mode="compact", streaming=False)

            QUERY_PROMPT = (
                "Analyze this log file to identify the root cause of failures. "
                "Provide concise analysis in EXACTLY this format:\n"
                "Reason: <root cause>\n"
                "Fix: <suggested solution>\n"
                "Steps: <immediate next steps>"
            )
            response = query_engine.query(QUERY_PROMPT)
            text = str(response)
            context_chunks = []
            for i, node in enumerate(response.source_nodes):
                context_chunks.append({
                    "text": node.node.get_content(),
                    "score": node.score,
                    "metadata": node.node.metadata
                })

        reason_match = re.search(r"Reason\s*:\s*(.*?)(?:\n|$)", text, re.IGNORECASE)
        fix_match = re.search(r"Fix\s*:\s*(.*?)(?:\n|$)", text, re.IGNORECASE)
        steps_match = re.search(r"Steps\s*:\s*(.*?)(?:\n|$)", text, re.IGNORECASE)

        reason = reason_match.group(1).strip() if reason_match else "Analysis incomplete"
        fix = fix_match.group(1).strip() if fix_match else "See raw analysis for details"
        steps = steps_match.group(1).strip() if steps_match else "Review full log"

        return {
            "name": os.path.basename(log_path),
            "raw": text.strip(),
            "reason": reason,
            "fix": fix,
            "steps": steps,
            "log_url": log_url,
            "model": model,
            "rag_context": {"query": QUERY_PROMPT, "chunks": context_chunks, "model": model}
        }

    except Exception as e:
        return {
            "name": os.path.basename(log_path),
            "raw": f"RAG analysis failed: {str(e)}",
            "reason": "Pipeline error",
            "fix": "Check configuration",
            "steps": "Verify Ollama service and network connection",
            "log_url": log_url,
            "model": model,
            "rag_context": None
        }

# ========== HTML REPORT ==========

def generate_html_report(analysis_results, output_file="log_report.html"):
    grouped_results = defaultdict(list)
    for result in analysis_results:
        dir_path = os.path.dirname(result['log_url'].replace(
            "http://magna002.ceph.redhat.com/cephci-jenkins/results/openstack/", ""
        )).strip('/')
        grouped_results[dir_path].append(result)
    first_dir = next(iter(grouped_results.keys()))
    metadata = extract_metadata_from_path(first_dir)

    html_content = f"""
    <html>
    <head>
        <title>CephCI Log Analysis Report</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; }}
            th {{ background-color: #f2f2f2; }}
            .directory-title {{ 
                font-size: 1.2em; 
                margin-top: 25px; 
                margin-bottom: 10px; 
                color: #2c3e50; 
                background-color: #ecf0f1; 
                padding: 8px; 
                border-left: 4px solid #3498db; 
            }}
            .log-name {{ font-weight: bold; color: #2980b9; }}
            .feedback-buttons {{ display: flex; gap: 5px; justify-content: center; }}
            .feedback-btn {{ 
                cursor: pointer; 
                border: none; 
                border-radius: 4px; 
                padding: 2px 8px; 
                font-size: 16px;
                transition: background-color 0.3s;
            }}
            .like-btn {{ background-color: #2ecc71; color: white; }}
            .like-btn.active {{ background-color: #27ae60; }}
            .dislike-btn {{ background-color: #e74c3c; color: white; }}
            .dislike-btn.active {{ background-color: #c0392b; }}
            .skip-btn {{ background-color: #f39c12; color: white; }}
            .skip-btn.active {{ background-color: #d35400; }}
            .feedback-form {{
                display: none;
                margin-top: 5px;
            }}
            textarea {{
                width: 100%;
                min-height: 50px;
                padding: 5px;
                border-radius: 4px;
                border: 1px solid #ccc;
            }}
            .submit-all-btn {{
                background-color: #e67e22;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 4px;
                cursor: pointer;
                margin: 20px auto;
                display: block;
                font-size: 16px;
            }}
            .submit-all-btn:hover {{
                background-color: #d35400;
            }}
            .raw-analysis {{
                background-color: #f9f9f9;
                padding: 10px;
                border-radius: 4px;
                margin-top: 5px;
            }}
        </style>
        <script>
            function toggleRawAnalysis(logId) {{
                var rawDiv = document.getElementById('raw-' + logId);
                var toggleBtn = document.getElementById('toggle-' + logId);
                if (rawDiv.style.display === 'none') {{
                    rawDiv.style.display = 'block';
                    toggleBtn.textContent = '▼';
                }} else {{
                    rawDiv.style.display = 'none';
                    toggleBtn.textContent = '➤';
                }}
            }}

            function showFeedbackForm(logId, btnType) {{
                // Remove active class from all buttons for this log
                document.querySelectorAll(`.feedback-btn[data-log-id="${{logId}}"]`).forEach(btn => {{
                    btn.classList.remove('active');
                }});
                
                // Set active class on clicked button
                document.getElementById(btnType + '-btn-' + logId).classList.add('active');
                
                // Show/hide textarea
                var form = document.getElementById('feedback-form-' + logId);
                if (btnType === 'dislike') {{
                    form.style.display = 'block';
                }} else {{
                    form.style.display = 'none';
                }}
            }}

            async function submitAllFeedback() {{
                const feedbacks = [];
                const logItems = document.querySelectorAll('.log-item');
                
                logItems.forEach(item => {{
                    const logId = item.dataset.logId;
                    const activeBtn = item.querySelector('.feedback-btn.active');
                    const vote = activeBtn ? activeBtn.dataset.vote : 'skip';
                    const comment = item.querySelector('textarea')?.value || '';
                    
                    feedbacks.push({{
                        log_id: logId,
                        log_name: item.dataset.logName,
                        vote: vote,
                        comment: comment,
                        build_stamp: new Date().toISOString()
                    }});
                }});

                try {{
                    const response = await fetch('/submit-feedback', {{
                        method: 'POST',
                        headers: {{
                            'Content-Type': 'application/json',
                        }},
                        body: JSON.stringify(feedbacks)
                    }});

                    const data = await response.json();
                    if (response.ok) {{
                        alert('Successfully submitted feedback!');
                    }} else {{
                        alert('Failed to submit feedback: ' + data.error);
                    }}
                }} catch (error) {{
                    console.error('Error:', error);
                    alert('An error occurred while submitting feedback.');
                }}
            }}
        </script>
    </head>
    <body>
        <h2>CephCI Log Analysis Report</h2>
        <p><strong>Generated at:</strong> {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
        <p><strong>Test Suite:</strong> {metadata.get('test_type', 'Unknown')} | <strong>RHEL:</strong> {metadata.get('distro', 'Unknown')}</p>
        <hr>
        
        {generate_test_suite_tables(grouped_results, metadata)}
        
        <button class="submit-all-btn" onclick="submitAllFeedback()">
            Submit All Feedback ({len(analysis_results)} logs)
        </button>
    </body>
    </html>
    """

    with open(output_file, 'w') as f:
        f.write(html_content)


def generate_test_suite_tables(grouped_results, metadata):
    tables_html = ""
    for dir_path, results in grouped_results.items():
        test_suite = dir_path.split('/')[-1] if dir_path else "Unknown Test Suite"
        tables_html += f"""
        <div class="directory-title">📁 Test Suite: <span class="test-suite">{test_suite}</span></div>
        <table>
            <tr>
                <th>#</th>
                <th>Log Name</th>
                <th>Reason</th>
                <th>Fix</th>
                <th>Next Steps</th>
                <th>Feedback</th>
            </tr>
        """

        for idx, result in enumerate(results, 1):
            log_id = re.sub(r'\W+', '', result['name']) + str(uuid.uuid4().hex[:6])
            tables_html += f"""
            <tr class="log-item" data-log-id="{log_id}" data-log-name="{result['name']}">
                <td>{idx}</td>
                <td>
                    <span id="toggle-{log_id}" class="toggle-raw" onclick="toggleRawAnalysis('{log_id}')">➤</span>
                    <a href="{result['log_url']}" target="_blank" class="log-name">{result['name']}</a>
                </td>
                <td>{html.escape(result['reason'])}</td>
                <td>{html.escape(result['fix'])}</td>
                <td>{html.escape(result['steps'])}</td>
                <td>
                    <div class="feedback-buttons">
                        <button id="like-btn-{log_id}" class="feedback-btn like-btn" 
                                onclick="showFeedbackForm('{log_id}', 'like')"
                                data-log-id="{log_id}" data-vote="like">👍</button>
                        <button id="dislike-btn-{log_id}" class="feedback-btn dislike-btn" 
                                onclick="showFeedbackForm('{log_id}', 'dislike')"
                                data-log-id="{log_id}" data-vote="dislike">👎</button>
                        <button id="skip-btn-{log_id}" class="feedback-btn skip-btn" 
                                onclick="showFeedbackForm('{log_id}', 'skip')"
                                data-log-id="{log_id}" data-vote="skip">⏭️</button>
                    </div>
                    <div id="feedback-form-{log_id}" class="feedback-form">
                        <textarea id="feedback-text-{log_id}" 
                                 placeholder="What was incorrect?"></textarea>
                    </div>
                </td>
            </tr>
            <tr>
                <td colspan="6">
                    <div id="raw-{log_id}" class="raw-analysis" style="display: none;">
                        <strong>Raw Analysis:</strong><br>
                        <pre>{html.escape(result['raw'])}</pre>
                    </div>
                </td>
            </tr>
            """
        tables_html += "</table>"

    return tables_html

# ========== ENDPOINTS ==========

@app.get("/list-sources")
def list_sources():
    try:
        with urllib.request.urlopen(BASE_URL, timeout=5) as response:
            soup = BeautifulSoup(response, "html.parser")
            return clean_links(soup)
    except URLError as e:
        print(f"[ERROR] Could not reach {BASE_URL}: {e}")
        raise HTTPException(status_code=500, detail=f"Unable to connect to {BASE_URL}. Check VPN/DNS. Error: {e}")

@app.get("/list-ceph-versions")
def list_ceph_versions(source: str = Query(...)):
    url = f"{BASE_URL}/{source}/"
    response = urllib.request.urlopen(url)
    soup = BeautifulSoup(response, "html.parser")
    return clean_links(soup)

@app.get("/list-rhel-versions")
def list_rhel_versions(source: str, ceph_version: str):
    url = f"{BASE_URL}/{source}/{ceph_version}/"
    response = urllib.request.urlopen(url)
    soup = BeautifulSoup(response, "html.parser")
    return clean_links(soup)

@app.get("/list-test-areas")
def list_test_areas(source: str, ceph_version: str, rhel_version: str):
    url = f"{BASE_URL}/{source}/{ceph_version}/{rhel_version}/"
    response = urllib.request.urlopen(url)
    soup = BeautifulSoup(response, "html.parser")
    return clean_links(soup)

@app.get("/fetch-builds")
def fetch_builds(source: str, ceph_version: str, rhel_version: str, test_area: str):
    url = f"{BASE_URL}/{source}/{ceph_version}/{rhel_version}/{test_area}/"
    response = urllib.request.urlopen(url)
    soup = BeautifulSoup(response, "html.parser")
    return clean_links(soup)

@app.get("/list-jenkins-builds")
def list_jenkins_builds(source: str, ceph_version: str, rhel_version: str, test_area: str, build: str):
    try:
        url = f"{BASE_URL}/{source}/{ceph_version}/{rhel_version}/{test_area}/{build}/"
        response = urllib.request.urlopen(url)
        soup = BeautifulSoup(response, "html.parser")
        return clean_links(soup)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.post("/start-analysis")
def start_analysis(data: AnalysisRequest, background_tasks: BackgroundTasks):
    report_id = str(uuid.uuid4())
    progress_data[report_id] = {
        "status": "Initializing...",
        "total_logs": 0,
        "failed_logs": 0
    }
    background_tasks.add_task(run_analysis, data, report_id)
    return {"report_id": report_id}

def run_analysis(data: AnalysisRequest, report_id: str):
    import pdb; pdb.set_trace()
    # progress_data[report_id]["status"] = "🔍 Scanning for logs..."
    try:
        base_path = "http://magna002.ceph.redhat.com/cephci-jenkins/results/openstack/IBM/8.1/rhel-9.6/Test/19.2.1-245.1.hotfix.bz2375001/870/tier-2_rgw_regression_extended/Test_non_current_deletion_via_s3cmd_0.err"
        urllib.request.urlopen(base_path)
        
        all_logs, failed_logs = collect_logs_with_failed_check(base_path, max_depth=2)

        progress_data[report_id]["total_logs"] = len(all_logs)
        progress_data[report_id]["failed_logs"] = len(failed_logs)

        if not failed_logs:
            progress_data[report_id]["status"] += "\n⚠️ No failed logs to analyze."
            return

        analyzed_logs = []

        def analyze_one(idx, log_url):
            log_name = log_url.split("/")[-1]
            save_path = os.path.join(LOG_DOWNLOAD_DIR, log_name)
            progress_data[report_id]["status"] = f"⬇️ Checking {idx+1}/{len(failed_logs)}: {log_name}"
            if not download_log_file(log_url, save_path):
                return None
            progress_data[report_id]["status"] = f"🧠 Analyzing {idx+1}/{len(failed_logs)}: {log_name}"
            return analyze_with_ai(save_path, model="llama2", log_url=log_url)

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(analyze_one, idx, log_url) for idx, log_url in enumerate(failed_logs)]
            for future in futures:
                result = future.result()
                if result:
                    analyzed_logs.append(result)

        report_path = os.path.join(REPORT_DIR, f"{report_id}.html")
        generate_html_report(analyzed_logs, output_file=report_path)
        progress_data[report_id]["status"] = f"✅ Analysis complete for {len(analyzed_logs)} failed logs."

    except Exception as e:
        progress_data[report_id]["status"] = f"❌ Error during analysis: {e}"

@app.get("/progress/{report_id}")
def check_progress(report_id: str):
    return progress_data.get(report_id, {
        "status": "Unknown Report ID",
        "total_logs": 0,
        "failed_logs": 0
    })

@app.get("/download-report/{report_id}")
def download_report(report_id: str):
    report_path = os.path.join(REPORT_DIR, f"{report_id}.html")
    if os.path.exists(report_path):
        return FileResponse(path=report_path, filename="log_report.html", media_type="text/html")
    return JSONResponse(content={"error": "Report not ready or doesn't exist"}, status_code=404)

@app.get("/view-report/{report_id}", response_class=HTMLResponse)
def view_report(report_id: str):
    report_path = os.path.join(REPORT_DIR, f"{report_id}.html")
    if not os.path.exists(report_path):
        return HTMLResponse(content="❌ Report not found.", status_code=404)
    with open(report_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content, status_code=200)

@app.post("/submit-feedback")
async def submit_feedback(request: Request):
    try:
        feedback_data = await request.json()
        print("📩 Raw feedback received:", feedback_data)

        # --- Write to MongoDB ---
        # Access the MongoDB collection
        db = mongo_client[MONGO_DB_NAME]
        collection = db[MONGO_COLLECTION_NAME]

        # Prepare documents for insertion
        documents_to_insert = []
        for item in feedback_data:
            doc = {
                "timestamp": datetime.datetime.utcnow().isoformat(),
                "testsuite": "Not Provided",  # This field is not in the client request
                "testcase": item.get('log_name', 'Unknown'),
                "actual_rag_error": "Not Provided", # This field is not in the client request
                "improvised_feedback": item.get('comment', ''),
                "vote": item.get('vote', 'skip')
            }
            documents_to_insert.append(doc)
        
        if documents_to_insert:
            result = await collection.insert_many(documents_to_insert)
            print(f"Successfully inserted {len(result.inserted_ids)} documents into MongoDB.")
        
        # --- Write to CSV ---
        with open(FEEDBACK_FILE, 'a', newline='', encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            if csvfile.tell() == 0:  # if file is empty, write header
                writer.writerow(['timestamp', 'build_stamp', 'log_id', 'log_name', 'vote', 'comment'])

            for item in feedback_data:
                writer.writerow([
                    datetime.datetime.utcnow().isoformat(),   # timestamp
                    item.get('build_stamp', ''),
                    item.get('log_id', ''),
                    item.get('log_name', ''),
                    item.get('vote', ''),
                    item.get('comment', '')
                ])

        # --- Write to JSON with fixed key order ---
        json_file = FEEDBACK_FILE.replace(".csv", ".json")

        if os.path.exists(json_file):
            with open(json_file, "r", encoding="utf-8") as jf:
                try:
                    all_feedback = json.load(jf)
                except json.JSONDecodeError:
                    all_feedback = []
        else:
            all_feedback = []

        # Reorder keys for consistency
        ordered_feedback = []
        for item in feedback_data:
            ordered_item = {
                "timestamp": datetime.datetime.utcnow().isoformat(),
                "build_stamp": item.get("build_stamp", ""),
                "log_id": item.get("log_id", ""),
                "log_name": item.get("log_name", ""),
                "vote": item.get("vote", ""),
                "comment": item.get("comment", "")
            }
            ordered_feedback.append(ordered_item)

        all_feedback.extend(ordered_feedback)

        with open(json_file, "w", encoding="utf-8") as jf:
            json.dump(all_feedback, jf, indent=2)

        return JSONResponse(content={"status": "success", "received_count": len(feedback_data)})
            
    except Exception as e:
        print(f"Feedback submission failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to submit feedback: {e}")

@app.get("/openstack-results")
def get_openstack_results():
    try:
        resp = requests.get(BASE_URL, timeout=10)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== END OF FILE ==========
