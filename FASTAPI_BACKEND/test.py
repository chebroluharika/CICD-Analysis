from fastapi import BackgroundTasks
from main import run_analysis, AnalysisRequest

data = AnalysisRequest(
    source="jenkins",
    ceph_version="8.1",
    rhel_version="rhel-9.6",
    test_area="RGW",
    build="870",
    jenkins_build="19.2.1-245.1.hotfix.bz2375001/"
)
bt = BackgroundTasks()


result = run_analysis(data, "95d738f6-e79d-4ae1-892e-66a7a7a665c7")
print(result)
