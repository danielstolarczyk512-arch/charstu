"""Test opisow pozy i ruchu przez dzialajacy program: STUDIO_URL=... python -m tests.pose_experiment images|clips"""
import json
import os
import sys
import time

import httpx

c = httpx.Client(base_url=os.getenv("STUDIO_URL", "http://localhost:8001"), timeout=120)
CID = int(os.getenv("CHAR_ID", "2"))
POSES = {
    "sit": "sits on a large rock with her elbows on her knees, looking at the ground",
    "kneel": "kneels on one knee and touches the ground with her right hand",
    "bow": "draws a longbow, her arm fully extended, aiming at something off-screen",
    "arms": "stands with her arms crossed over her chest and one leg slightly forward",
    "run": "runs towards the camera, mid-stride, her cloak flying behind her",
    "reach": "reaches up with her left hand to grab a branch above her head",
}


def wait(ids, timeout=900):
    end = time.time() + timeout
    while time.time() < end:
        js = {j["id"]: j for j in c.get(f"/api/jobs?character_id={CID}").json()}
        if all(js[i]["status"] in ("done", "failed") for i in ids):
            return js
        time.sleep(5)
    return js


if sys.argv[1] == "images":
    jobs = {}
    for name, action in POSES.items():
        sid = c.post("/api/shots", json={"character_id": CID, "az": 40, "el": 5, "dist": 5.5, "fov": 35, "fmt": "16:9",
                                         "action": action}).json()["id"]
        r = c.post(f"/api/shots/{sid}/generate", json={"kind": "image", "count": 1}).json()
        jobs[name] = r["jobs"][0]
    js = wait(list(jobs.values()))
    arts = {a["job_id"]: a for a in c.get("/api/artifacts?character_id=%d" % CID).json()}
    out = {n: (arts[j]["id"], arts[j]["path"]) if j in arts else None for n, j in jobs.items()}
    print(json.dumps({"jobs": jobs, "artifacts": out, "status": {n: js[j]["status"] for n, j in jobs.items()}}, indent=1))
else:
    spec = json.loads(sys.argv[2])   # {"name": [artifact_id, "action text"]}
    jobs = {}
    for name, (aid, action) in spec.items():
        sid = c.post("/api/shots", json={"character_id": CID, "az": 40, "el": 5, "dist": 5.5, "fov": 35, "fmt": "16:9",
                                         "action": action}).json()["id"]
        r = c.post(f"/api/shots/{sid}/generate", json={"kind": "video", "source_artifact_id": aid})
        jobs[name] = r.json()["jobs"][0]
    js = wait(list(jobs.values()))
    arts = {a["job_id"]: a for a in c.get("/api/artifacts?character_id=%d" % CID).json()}
    print(json.dumps({n: (arts[j]["path"] if j in arts else js[j]["error"]) for n, j in jobs.items()}, indent=1))
