"""Eksperyment 3: Qwen Image Edit + szkielet OpenPose jako druga referencja: python -m tests.pose_ref_experiment3"""
import uuid

from app import config, skeleton
from app.providers.sogni import SogniProvider

O = config.DATA / "outputs"
p = SogniProvider()
canon = O / "job5_0.png"
photo = O / "exp_poseref_p1_photo.png"

# szkielet: klek z uniesionymi rekami (jak na zdjeciu wojownika) oraz presety "siedzi" i "luk"
sk_kneel = O / "exp_pose_skel_klek.png"
sk_sit = O / "exp_pose_skel_siedzi.png"
sk_bow = O / "exp_pose_skel_luk.png"
for name, path in (("klek", sk_kneel), ("siedzi", sk_sit), ("luk", sk_bow)):
    skeleton.render(skeleton.PRESETS[name], (1280, 720)).save(path)

PROMPT_SK = ("The woman in the first image takes the exact body pose shown by the skeleton figure in the second image. Keep her "
             "face, silver braided hair, green hooded cloak, leather armor and the cliff background from the first image. "
             "Do not draw the skeleton. Only one person is visible.")
PROMPT_PH = ("The woman in the first image takes the same body pose as the man in the second image. Keep her face, silver braided "
             "hair, green hooded cloak, leather armor and the cliff background from the first image. Only one person is visible.")


def run(name, refs, prompt, model="qwen"):
    media = [{"kind": "image", "url": p._upload_image(r, f"contextImage{i + 1}", str(uuid.uuid4()))} for i, r in enumerate(refs)]
    step = {"id": "s1", "toolName": "edit_image", "arguments": {"prompt": prompt, "model": model, "aspectRatio": "16:9",
                                                                  "contextImageIndices": [-1, -2]}}
    body = {"input": {"title": "poseref3-" + name, "steps": [step]}, "billing_mode": "subscription", "app_source": "character-studio",
            "safe_content_filter": True, "confirm_cost": True, "media_references": media}
    r = p._call("POST", "/v1/creative-agent/workflows", json=body, headers={"Idempotency-Key": str(uuid.uuid4())})
    wf = p._poll(r.json()["data"]["workflow"]["workflowId"], 420)
    u = [a["url"] for st in wf["steps"] for a in st.get("artifacts", []) if a.get("url")][0]
    (O / f"exp_poseref3_{name}.png").write_bytes(p.plain.get(u).content)
    print(name, "OK", flush=True)


run("qwen_photo", [canon, photo], PROMPT_PH)
run("qwen_skel_klek", [canon, sk_kneel], PROMPT_SK)
run("qwen_skel_siedzi", [canon, sk_sit], PROMPT_SK)
run("qwen_skel_luk", [canon, sk_bow], PROMPT_SK)
