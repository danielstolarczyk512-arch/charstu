"""B3: czy dark-beast-krea2-identity-edit przenosi poze z drugiego obrazu? 2 rendery (zdjecie pozy w dwoch kolejnosciach
referencji), te same dane co pose_ref_experiment3 (Qwen przenosil). python -m tests.pose_dark_beast_experiment"""
import uuid

from app import config
from app.providers.sogni import SogniProvider

O = config.DATA / "outputs"
p = SogniProvider()
canon = O / "job5_0.png"
photo = O / "exp_poseref_p1_photo.png"
MODEL = "dark-beast-krea2-identity-edit"
PROMPT = ("The woman in the first image takes the same body pose as the man in the second image. Keep her face, silver braided "
          "hair, green hooded cloak, leather armor and the cliff background from the first image. Only one person is visible.")


def usage():
    r = p._call("GET", "/v1/subscriptions/usage")
    return r.json()["data"]["usage"]["value"]["daily"]["renderSpark"]


def run(name, refs, prompt):
    media = [{"kind": "image", "url": p._upload_image(r, f"contextImage{i + 1}", str(uuid.uuid4()))} for i, r in enumerate(refs)]
    step = {"id": "s1", "toolName": "edit_image", "arguments": {"prompt": prompt, "model": MODEL, "aspectRatio": "16:9",
                                                                  "contextImageIndices": [-1, -2]}}
    body = {"input": {"title": "pose-db-" + name, "steps": [step]}, "billing_mode": config.SOGNI_BILLING_MODE,
            "app_source": "character-studio", "safe_content_filter": False, "confirm_cost": True, "media_references": media}
    r = p._call("POST", "/v1/creative-agent/workflows", json=body, headers={"Idempotency-Key": str(uuid.uuid4())})
    if r.status_code not in (200, 201, 202):
        print(name, "BLAD", p._err(r)); return
    wid = r.json()["data"]["workflow"]["workflowId"]
    try:
        wf = p._poll(wid, 420)
    except Exception as e:  # noqa: BLE001
        g = p._call("GET", f"/v1/creative-agent/workflows/{wid}").json()["data"]["workflow"]
        print(name, "BLAD:", e, {k: g.get(k) for k in ("status", "waitingReason")}, p._last_message(g)); return
    u = [a["url"] for st in wf["steps"] for a in st.get("artifacts", []) if a.get("url")][0]
    (O / f"exp_pose_db_{name}.png").write_bytes(p.plain.get(u).content)
    print(name, "OK", flush=True)


u0 = usage()
run("canon_first", [canon, photo], PROMPT)
run("pose_first", [photo, canon], PROMPT.replace("first image", "TMP").replace("second image", "first image").replace("TMP", "second image"))
print("zuzycie Spark:", round(usage() - u0, 2), "zadan: 2")
