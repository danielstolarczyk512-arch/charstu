"""Eksperyment 4: dwa kroki - (A) Qwen przenosi poze (hybryda), (B) Krea restage: osoba z kanonu w tej pozie.
python -m tests.pose_ref_experiment4"""
import uuid

from app import config
from app.providers.sogni import SogniProvider

O = config.DATA / "outputs"
p = SogniProvider()
canon = O / "job5_0.png"
hybrid = O / "exp_poseref3_qwen_photo.png"

PROMPT = ("Replace the person in the first image with the woman from the second image. Keep the exact body pose, the raised sword "
          "and the composition of the first image. Use the face, silver braided hair and the green hooded cloak with leather armor "
          "of the woman from the second image. Only one person is visible.")


def run(name, refs, prompt, model):
    media = [{"kind": "image", "url": p._upload_image(r, f"contextImage{i + 1}", str(uuid.uuid4()))} for i, r in enumerate(refs)]
    step = {"id": "s1", "toolName": "edit_image", "arguments": {"prompt": prompt, "model": model, "aspectRatio": "16:9",
                                                                  "contextImageIndices": [-1, -2]}}
    body = {"input": {"title": "poseref4-" + name, "steps": [step]}, "billing_mode": "subscription", "app_source": "character-studio",
            "safe_content_filter": True, "confirm_cost": True, "media_references": media}
    r = p._call("POST", "/v1/creative-agent/workflows", json=body, headers={"Idempotency-Key": str(uuid.uuid4())})
    wf = p._poll(r.json()["data"]["workflow"]["workflowId"], 420)
    u = [a["url"] for st in wf["steps"] for a in st.get("artifacts", []) if a.get("url")][0]
    (O / f"exp_poseref4_{name}.png").write_bytes(p.plain.get(u).content)
    print(name, "OK", flush=True)


run("krea_restage", [hybrid, canon], PROMPT, "krea-identity-edit")
run("qwen_restage", [hybrid, canon], PROMPT, "qwen")
