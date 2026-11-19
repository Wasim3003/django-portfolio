"""Single-file Django backend for the portfolio.
Run:  pip install django gunicorn
      set EMAIL_HOST_USER, EMAIL_HOST_PASSWORD (Gmail app password), EMAIL_TO
      python app.py runserver --noreload      (local)
      gunicorn app:application                (deploy)
"""
import json, os, sys, time, urllib.request
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


def theme(request):
    """Serves your own theme.mp3 if you put one next to this file."""
    f = BASE / "theme.mp3"
    if not f.exists():
        raise Http404
    return FileResponse(open(f, "rb"), content_type="audio/mpeg")


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


def resume(request):
    f = BASE / "resume.pdf"
    if not f.exists():
        raise Http404
    resp = FileResponse(open(f, "rb"), content_type="application/pdf")
    resp["Content-Disposition"] = 'attachment; filename="Wasimullah_Siddique_Resume.pdf"'
    return resp


FACTS = "You are JARVIS, the assistant on Wasim's portfolio. Answer only questions about Wasim, in under 80 words, in a friendly tone. If the answer is not in these facts, say you do not know and suggest emailing wasimroy272@gmail.com. Facts: Wasim is Mohammed Wasimullah Siddique, a Python full-stack developer from Visakhapatnam, India. B.Tech in Electronics and Communication Engineering, Andhra University, 2021 to 2025, merit scholarship (top 5% of 200 students). Skills: Python, JavaScript, C basics, Django, Django REST Framework, React, MySQL, PostgreSQL, Redis, Git, GitHub, REST APIs, caching, debugging. Experience: Python Full Stack Developer Intern at RoboWaves. Projects: GitHub Searcher (Django REST, Redis caching with 2 hour TTL, React), Country Information Platform (Django, external APIs, 3D globe), Jarvis Voice Assistant (Python, speech recognition), PrepMind AI (exam prep with the Claude API), ANTIGRAVITY (fitness tracker with AI coach), AI Chatbot (Django, React, LLaMA3 on Groq). Certifications: Python Full Stack (QSpiders), Telecom (BSNL), Embedded C, IoT, AI and Cloud (L&T). Contact: wasimroy272@gmail.com, GitHub wasim3003."
_hits = {}
_cache = {"t": 0, "data": None}


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
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not q or not key:
        return JsonResponse({"ok": False, "error": "Assistant is not configured."}, status=503)
    payload = json.dumps({
        "model": os.environ.get("ASK_MODEL", "claude-haiku-5-5"),
        "max_tokens": 300,
        "system": FACTS,
        "messages": [{"role": "user", "content": q}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", payload,
        {"content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            text = json.loads(r.read())["content"][0]["text"]
    except Exception:
        return JsonResponse({"ok": False, "error": "Could not answer right now."}, status=502)
    return JsonResponse({"ok": True, "text": text})


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
    path("theme.mp3", theme),
    path("resume.pdf", resume),
    path("ask/", ask),
    path("github/", github),
]

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()

if __name__ == "__main__":
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
