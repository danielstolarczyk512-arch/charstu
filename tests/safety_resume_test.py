"""Test wznawiania po safety_review_required (B1) z atrapa HTTP, bez konta: python -m tests.safety_resume_test

Sprawdza logike _poll, a NIE prawdziwe zachowanie /resume u Sogni (format odpowiedzi /resume niezweryfikowany renderem)."""
import os
import tempfile

os.environ["STUDIO_DATA"] = tempfile.mkdtemp(prefix="studio-safety-")
os.environ["PROVIDER"] = "mock"
os.environ["SOGNI_API_KEY"] = "test-key-nieprawdziwy"
os.environ["SAFETY_RESUME_ATTEMPTS"] = "2"

from app.providers import sogni  # noqa: E402
from app.providers.base import ProviderError, SafetyRejected  # noqa: E402

sogni.time.sleep = lambda *_a, **_k: None   # bez czekania w testach

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" | " + detail) if detail else ""), flush=True)


class Resp:
    def __init__(self, code, data=None):
        self.status_code, self._d, self.content, self.headers = code, data or {}, b"x", {}

    def json(self):
        return self._d


def wf(status, reason=None):
    w = {"status": status, "steps": [], "events": []}
    if reason:
        w["waitingReason"] = reason
    return Resp(200, {"data": {"workflow": w}})


def make(sequence, resume_code=200):
    """Dostawca z atrapa _call: GET zwraca kolejne stany, POST /resume jest zapisywany."""
    p = sogni.SogniProvider()
    calls = {"resume": [], "get": 0}
    seq = list(sequence)

    def fake(method, path, retries=4, **kw):
        if method == "POST" and path.endswith("/resume"):
            calls["resume"].append((path, kw.get("json")))
            return Resp(resume_code)
        calls["get"] += 1
        return seq.pop(0) if len(seq) > 1 else seq[0]
    p._call = fake
    return p, calls


# 1. jedno wstrzymanie, po wznowieniu zadanie konczy sie
p, calls = make([wf("waiting_for_user", "safety_review_required"), wf("running"), wf("completed")])
out = p._poll("w1", 60)
check("1 wznowienie po safety_review_required i dokonczenie", out["status"] == "completed" and len(calls["resume"]) == 1,
      str(calls["resume"]))
check("2 /resume dostaje safe_content_filter=false", calls["resume"][0][1] == {"safe_content_filter": False}
      and calls["resume"][0][0] == "/v1/creative-agent/workflows/w1/resume")

# 3. wstrzymanie nie schodzi: dokladnie 2 wznowienia, potem SafetyRejected z czytelnym komunikatem
p, calls = make([wf("waiting_for_user", "safety_review_required")])
try:
    p._poll("w2", 60)
    err = None
except SafetyRejected as e:
    err = str(e)
check("3 po 2 probach SafetyRejected", err is not None and len(calls["resume"]) == 2, str(len(calls["resume"])))
check("4 komunikat zawiera przyczyne i limit", err and "safety_review_required" in err and "2" in err and "SAFETY_REJECTED" in err)

# 5. inny powod wstrzymania nie jest wznawiany
p, calls = make([wf("waiting_for_user", "permission_required")])
try:
    p._poll("w3", 60)
    err = None
except ProviderError as e:
    err = e
check("5 inny waitingReason: blad bez wznawiania", isinstance(err, ProviderError) and not isinstance(err, SafetyRejected)
      and not calls["resume"])

# 6. zwykla odmowa (status failed) nie jest ponawiana
p, calls = make([wf("failed")])
try:
    p._poll("w4", 60)
    err = None
except ProviderError as e:
    err = e
check("6 status failed: blad, brak wznowien", err is not None and not isinstance(err, SafetyRejected) and not calls["resume"])

# 7. /resume odrzucone przez serwer -> SafetyRejected bez petli
p, calls = make([wf("waiting_for_user", "safety_review_required")], resume_code=403)
try:
    p._poll("w5", 60)
    err = None
except SafetyRejected as e:
    err = e
check("7 odrzucone /resume: SafetyRejected od razu", err is not None and len(calls["resume"]) == 1)

# 8. karencja po /resume: stan jeszcze kilka odpytan zostaje "safety_review_required" (zachowanie zmierzone sonda), potem completed
hold = wf("waiting_for_user", "safety_review_required")
p, calls = make([hold, hold, hold, hold, hold, wf("completed")])
out = p._poll("w6", 60)
check("8 po /resume stan trzyma sie kilka odpytan: tylko 1 wznowienie, zadanie konczy sie",
      out["status"] == "completed" and len(calls["resume"]) == 1, str(len(calls["resume"])))

print(f"\nWYNIK: {sum(results)}/{len(results)}")
raise SystemExit(0 if all(results) else 1)
