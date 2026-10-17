"""Eksperyment 2: obraz pozy jako BAZA (1. obraz), kanon jako osoba (2. obraz): python -m tests.pose_ref_experiment2"""
import uuid

from app import config
from app.providers.sogni import SogniProvider

O = config.DATA / "outputs"
p = SogniProvider()
canon = O / "job5_0.png"
photo = O / "exp_poseref_p1_photo.png"
stick = O / "exp_poseref_p2_stick.png"

PROMPT = ("Replace the person in the first image with the woman from the second image. Keep the exact body pose, composition and "
          "camera angle of the first image. Use the face, silver braided hair and green hooded cloak with leather armor of the "
          "woman from the second image. Only one person is visible.")


def run(name, refs, prompt):
    media = [{"kind": "image", "url": p._upload_image(r, f"contextImage{i + 1}", str(uuid.uuid4()))} for i, r in enumerate(refs)]
    step = {"id": "s1", "toolName": "edit_image", "arguments": {"prompt": prompt, "model": "krea-identity-edit", "aspectRatio": "16:9",
                                                                  "contextImageIndices": [-1, -2]}}
    body = {"input": {"title": "poseref2-" + name, "steps": [step]}, "billing_mode": "subscription", "app_source": "character-studio",
            "safe_content_filter": True, "confirm_cost": True, "media_references": media}
    r = p._call("POST", "/v1/creative-agent/workflows", json=body, headers={"Idempotency-Key": str(uuid.uuid4())})
    wf = p._poll(r.json()["data"]["workflow"]["workflowId"], 300)
    u = [a["url"] for st in wf["steps"] for a in st.get("artifacts", []) if a.get("url")][0]
    (O / f"exp_poseref2_{name}.png").write_bytes(p.plain.get(u).content)
    print(name, "OK", flush=True)


run("photo_base", [photo, canon], PROMPT)
run("stick_base", [stick, canon], PROMPT)
