import React, { useState, useEffect } from 'react';
import axios from 'axios';
function FullLogAnalyzer() {
  // State for dropdown options
  const [sources, setSources] = useState([]);
  const [cephVersions, setCephVersions] = useState([]);
  const [rhelVersions, setRhelVersions] = useState([]);
  const [testAreas, setTestAreas] = useState([]);
  const [buildVersions, setBuildVersions] = useState([]);
  const [jenkinsBuilds, setJenkinsBuilds] = useState([]);
  // State for selected values
  const [source, setSource] = useState('');
  const [cephVersion, setCephVersion] = useState('');
  const [rhelVersion, setRhelVersion] = useState('');
  const [testArea, setTestArea] = useState('');
  const [selectedBuild, setSelectedBuild] = useState('');
  const [jenkinsBuild, setJenkinsBuild] = useState('');
  // State for analysis progress
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState('');
  const [reportId, setReportId] = useState('');
  const [pollingStatus, setPollingStatus] = useState('');
  const [logCount, setLogCount] = useState(null);
  const [failedLogCount, setFailedLogCount] = useState(null);
  const [showIframe, setShowIframe] = useState(false);
  const [analysisComplete, setAnalysisComplete] = useState(false);
  // --- Feedback states ---
  const [logs, setLogs] = useState([]); // Stores all log IDs returned by analysis
  const [feedback, setFeedback] = useState({}); // { log_id: { vote, comment } }
  const [feedbackSubmitted, setFeedbackSubmitted] = useState(false);
  // Fetch initial data
  useEffect(() => {
    axios.get("http://localhost:8000/list-sources")
      .then(res => setSources(res.data))
      .catch(err => console.error("Error fetching sources:", err));
  }, []);
  // Chain dropdown population
  useEffect(() => {
    if (source) {
      axios.get("http://localhost:8000/list-ceph-versions", { params: { source } })
        .then(res => setCephVersions(res.data))
        .catch(err => console.error("Error fetching Ceph versions:", err));
    } else {
      setCephVersions([]);
      setCephVersion('');
    }
  }, [source]);
  useEffect(() => {
    if (source && cephVersion) {
      axios.get("http://localhost:8000/list-rhel-versions", { params: { source, ceph_version: cephVersion } })
        .then(res => setRhelVersions(res.data))
        .catch(err => console.error("Error fetching RHEL versions:", err));
    } else {
      setRhelVersions([]);
      setRhelVersion('');
    }
  }, [source, cephVersion]);
  useEffect(() => {
    if (source && cephVersion && rhelVersion) {
      axios.get("http://localhost:8000/list-test-areas", {
        params: { source, ceph_version: cephVersion, rhel_version: rhelVersion }
      })
        .then(res => setTestAreas(res.data))
        .catch(err => console.error("Error fetching test areas:", err));
    } else {
      setTestAreas([]);
      setTestArea('');
    }
  }, [source, cephVersion, rhelVersion]);
  useEffect(() => {
    if (source && cephVersion && rhelVersion && testArea) {
      axios.get("http://localhost:8000/fetch-builds", {
        params: { source, ceph_version: cephVersion, rhel_version: rhelVersion, test_area: testArea }
      })
        .then(res => setBuildVersions(res.data))
        .catch(err => console.error("Error fetching builds:", err));
    } else {
      setBuildVersions([]);
      setSelectedBuild('');
    }
  }, [source, cephVersion, rhelVersion, testArea]);
  useEffect(() => {
    if (source && cephVersion && rhelVersion && testArea && selectedBuild) {
      axios.get("http://localhost:8000/list-jenkins-builds", {
        params: {
          source,
          ceph_version: cephVersion,
          rhel_version: rhelVersion,
          test_area: testArea,
          build: selectedBuild
        }
      })
        .then(res => setJenkinsBuilds(res.data))
        .catch(err => {
          console.error("Error fetching Jenkins builds:", err);
          setJenkinsBuilds([]);
        });
    } else {
      setJenkinsBuilds([]);
      setJenkinsBuild('');
    }
  }, [source, cephVersion, rhelVersion, testArea, selectedBuild]);
  // --- Analysis Handler ---
  const handleAnalysis = async () => {
    if (!source || !cephVersion || !rhelVersion || !testArea || !selectedBuild || !jenkinsBuild) {
      alert("Please select all dropdown options");
      return;
    }
    setLoading(true);
    setResult('');
    setPollingStatus('');
    setLogCount(null);
    setFailedLogCount(null);
    setShowIframe(false);
    setAnalysisComplete(false);
    setFeedbackSubmitted(false);
    setFeedback({});
    setLogs([]);
    try {
      const response = await axios.post("http://localhost:8000/start-analysis", {
        source,
        ceph_version: cephVersion,
        rhel_version: rhelVersion,
        test_area: testArea,
        build: selectedBuild,
        jenkins_build: jenkinsBuild
      });
      setReportId(response.data.report_id);
    } catch (err) {
      let errorMessage = 'Error running analysis';
      if (err.response) {
        errorMessage += `: ${err.response.data.error || err.response.status}`;
      } else if (err.request) {
        errorMessage += ": Could not reach server";
      }
      setResult(`❌ ${errorMessage}`);
      setLoading(false);
    }
  };
  // Poll for progress updates
  useEffect(() => {
    if (!reportId) return;
    const interval = setInterval(async () => {
      try {
        const res = await axios.get(`http://localhost:8000/progress/${reportId}`);
        setPollingStatus(res.data.status);
        setLogCount(res.data.total_logs || 0);
        setFailedLogCount(res.data.failed_logs || 0);
        // Save logs IDs for feedback
        if (res.data.logs) {
          setLogs(res.data.logs); // expecting array of log_ids
          const initialFeedback = {};
          res.data.logs.forEach(log => {
            initialFeedback[log] = { vote: '', comment: '' };
          });
          setFeedback(initialFeedback);
        }
        if (res.data.status.includes("✅ Analysis complete")) {
          clearInterval(interval);
          setResult("✅ Report Ready");
          setAnalysisComplete(true);
          setLoading(false);
        } else if (res.data.status.startsWith("❌") || res.data.status.startsWith("⚠️")) {
          clearInterval(interval);
          setResult(res.data.status);
          setLoading(false);
        }
      } catch (err) {
        clearInterval(interval);
        setResult("❌ Error checking progress");
        setLoading(false);
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [reportId]);
  const handleViewReport = () => {
    if (!analysisComplete) {
      alert("Please wait for analysis to complete");
      return;
    }
    setShowIframe(true);
  };
  // --- Feedback Handlers ---
  const handleFeedbackChange = (logId, field, value) => {
    setFeedback(prev => ({
      ...prev,
      [logId]: { ...prev[logId], [field]: value }
    }));
  };
  const handleFeedbackSubmit = async () => {
    try {
      await axios.post("http://localhost:8000/submit-feedback", feedback);
      setFeedbackSubmitted(true);
    } catch (err) {
      alert("Error submitting feedback");
      console.error(err);
    }
  };
  return (
    <div style={{ maxWidth: '1200px', margin: '0 auto', padding: '2rem', fontFamily: 'Arial, sans-serif' }}>
      <h1 style={{ textAlign: 'center', color: '#2c3e50', marginBottom: '2rem' }}>CephCI Log Analyzer</h1>
      {/* Selection Form */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
        gap: '1rem',
        marginBottom: '2rem',
        padding: '1.5rem',
        backgroundColor: '#fff',
        borderRadius: '8px',
        boxShadow: '0 2px 4px rgba(0,0,0,0.1)'
      }}>
        {[
          { label: "Source", value: source, setValue: setSource, options: sources },
          { label: "Ceph Version", value: cephVersion, setValue: setCephVersion, options: cephVersions },
          { label: "RHEL Version", value: rhelVersion, setValue: setRhelVersion, options: rhelVersions },
          { label: "Test Area", value: testArea, setValue: setTestArea, options: testAreas },
          { label: "Build Version", value: selectedBuild, setValue: setSelectedBuild, options: buildVersions },
          { label: "Jenkins Build", value: jenkinsBuild, setValue: setJenkinsBuild, options: jenkinsBuilds }
        ].map((field, idx) => (
          <div key={idx}>
            <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: '600', color: '#34495e' }}>
              {field.label}:
            </label>
            <select
              value={field.value}
              onChange={(e) => field.setValue(e.target.value)}
              style={{ width: '100%', padding: '0.6rem', borderRadius: '4px', border: '1px solid #ddd', backgroundColor: '#fff' }}
            >
              <option value="">Select {field.label}</option>
              {Array.isArray(field.options) && field.options.map((opt, i) => (
                <option key={i} value={opt}>{opt}</option>
              ))}
            </select>
          </div>
        ))}
      </div>
      {/* Analysis Button */}
      <div style={{ textAlign: 'center', marginBottom: '2rem' }}>
        <button
          onClick={handleAnalysis}
          disabled={loading}
          style={{
            padding: '0.8rem 2rem',
            fontSize: '1rem',
            backgroundColor: loading ? '#95a5a6' : '#3498db',
            color: '#fff',
            border: 'none',
            borderRadius: '6px',
            cursor: 'pointer',
            fontWeight: '600',
            minWidth: '200px'
          }}
        >
          {loading ? 'Analyzing...' : 'Start Analysis'}
        </button>
      </div>
      {/* Status Display */}
      {(logCount !== null || failedLogCount !== null) && (
        <div style={{ margin: '1rem auto', padding: '1rem', backgroundColor: '#e8f4f8', borderRadius: '6px', textAlign: 'center', maxWidth: '500px' }}>
          <div style={{ marginBottom: '0.5rem' }}>
            <span style={{ fontWeight: '600', color: '#3498db' }}>Total Logs:</span> {logCount}
            <span style={{ marginLeft: '1rem', fontWeight: '600', color: '#e74c3c' }}>Failed Logs:</span> {failedLogCount}
          </div>
          {pollingStatus && (
            <div style={{ fontStyle: 'italic', color: '#7f8c8d' }}>
              {pollingStatus}
            </div>
          )}
        </div>
      )}
      {/* Results Section */}
      {result && (
        <div style={{
          margin: '2rem auto',
          padding: '1.5rem',
          backgroundColor: result.includes('✅') ? '#e8f8ef' : '#fde8e8',
          borderRadius: '8px',
          textAlign: 'center',
          maxWidth: '600px',
          border: `1px solid ${result.includes('✅') ? '#2ecc71' : '#e74c3c'}`
        }}>
          <h3 style={{ color: result.includes('✅') ? '#27ae60' : '#c0392b', marginBottom: '1.5rem' }}>
            {result}
          </h3>
          <div style={{ display: 'flex', justifyContent: 'center', gap: '1rem', flexWrap: 'wrap' }}>
            <button
              onClick={handleViewReport}
              style={{
                padding: '0.6rem 1.2rem',
                backgroundColor: '#2ecc71',
                color: '#fff',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer',
                fontWeight: '500'
              }}
            >
              View Report
            </button>
            <a
              href={`http://localhost:8000/download-report/${reportId}`}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                padding: '0.6rem 1.2rem',
                backgroundColor: '#3498db',
                color: '#fff',
                border: 'none',
                borderRadius: '4px',
                textDecoration: 'none',
                fontWeight: '500'
              }}
            >
              Download Report
            </a>
          </div>
        </div>
      )}
      {/* Feedback Section */}
      {analysisComplete && logs.length > 0 && (
        <div style={{ marginTop: '2rem', padding: '1rem', backgroundColor: '#f4f6f7', borderRadius: '8px' }}>
          <h2 style={{ textAlign: 'center', marginBottom: '1rem', color: '#2c3e50' }}>Submit Feedback</h2>
          {logs.map(logId => (
            <div key={logId} style={{ marginBottom: '1rem', padding: '0.8rem', backgroundColor: '#fff', borderRadius: '6px', border: '1px solid #ddd' }}>
              <p><strong>{logId}</strong></p>
              <select
                value={feedback[logId]?.vote || ''}
                onChange={e => handleFeedbackChange(logId, 'vote', e.target.value)}
                style={{ marginRight: '1rem', padding: '0.4rem', borderRadius: '4px', border: '1px solid #ccc' }}
              >
                <option value="">Select Vote</option>
                <option value="like">Like</option>
                <option value="dislike">Dislike</option>
              </select>
              <input
                type="text"
                placeholder="Comment"
                value={feedback[logId]?.comment || ''}
                onChange={e => handleFeedbackChange(logId, 'comment', e.target.value)}
                style={{ padding: '0.4rem', borderRadius: '4px', border: '1px solid #ccc', width: '60%' }}
              />
            </div>
          ))}
          <div style={{ textAlign: 'center', marginTop: '1rem' }}>
            <button
              onClick={handleFeedbackSubmit}
              disabled={feedbackSubmitted}
              style={{
                padding: '0.6rem 1.2rem',
                backgroundColor: feedbackSubmitted ? '#95a5a6' : '#3498db',
                color: '#fff',
                border: 'none',
                borderRadius: '6px',
                fontWeight: '600',
                cursor: feedbackSubmitted ? 'default' : 'pointer'
              }}
            >
              {feedbackSubmitted ? 'Feedback Submitted' : 'Submit Feedback'}
            </button>
          </div>
        </div>
      )}
      {/* Report Viewer */}
      {showIframe && analysisComplete && (
        <div style={{ marginTop: '2rem', border: '1px solid #ddd', borderRadius: '8px', overflow: 'hidden', boxShadow: '0 3px 10px rgba(0,0,0,0.1)' }}>
          <iframe
            src={`http://localhost:8000/view-report/${reportId}`}
            title="Analysis Report"
            width="100%"
            height="700px"
            style={{ border: 'none' }}
          />
        </div>
      )}
    </div>
  );
}
export default FullLogAnalyzer;

