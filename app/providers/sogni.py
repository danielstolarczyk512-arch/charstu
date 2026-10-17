"""Adapter Sogni napisany z dokumentacji (docs.sogni.ai/api-reference). NIE TESTOWANY na zywym koncie.

Pola oznaczone UNVERIFIED nie sa opisane w dokumentacji - sprawdz je w Etapie 0.
"""
import mimetypes
import random
import time
import uuid
from pathlib import Path

import httpx

from .. import config
from .base import GenRequest, GenResult, Provider, ProviderError, SafetyRejected

BASE = "https://api.sogni.ai"
TERMINAL = {"completed", "partial_failure", "failed", "cancelled"}
UA = "character-studio/0.1"
RESUME_GRACE_POLLS = 10   # tyle odpytan (po 4 s) czekamy po /resume, zanim uznamy wznowienie za nieudane


class SogniProvider(Provider):
    name = "sogni"

    def __init__(self):
        if not config.SOGNI_API_KEY:
            raise ProviderError("Brak SOGNI_API_KEY w .env")
        self.http = httpx.Client(
            base_url=BASE, timeout=60,
            headers={"Authorization": f"Bearer {config.SOGNI_API_KEY}", "User-Agent": UA})
        self.plain = httpx.Client(timeout=300, headers={"User-Agent": UA})

    # --- pomocnicze ---------------------------------------------------------------
    def _call(self, method, path, retries=4, **kw):
        delay = 2.0
        for attempt in range(retries + 1):
            try:
                r = self.http.request(method, path, **kw)
            except httpx.TransportError as e:
                if attempt == retries:
                    raise ProviderError(f"Siec: {e}") from e
                time.sleep(delay + random.random())
                delay *= 2
                continue
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                wait = float(r.headers.get("Retry-After") or delay)
                time.sleep(wait + random.random())
                delay *= 2
                continue
            return r
        raise ProviderError("Wyczerpano ponowienia")

    @staticmethod
    def _err(r: httpx.Response) -> str:
        try:
            j = r.json()
            return f"HTTP {r.status_code}: {j.get('message') or j.get('error') or j}"
        except Exception:
            return f"HTTP {r.status_code}: {r.text[:200]}"

    def _upload_image(self, path: Path, type_: str, job_id: str) -> str:
        """Wgrywa obraz i zwraca podpisany URL do pobrania (do media_references)."""
        ctype = mimetypes.guess_type(path.name)[0] or "image/png"
        q = {"type": type_, "jobId": job_id, "contentType": ctype}
        r = self._call("GET", "/v1/image/uploadUrl", params=q)
        if r.status_code != 200:
            raise ProviderError("uploadUrl " + self._err(r))
        put = self.plain.put(r.json()["data"]["uploadUrl"], content=path.read_bytes(),
                             headers={"Content-Type": ctype})
        if put.status_code != 200:
            raise ProviderError(f"PUT obrazu: HTTP {put.status_code}")
        r = self._call("GET", "/v1/image/downloadUrl", params=q)
        if r.status_code != 200:
            raise ProviderError("downloadUrl " + self._err(r))
        return r.json()["data"]["downloadUrl"]

    def _upload_media(self, path: Path, type_: str, job_id: str) -> str:
        """Wgrywa plik audio/wideo (GET /v1/media/uploadUrl -> PUT -> GET /v1/media/downloadUrl)."""
        ctype = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".flac": "audio/flac", ".m4a": "audio/mp4"}.get(
            path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "audio/wav"
        q = {"type": type_, "jobId": job_id, "contentType": ctype}
        r = self._call("GET", "/v1/media/uploadUrl", params=q)
        if r.status_code != 200:
            raise ProviderError("media uploadUrl " + self._err(r))
        put = self.plain.put(r.json()["data"]["uploadUrl"], content=path.read_bytes(), headers={"Content-Type": ctype})
        if put.status_code != 200:
            raise ProviderError(f"PUT audio: HTTP {put.status_code}")
        r = self._call("GET", "/v1/media/downloadUrl", params=q)
        if r.status_code != 200:
            raise ProviderError("media downloadUrl " + self._err(r))
        return r.json()["data"]["downloadUrl"]

    # --- budowa planu ---------------------------------------------------------------
    def _plan(self, req: GenRequest):
        job_id = str(uuid.uuid4())
        media = []
        if req.kind == "image":
            # aspectRatio zweryfikowane testem: "16:9" -> 1280x720 (domyslnie 1024x1024)
            args = {"prompt": req.prompt, "model": req.model or config.IMAGE_MODEL,
                    "aspectRatio": req.fmt, **config.SOGNI_IMAGE_ARGS}
            step = {"id": "s1", "toolName": "generate_image", "arguments": args}
        elif req.kind == "music":
            # generate_music: domyslnie MiniMax Music 3 (10-300 s; dlugosc to gorny limit). Tempo/tonacje wpisz w prompcie.
            args = {"prompt": req.prompt, "duration": max(10, min(300, int(req.duration)))}
            step = {"id": "s1", "toolName": "generate_music", "arguments": args}
        elif req.kind == "speech":
            v = req.voice or {}
            mode = v.get("mode", "voice")
            args = {"prompt": req.prompt, "model": mode, "outputFormat": "wav", "language": v.get("language", "english")}
            if mode == "voice":          # glos studyjny: ten sam mowca przy kazdym wywolaniu
                args["voice"] = v.get("voice", "serena")
                if v.get("description"):
                    args["voiceDescription"] = v["description"]
            elif mode == "design":       # UWAGA: kazde wywolanie = nowy glos; do spojnosci zaprojektuj raz i sklonuj
                args["voiceDescription"] = v.get("description", "")
            elif mode == "clone":
                media.append({"kind": "audio", "url": self._upload_media(Path(v["ref_path"]), "referenceAudio", job_id)})
                args["voiceSourceIndex"] = -1
                if v.get("transcript"):
                    args["voiceTranscript"] = v["transcript"]
            step = {"id": "s1", "toolName": "generate_speech", "arguments": args}
        elif req.kind == "edit":
            # Limity z dokumentacji: Krea Identity Edit do 2 obrazow referencyjnych, Qwen do 3.
            model = req.model or config.EDIT_MODEL
            req.refs = req.refs[:2] if "krea" in model else req.refs[:3]
            for i, p in enumerate(req.refs):
                media.append({"kind": "image", "url": self._upload_image(p, f"contextImage{i + 1}", job_id)})
            # media_references: -1 = pierwszy wgrany obraz, -2 = drugi... (zgodnie z prompt "first/second image")
            idx = [-(i + 1) for i in range(len(media))]
            args = {"prompt": req.prompt, "model": model, "aspectRatio": req.fmt,
                    config.SOGNI_EDIT_REF_ARG: idx, **config.SOGNI_IMAGE_ARGS}
            step = {"id": "s1", "toolName": "edit_image", "arguments": args}
        else:
            args = {"prompt": req.prompt, "videoModel": req.model or config.VIDEO_MODEL,
                    "duration": req.duration, **config.SOGNI_VIDEO_ARGS}
            if req.source_image and req.end_image:
                # Zweryfikowane testem: H3 first/last frame wymaga frameRole="both"; kolejnosc: start (-1), koniec (-2).
                media.append({"kind": "image", "url": self._upload_image(req.source_image, "startingImage", job_id)})
                media.append({"kind": "image", "url": self._upload_image(req.end_image, "referenceImageEnd", job_id)})
                args["videoModel"] = req.model or "minimax-h3-fasth3-flf2v-turbo"
                args.update({"frameRole": "both", "sourceImageIndex": -1, "endImageIndex": -2})
                step = {"id": "s1", "toolName": "animate_photo", "arguments": args}
            elif req.source_image:
                media.append({"kind": "image",
                              "url": self._upload_image(req.source_image, "startingImage", job_id)})
                args["sourceImageIndex"] = -1  # udokumentowane w Generation Recipes
                step = {"id": "s1", "toolName": "animate_photo", "arguments": args}
            else:
                step = {"id": "s1", "toolName": "generate_video", "arguments": args}
        body = {
            "input": {"title": f"studio-{req.kind}", "steps": [step]},
            "billing_mode": config.SOGNI_BILLING_MODE,
            "app_source": "character-studio",
            "safe_content_filter": req.safe_filter,
            "max_estimated_capacity_units": config.SOGNI_MAX_CAPACITY_UNITS,
            "confirm_cost": True,
        }
        if media:
            body["media_references"] = media
        return body

    # --- API ------------------------------------------------------------------------
    def estimate(self, req: GenRequest) -> dict:
        body = self._plan(req)
        body["confirm_cost"] = False
        r = self._call("POST", "/v1/creative-agent/workflows", json=body,
                       headers={"Idempotency-Key": str(uuid.uuid4())})
        j = r.json() if r.content else {}
        details = j.get("details") or j.get("data", {}).get("details") or {}
        return {"supported": True, "status": r.status_code,
                "estimatedCapacity": details.get("estimatedCapacity"), "raw": j}

    def generate(self, req: GenRequest, on_remote_id=None) -> GenResult:
        wid = req.resume_id
        if not wid:
            r = self._call("POST", "/v1/creative-agent/workflows", json=self._plan(req),
                           headers={"Idempotency-Key": req.idem_key})
            if r.status_code not in (200, 201, 202):
                raise ProviderError("start " + self._err(r))
            wid = r.json()["data"]["workflow"]["workflowId"]
        if on_remote_id:
            on_remote_id(wid)
        wf = self._poll(wid, timeout=2400 if req.kind == "video" else 900)
        urls = [a["url"] for st in wf.get("steps", []) for a in st.get("artifacts", []) if a.get("url")]
        if not urls:
            raise ProviderError(f"Workflow {wid} zakonczony bez artefaktow (status {wf.get('status')}).")
        files = []
        for u in urls:  # wyniki zyja ok. 48 h - pobieramy od razu
            d = self.plain.get(u)
            if d.status_code != 200:
                raise ProviderError(f"Pobieranie wyniku: HTTP {d.status_code}")
            ctype = d.headers.get("content-type", "").split(";")[0].strip().lower()
            ext = {"audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav",
                   "audio/flac": "flac", "audio/mp4": "m4a", "audio/x-m4a": "m4a", "image/jpeg": "jpg"}.get(ctype) or \
                (mimetypes.guess_extension(ctype) or ".bin").lstrip(".")
            files.append((d.content, ext))
        return GenResult(files, wid, {"status": wf.get("status")})

    @staticmethod
    def _last_message(wf: dict) -> str:
        """Ostatni komunikat ze zdarzen workflow (np. powod wstrzymania, limit okresu probnego)."""
        for e in reversed(wf.get("events", [])):
            m = e.get("message")
            if m and "lease" not in m.lower():
                return str(m)[:300]
        return ""

    @staticmethod
    def _why(wf: dict) -> str:
        """Zbiera powody niepowodzenia z workflow (bez URL-i); format odpowiedzi nie jest w pelni udokumentowany."""
        import json
        info = {k: wf[k] for k in ("error", "errorCode", "message", "failureReason", "waitingReason") if wf.get(k)}
        steps = []
        for st in wf.get("steps", []):
            s = {k: st[k] for k in ("id", "toolName", "status", "error", "errorCode", "errorMessage", "message")
                 if st.get(k)}
            if s:
                steps.append(s)
        if steps:
            info["steps"] = steps
        evs = [e for e in wf.get("events", []) if any(w in json.dumps(e).lower() for w in ("fail", "error", "reject"))]
        if evs:
            info["events"] = evs[-3:]
        text = json.dumps(info, ensure_ascii=False)
        return text[:900] if info else f"brak szczegolow w odpowiedzi; klucze: {sorted(wf.keys())}"

    def _resume_safety(self, wid: str) -> bool:
        """Odblokowuje workflow wstrzymany przez przeglad bezpieczenstwa: POST /workflows/{id}/resume z
        safe_content_filter=false (pole per zadanie wg dokumentacji; konto 18+ uprawnione). Zwraca True, gdy HTTP przyjal zadanie.
        Format odpowiedzi /resume NIE zostal zweryfikowany prawdziwym renderem."""
        r = self._call("POST", f"/v1/creative-agent/workflows/{wid}/resume", json={"safe_content_filter": False},
                       headers={"Idempotency-Key": str(uuid.uuid4())})
        return r.status_code in (200, 201, 202)

    def _poll(self, wid: str, timeout: float) -> dict:
        deadline = time.time() + timeout
        delay = 3.0
        resumes = 0
        grace = 0   # odpytania od ostatniego /resume (po /resume stan jeszcze kilka odpytan pozostaje "safety_review_required")
        while time.time() < deadline:
            r = self._call("GET", f"/v1/creative-agent/workflows/{wid}")
            if r.status_code != 200:
                raise ProviderError("status " + self._err(r))
            wf = r.json()["data"]["workflow"]
            status = wf.get("status")
            if status in TERMINAL:
                if status != "completed":
                    raise ProviderError(f"Workflow {wid}: {status}. {self._why(wf)}")
                return wf
            if status == "waiting_for_user":
                if wf.get("waitingReason") == "safety_review_required":
                    # Tylko ten jeden powod wstrzymania jest wznawiany (B1); zwykla odmowa (status failed) nie jest ponawiana.
                    if resumes and grace < RESUME_GRACE_POLLS:
                        # Sonda 17.10.2026: /resume -> HTTP 202, ale stan wraca do "completed" dopiero po ok. 4-5 odpytaniach
                        # co 4 s; ponowne /resume od razu zuzywaloby limit prob (pierwsza wersja B1 tak padla).
                        grace += 1
                        time.sleep(4.0)
                        continue
                    if resumes < config.SAFETY_RESUME_ATTEMPTS and self._resume_safety(wid):
                        resumes += 1
                        grace = 0
                        time.sleep(4.0)
                        continue
                    raise SafetyRejected(
                        f"Dostawca wstrzymal zadanie do przegladu bezpieczenstwa (safety_review_required) i po {resumes} "
                        f"wznowieniach z safe_content_filter=false nadal je wstrzymuje (limit {config.SAFETY_RESUME_ATTEMPTS}). "
                        "Zmien prompt albo sprawdz uprawnienia konta 18+ (SAFETY_REJECTED).")
                raise ProviderError(f"Workflow czeka na uzytkownika: {wf.get('waitingReason')}. {self._last_message(wf)}")
            time.sleep(delay + random.random())
            delay = min(delay * 1.4, 20.0)
        raise ProviderError(f"Przekroczono czas oczekiwania na workflow {wid}")
