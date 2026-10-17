"""Test dymny calego przeplywu na dostawcy mock: python -m tests.smoke"""
import io
import os
import tempfile
import time

os.environ["STUDIO_DATA"] = tempfile.mkdtemp(prefix="studio-test-")
os.environ["PROVIDER"] = "mock"

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402


def png() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (64, 64), (120, 80, 200)).save(b, "PNG")
    return b.getvalue()


def wait(c, cid, n, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        jobs = c.get(f"/api/jobs?character_id={cid}").json()
        if len(jobs) >= n and all(j["status"] in ("done", "failed") for j in jobs):
            return jobs
        time.sleep(0.5)
    raise AssertionError("timeout")


with TestClient(app) as c:
    # 1. blokada: postac musi byc fikcyjna i dorosla
    r = c.post("/api/characters", json={"name": "X", "adult_fictional": False})
    assert r.status_code == 400, r.text

    ch = c.post("/api/characters", json={"name": "Aria", "archetype": "huntress", "traits": "silver hair",
                                         "outfit": "green cloak", "style": "cinematic", "adult_fictional": True}).json()
    cid = ch["id"]

    # 2. obraz bez kanonu -> generate_image (kind=image)
    shot = c.post("/api/shots", json={"character_id": cid, "az": 40, "el": 5, "dist": 4, "fov": 35,
                                      "fmt": "16:9", "action": "stands on a rooftop"}).json()
    g = c.post(f"/api/shots/{shot['id']}/generate", json={"kind": "image", "count": 2}).json()
    assert g["kind"] == "image" and g["refs"] == [], g
    jobs = wait(c, cid, 2)
    assert all(j["status"] == "done" for j in jobs), jobs
    arts = c.get(f"/api/artifacts?character_id={cid}").json()
    assert len(arts) == 2 and c.get("/files/" + arts[0]["path"]).status_code == 200

    # 3. kanon: twarz + zatwierdzenie wyniku -> kolejne obrazy ida jako edit z referencjami
    up = c.post(f"/api/characters/{cid}/canon", data={"role": "face", "tier": "main"},
                files={"file": ("face.png", png(), "image/png")})
    assert up.status_code == 200, up.text
    assert c.post(f"/api/artifacts/{arts[0]['id']}/approve", data={"role": "three_quarter"}).status_code == 200
    cov = c.get(f"/api/coverage?character_id={cid}").json()
    assert cov["face"] and cov["three_quarter"] and not cov["back"], cov

    shot2 = c.post("/api/shots", json={"character_id": cid, "az": 180, "el": 5, "dist": 4, "fov": 35,
                                       "fmt": "9:16", "action": "walks away"}).json()
    g2 = c.post(f"/api/shots/{shot2['id']}/generate", json={"kind": "image"}).json()
    assert g2["kind"] == "edit" and len(g2["refs"]) >= 1, g2

    # 4. klip z zatwierdzonego obrazu
    g3 = c.post(f"/api/shots/{shot['id']}/generate", json={"kind": "video", "source_artifact_id": arts[0]["id"]}).json()
    jobs = wait(c, cid, 4)
    assert all(j["status"] == "done" for j in jobs), [(j["id"], j["status"], j["error"]) for j in jobs]
    vids = [a for a in c.get(f"/api/artifacts?character_id={cid}").json() if a["kind"] == "video"]
    assert vids and c.get("/files/" + vids[0]["path"]).status_code == 200

    # 5. limit prob na ujecie
    for _ in range(3):
        r = c.post(f"/api/shots/{shot['id']}/generate", json={"kind": "image", "count": 2})
    assert r.status_code == 409, r.status_code

    print("SMOKE OK:", len(jobs), "zadan,", len(vids), "klip")
