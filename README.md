# RAG-pipeline
## CephCI Log Analysis RAG Pipeline

This project provides a solution for analyzing **CephCI log files** using a **Retrieval-Augmented Generation (RAG) pipeline**.  
It includes a **FastAPI backend** that scrapes Jenkins log data, runs an **LLM-based analysis**, and stores user feedback, along with a **React frontend** for user interaction.

---

## Features

- **Log Scraping**: Crawls Jenkins-hosted CephCI directories to identify and download failed log files.  
- **LLM-based RAG Analysis**: Uses a RAG pipeline with a local **Ollama LLM** to analyze log files and provide concise, actionable insights.  
- **Persistent Feedback**: Stores user feedback on analysis accuracy in **local JSON, CSV, and MongoDB**.  
- **HTML Reporting**: Generates a clean, user-friendly **HTML report** of the analysis results.  
- **Full-stack Architecture**: A **FastAPI backend** handles data processing and API logic, while a **React frontend** provides a responsive UI.  

---

## System Requirements

- **Python**: 3.8+  
- **Node.js & npm**: For the frontend  
- **Ollama**: Must be running with the specified LLM model (`gemma3:1b`)  
- **MongoDB**: A running MongoDB instance (local or remote) accessible via a connection URI  

---

## Installation & Setup

### 1. Backend Setup

1. Clone the repository:
   ```bash
   git clone https://github.ibm.com/Chebrolu-Harika/RAG-pipeline.git
   cd RAG-pipeline

2. Set up a Python virtual environment:

   ```bash
   python3 -m venv venv
   source venv/bin/activate    # Linux / Mac
   venv\Scripts\activate       # Windows
   ```

3. Install Python dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Configure MongoDB:
   Create a `.env` file in the project root with the following content:

   ```env
   MONGO_URI="mongodb+srv://<user>:<password>@<cluster-url>/<db-name>?retryWrites=true&w=majority"
   ```

5. Start Ollama (ensure `gemma3:1b` is pulled):

   ```bash
   ollama run gemma3:1b
   ```

6. Run the Backend Server:

   ```bash
   uvicorn main:app --reload
   ```

### 2. Frontend Setup

1. Navigate to the frontend directory:
   ```bash
   cd frontend


2. Install npm dependencies:

   ```bash
   npm install
   ```

3. Run the frontend development server:

   ```bash
   npm start
   ```

## Usage

1. Start both the **backend** and **frontend** servers.  

2. Open your browser and go to:  
   [http://localhost:3000](http://localhost:3000)  

3. Use the dropdown menus to select:  
   - Log source  
   - Ceph version  
   - RHEL version  
   - Test area / build  

4. Click **"Start Analysis"** to trigger the RAG pipeline.  

5. Monitor analysis progress on the dashboard.  

6. Once the report is generated:  
   - View analysis results  
   - Provide feedback (**👍 like**, **👎 dislike**, **⏭️ skip**)  

7. Feedback helps improve system accuracy for future analyses.  
