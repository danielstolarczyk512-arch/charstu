"""Realny test sciezki produkcyjnej: pose_prompt + adapter Sogni (indeksy [-1,-2]): python -m tests.pose_real_check"""
from app import config, prompts
from app.providers.base import GenRequest
from app.providers.sogni import SogniProvider

O = config.DATA / "outputs"
c = {"archetype": "adult huntress", "traits": "silver braided hair", "outfit": "green hooded cloak with leather armor"}
shot = {"az": 0, "el": 5, "dist": 4, "fov": 35, "outfit": ""}
req = GenRequest(kind="edit", prompt=prompts.pose_prompt(c, shot), fmt="16:9", model="qwen",
                 refs=[O / "job5_0.png", O / "exp_poseref_p1_photo.png"], safe_filter=True, idem_key=__import__("uuid").uuid4().hex)
res = SogniProvider().generate(req)
data, ext = res.files[0]
(O / "exp_pose_realcheck.png").write_bytes(data)
print("OK", len(data))
