"""Eksperyment: poza jako druga referencja Krea Identity Edit: python -m tests.pose_ref_experiment"""
import io
import uuid

from PIL import Image, ImageDraw

from app import config
from app.providers.base import GenRequest
from app.providers.sogni import SogniProvider

O = config.DATA / "outputs"
p = SogniProvider()
canon = O / "job5_0.png"


def gen_text(prompt, name):
    res = p.generate(GenRequest(kind="image", prompt=prompt, fmt="16:9", model="krea-2-turbo", idem_key=str(uuid.uuid4())))
    path = O / f"exp_poseref_{name}.png"
    path.write_bytes(res.files[0][0])
    return path


# P1: zdjecie innej, fikcyjnej doroslej postaci w wyraznej pozie
p1 = gen_text("a fictional adult male warrior in a low crouching stance, one knee almost touching the ground, "
              "both hands holding a sword raised high above his head, full body, plain grey studio background", "p1_photo")

# P2: prosty rysunek szkieletu w tej samej pozie (kreski)
img = Image.new("RGB", (1280, 720), (235, 235, 235))
d = ImageDraw.Draw(img)
W = 10
pts = {"head": (640, 150), "neck": (640, 200), "hip": (640, 400), "lknee": (560, 480), "lfoot": (500, 600),
       "rknee": (720, 540), "rfoot": (740, 640), "lhand": (600, 60), "rhand": (690, 60), "lelb": (590, 130), "relb": (700, 130),
       "lsh": (600, 210), "rsh": (680, 210)}
for a, b in (("neck", "hip"), ("hip", "lknee"), ("lknee", "lfoot"), ("hip", "rknee"), ("rknee", "rfoot"), ("neck", "lsh"),
             ("neck", "rsh"), ("lsh", "lelb"), ("lelb", "lhand"), ("rsh", "relb"), ("relb", "rhand")):
    d.line([pts[a], pts[b]], fill=(30, 30, 30), width=W)
d.ellipse([610, 110, 670, 190], outline=(30, 30, 30), width=W)
p2 = O / "exp_poseref_p2_stick.png"
img.save(p2)

PROMPT = ("Show the same character from the first reference image, in the same body pose as the figure in the second reference "
          "image. Keep her face, hairstyle, outfit and the scene from the first reference image. Do not copy the person, "
          "clothing or background of the second reference image. Only one person is visible.")


def edit(refs, order, name):
    media = [{"kind": "image", "url": p._upload_image(r, f"contextImage{i + 1}", str(uuid.uuid4()))} for i, r in enumerate(refs)]
    config.SOGNI_EDIT_REF_ARG = "contextImageIndices"
    # order A: [-1,-2] (zgodnie z dokumentacja: -1 = pierwszy wgrany); order B: [-2,-1] (stary kod adaptera)
    idx = [-1, -2] if order == "A" else [-2, -1]
    step = {"id": "s1", "toolName": "edit_image", "arguments": {"prompt": PROMPT, "model": "krea-identity-edit", "aspectRatio": "16:9",
                                                                  "contextImageIndices": idx}}
    body = {"input": {"title": "poseref-" + name, "steps": [step]}, "billing_mode": "subscription", "app_source": "character-studio",
            "safe_content_filter": True, "confirm_cost": True, "media_references": media}
    import uuid as _u
    r = p._call("POST", "/v1/creative-agent/workflows", json=body, headers={"Idempotency-Key": str(_u.uuid4())})
    wf = p._poll(r.json()["data"]["workflow"]["workflowId"], 900)
    u = [a["url"] for st in wf["steps"] for a in st.get("artifacts", []) if a.get("url")][0]
    out = O / f"exp_poseref_{name}.png"
    out.write_bytes(p.plain.get(u).content)
    print(name, "OK", flush=True)


edit([canon, p1], "A", "r1_photo_orderA")
edit([canon, p1], "B", "r2_photo_orderB")
edit([canon, p2], "A", "r3_stick_orderA")
