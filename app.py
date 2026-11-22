"""Backend for the Wasim Stark portfolio (Django, one file).

Routes
  /            the page (index.html)
  /resume.pdf  your resume (download)
  /theme.mp3   the music for the Music button
  /contact/    contact form: emails you the message
  /ask/        JARVIS chat: answers questions about you
  /github/     live GitHub numbers for the feed
  /health/     shows which settings are loaded (true/false only)

Environment variables (set them on your host, never in the code)
  RESEND_API_KEY     sends contact mail over HTTPS (works on Render free)
  EMAIL_TO           where contact messages arrive
  OPENROUTER_API_KEY key for JARVIS (OpenRouter), with OPENROUTER_MODEL = the model id
  GROQ_API_KEY       alternative key for JARVIS (Groq), or ANTHROPIC_API_KEY
  GITHUB_TOKEN       optional, avoids GitHub rate limits
  SHOW_AI_ERRORS     set to 1 while testing: JARVIS then shows why the AI call failed
  SECRET_KEY, DEBUG  Django settings (DEBUG=0 on a live site)

Run locally:  pip install -r requirements.txt
              python app.py runserver --noreload
Deploy:       gunicorn app:application
"""
import json, os, sys, time, urllib.error, urllib.request
from pathlib import Path
from django.conf import settings

BASE = Path(__file__).resolve().parent
settings.configure(
    DEBUG=os.environ.get("DEBUG", "0") == "1",
    SECRET_KEY=os.environ.get("SECRET_KEY", "change-me-in-production"),
    ALLOWED_HOSTS=["*"],
    ROOT_URLCONF=__name__,
    MIDDLEWARE=[],
    EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
    EMAIL_HOST="smtp.gmail.com",
    EMAIL_PORT=587,
    EMAIL_USE_TLS=True,
    EMAIL_HOST_USER=os.environ.get("EMAIL_HOST_USER", ""),
    EMAIL_HOST_PASSWORD=os.environ.get("EMAIL_HOST_PASSWORD", ""),
)

from django.core.mail import send_mail
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST


def send_file(name, content_type, download_name=None):
    """Sends a file that sits next to app.py."""
    path = BASE / name
    if not path.exists():
        raise Http404
    response = FileResponse(open(path, "rb"), content_type=content_type)
    if download_name:
        response["Content-Disposition"] = 'attachment; filename="%s"' % download_name
    return response


def resume(request):
    return send_file("resume.pdf", "application/pdf", "Wasimullah_Siddique_Resume.pdf")


def theme(request):
    return send_file("theme.mp3", "audio/mpeg")


def index(request):
    return HttpResponse((BASE / "index.html").read_text(encoding="utf-8"))


def deliver(subject, body):
    """Send the message to you. Uses Resend's HTTPS API when RESEND_API_KEY is set
    (works on hosts that block SMTP, like Render's free plan), else Gmail SMTP."""
    to = os.environ.get("EMAIL_TO") or settings.EMAIL_HOST_USER
    key = os.environ.get("RESEND_API_KEY")
    if key:
        payload = json.dumps({
            "from": "Portfolio <onboarding@resend.dev>",
            "to": [to],
            "subject": subject,
            "text": body,
        }).encode()
        req = urllib.request.Request(
            "https://api.resend.com/emails", payload,
            {"Authorization": "Bearer " + key, "Content-Type": "application/json", "User-Agent": "portfolio"},
        )
        urllib.request.urlopen(req, timeout=15).read()
    else:
        send_mail(subject, body, settings.EMAIL_HOST_USER, [to], fail_silently=False)


@csrf_exempt
@require_POST
def contact(request):
    try:
        data = json.loads(request.body)
    except ValueError:
        return JsonResponse({"ok": False, "error": "Bad request."}, status=400)
    if data.get("website"):  # honeypot: bots fill this hidden field
        return JsonResponse({"ok": True})
    name = str(data.get("name", "")).strip()[:80]
    phone = str(data.get("phone", "")).strip()[:20]
    purpose = str(data.get("purpose", "")).strip()[:2000]
    if not (name and phone and purpose):
        return JsonResponse({"ok": False, "error": "All fields are required."}, status=400)
    try:
        deliver(
            f"Portfolio message from {name}",
            f"Name: {name}\nPhone: {phone}\n\nPurpose of contact:\n{purpose}",
        )
    except Exception:
        return JsonResponse({"ok": False, "error": "Could not send email."}, status=500)
    return JsonResponse({"ok": True})


FACTS = "You are JARVIS, the assistant on Wasim's portfolio. Answer only questions about Wasim, in under 80 words, in a friendly tone. If the answer is not in these facts, say you do not know and suggest emailing wasimroy272@gmail.com. Facts: Wasim is Mohammed Wasimullah Siddique, a Python full-stack developer from Visakhapatnam, India. B.Tech in Electronics and Communication Engineering, Andhra University, 2021 to 2025, merit scholarship (top 5% of 200 students). Skills: Python, JavaScript, C basics, Django, Django REST Framework, React, MySQL, PostgreSQL, Redis, Git, GitHub, REST APIs, caching, debugging. Experience: Python Full Stack Developer Intern at RoboWaves. Projects: GitHub Searcher (Django REST, Redis caching with 2 hour TTL, React), Country Information Platform (Django, external APIs, 3D globe), Jarvis Voice Assistant (Python, speech recognition), PrepMind AI (exam prep with the Claude API), ANTIGRAVITY (fitness tracker with AI coach), AI Chatbot (Django, React, LLaMA3 on Groq). Certifications: Python Full Stack (QSpiders), Telecom (BSNL), Embedded C, IoT, AI and Cloud (L&T). Contact: wasimroy272@gmail.com, GitHub wasim3003."
_hits = {}
_cache = {"t": 0, "data": None}


def env_key(name):
    """Reads a key from the environment and trims stray spaces, quotes or line breaks.
    (A pasted key with a hidden space works in Postman but fails on a server.)"""
    return os.environ.get(name, "").strip().strip('"').strip("'")


_models = {"t": 0, "ids": []}


def free_openrouter_models():
    """Asks OpenRouter which free text models exist right now (cached for an hour),
    because free model names come and go."""
    now = time.time()
    if _models["ids"] and now - _models["t"] < 3600:
        return _models["ids"]
    try:
        req = urllib.request.Request("https://openrouter.ai/api/v1/models", headers={"User-Agent": "portfolio"})
        with urllib.request.urlopen(req, timeout=10) as r:
            models = json.loads(r.read())["data"]
    except Exception:
        return _models["ids"]
    ids = []
    for m in models:
        price = m.get("pricing") or {}
        free = str(price.get("prompt")) == "0" and str(price.get("completion")) == "0"
        text_only = (m.get("architecture") or {}).get("modality") == "text->text"
        if m["id"].endswith(":free") and free and text_only and (m.get("context_length") or 0) >= 8000:
            ids.append(m["id"])
    # Skip reasoning models (they often reply with empty text) and prefer well-known chat models.
    ids = [i for i in ids if not any(w in i for w in ("thinking", "reasoning", "r1", "think"))]
    liked = ("llama", "gemma", "qwen", "mistral", "gpt-oss", "deepseek")
    ids.sort(key=lambda i: (not any(w in i for w in liked), i))
    _models.update(t=now, ids=ids)
    return ids


def ai_failure(provider, detail):
    """Logs why the AI call failed. Set SHOW_AI_ERRORS=1 to also show the reason in the chat."""
    print("ASK ERROR", provider, detail, file=sys.stderr, flush=True)
    result = {"ok": False, "error": "Could not answer right now."}
    if os.environ.get("SHOW_AI_ERRORS") == "1":
        result["detail"] = (provider + ": " + detail)[:200]
    return JsonResponse(result, status=502)


def ai_provider():
    """JARVIS uses the first key that is set: OpenRouter, then Groq, then Anthropic."""
    for provider in ("openrouter", "groq", "anthropic"):
        if env_key(provider.upper() + "_API_KEY"):
            return provider
    return None


@csrf_exempt
@require_POST
def ask(request):
    """JARVIS: answers visitor questions about you with the Claude API."""
    ip = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", "x")).split(",")[0].strip()
    now = time.time()
    hits = [t for t in _hits.get(ip, []) if now - t < 3600]
    if len(hits) >= 15:
        return JsonResponse({"ok": False, "error": "Too many questions."}, status=429)
    _hits[ip] = hits + [now]
    try:
        q = str(json.loads(request.body).get("q", "")).strip()[:300]
    except ValueError:
        q = ""
    provider = ai_provider()
    if not q or not provider:
        return JsonResponse({"ok": False, "error": "Assistant is not configured."}, status=503)
    if provider == "anthropic":
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": env_key("ANTHROPIC_API_KEY"),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body = {"max_tokens": 1500, "system": FACTS, "messages": [{"role": "user", "content": q}]}
        models = [os.environ.get("ASK_MODEL", "claude-haiku-5-5")]
    else:  # OpenRouter and Groq both use the OpenAI chat format
        if provider == "openrouter":
            url = "https://openrouter.ai/api/v1/chat/completions"
            chosen = os.environ.get("OPENROUTER_MODEL", "").strip()
            # Your model first, then up to 3 free ones found live, in case yours is gone.
            models = ([chosen] if chosen else []) + [m for m in free_openrouter_models() if m != chosen][:3]
            extra = {"HTTP-Referer": request.build_absolute_uri("/"), "X-Title": "Wasim portfolio"}
        else:
            url = "https://api.groq.com/openai/v1/chat/completions"
            models = [os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile").strip()]
            extra = {}
        headers = {
            "Authorization": "Bearer " + env_key(provider.upper() + "_API_KEY"),
            "Content-Type": "application/json",
            "User-Agent": "portfolio",
        }
        headers.update(extra)
        body = {"max_tokens": 400, "messages": [{"role": "system", "content": FACTS}, {"role": "user", "content": q}]}
    if not models:
        return ai_failure(provider, "no model available (set OPENROUTER_MODEL)")
    last_error = "unknown"
    for model in models:
        body["model"] = model
        try:
            req = urllib.request.Request(url, json.dumps(body).encode(), headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
            if provider == "anthropic":
                text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
            else:
                text = (data["choices"][0]["message"].get("content") or "").strip()
            if not text:
                raise ValueError("empty answer")
            return JsonResponse({"ok": True, "text": text})
        except urllib.error.HTTPError as e:
            raw = e.read()[:600].decode("utf-8", "replace")
            try:
                message = json.loads(raw)["error"]["message"]
            except Exception:
                message = raw
            last_error = "HTTP %s %s (model %s)" % (e.code, message, model)
            print("ASK TRY", provider, last_error, file=sys.stderr, flush=True)
            if e.code in (401, 402, 403):  # key or credits problem: another model will not help
                break
        except Exception as e:
            last_error = "%r (model %s)" % (e, model)
            print("ASK TRY", provider, last_error, file=sys.stderr, flush=True)
    return ai_failure(provider, last_error)


def health(request):
    """Shows which settings are loaded (true/false only, never the values)."""
    return JsonResponse({
        "jarvis_provider": ai_provider() or "none",
        "jarvis_model": (os.environ.get("OPENROUTER_MODEL") or "(auto: free model)") if ai_provider() == "openrouter" else "",
        "openrouter_key_set": bool(env_key("OPENROUTER_API_KEY")),
        "groq_key_set": bool(env_key("GROQ_API_KEY")),
        "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "resend_key_set": bool(os.environ.get("RESEND_API_KEY")),
        "github_token_set": bool(os.environ.get("GITHUB_TOKEN")),
        "email_to": os.environ.get("EMAIL_TO", ""),
    })


def github(request):
    """Live GitHub numbers for the HUD feed, cached for 10 minutes."""
    now = time.time()
    if _cache["data"] and now - _cache["t"] < 600:
        return JsonResponse(_cache["data"])
    headers = {"User-Agent": "portfolio"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]

    def get(url):
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as r:
            return json.loads(r.read())

    try:
        user = get("https://api.github.com/users/wasim3003")
        repos = get("https://api.github.com/users/wasim3003/repos?sort=pushed&per_page=8")
    except Exception:
        return JsonResponse({"ok": False}, status=502)
    data = {
        "ok": True,
        "repos": user["public_repos"],
        "followers": user["followers"],
        "recent": [
            {"name": r["name"], "lang": r["language"], "url": r["html_url"], "pushed": r["pushed_at"][:10]}
            for r in repos if not r["fork"]
        ][:4],
    }
    _cache.update(t=now, data=data)
    return JsonResponse(data)


urlpatterns = [
    path("", index),
    path("contact/", contact),
    path("resume.pdf", resume),
    path("static/assets/resume.pdf", resume),  # old address, kept so older pages still work
    path("theme.mp3", theme),
    path("ask/", ask),
    path("github/", github),
    path("health/", health),
]

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()

if __name__ == "__main__":
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
