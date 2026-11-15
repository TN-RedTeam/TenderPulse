"""Générateur du digest quotidien : e-mail HTML autonome (styles en ligne, mise en page en tableaux)."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from jinja2 import Environment, select_autoescape

from backend.textutils import format_eur

PARIS = ZoneInfo("Europe/Paris")

DECISION_STYLE = {
    "go": ("Go", "#166534", "#dcfce7"),
    "a_verifier": ("À vérifier", "#92400e", "#fef3c7"),
    "no_go": ("No-Go", "#991b1b", "#fee2e2"),
}

_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ subject }}</title>
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:Arial,Helvetica,sans-serif;color:#0f172a;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f1f5f9;">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="640" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%;">
  <tr><td style="background-color:#0f172a;border-radius:8px 8px 0 0;padding:24px 28px;">
    <div style="font-size:13px;letter-spacing:1px;text-transform:uppercase;color:#94a3b8;">TenderPulse — digest du {{ generated_label }}</div>
    <div style="font-size:22px;font-weight:bold;color:#ffffff;padding-top:6px;">{{ profile_name }}</div>
    <div style="font-size:14px;color:#cbd5e1;padding-top:4px;">{{ tenant_name }}</div>
  </td></tr>
  <tr><td style="background-color:#ffffff;padding:20px 28px;border-bottom:1px solid #e2e8f0;">
    {% if items %}
    <div style="font-size:16px;line-height:24px;">
      <strong>{{ items|length }} opportunité{{ 's' if items|length > 1 else '' }}</strong>
      avec un score d'au moins <strong>{{ threshold }}/100</strong>{{ period_label }}.
    </div>
    {% else %}
    <div style="font-size:16px;line-height:24px;">
      Aucune opportunité n'atteint le seuil de <strong>{{ threshold }}/100</strong>{{ period_label }}.
    </div>
    {% endif %}
  </td></tr>
  {% for item in items %}
  <tr><td style="background-color:#ffffff;padding:20px 28px;border-bottom:1px solid #e2e8f0;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td width="64" valign="top" style="padding-right:16px;">
          <div style="width:56px;height:56px;line-height:56px;border-radius:28px;text-align:center;font-size:20px;font-weight:bold;background-color:{{ item.badge_bg }};color:{{ item.badge_fg }};">{{ item.score }}</div>
        </td>
        <td valign="top">
          <span style="display:inline-block;padding:2px 10px;border-radius:10px;font-size:12px;font-weight:bold;background-color:{{ item.badge_bg }};color:{{ item.badge_fg }};">{{ item.decision_label }}</span>
          <div style="font-size:16px;font-weight:bold;line-height:22px;padding-top:6px;">
            <a href="{{ item.url_avis }}" style="color:#1d4ed8;text-decoration:none;">{{ item.objet }}</a>
          </div>
          <div style="font-size:13px;color:#475569;padding-top:4px;">
            {{ item.acheteur }}{% if item.departments %} · Dép. {{ item.departments|join(', ') }}{% endif %} · Avis {{ item.idweb }}
          </div>
          <div style="font-size:13px;color:#0f172a;padding-top:8px;">
            <strong>Date limite :</strong> {{ item.deadline_label }} &nbsp;|&nbsp; <strong>Budget estimé :</strong> {{ item.budget_label }}
          </div>
          {% if item.eliminatory %}
          <div style="margin-top:10px;padding:8px 12px;background-color:#fef2f2;border-left:4px solid #dc2626;font-size:13px;line-height:19px;color:#7f1d1d;">
            {% for flag in item.eliminatory %}<div>⚠ <strong>{{ flag.label }}</strong> — {{ flag.detail }}</div>{% endfor %}
          </div>
          {% endif %}
          <div style="font-size:13px;line-height:20px;color:#334155;padding-top:10px;">
            {% for line in item.summary_lines %}<div>{{ line }}</div>{% endfor %}
          </div>
        </td>
      </tr>
    </table>
  </td></tr>
  {% endfor %}
  <tr><td style="background-color:#ffffff;border-radius:0 0 8px 8px;padding:20px 28px;" align="center">
    <a href="{{ app_url }}" style="display:inline-block;padding:10px 22px;border-radius:6px;background-color:#1d4ed8;color:#ffffff;font-size:14px;font-weight:bold;text-decoration:none;">Ouvrir le tableau de bord</a>
    <div style="font-size:12px;color:#64748b;line-height:18px;padding-top:14px;">
      Source : Bulletin officiel des annonces des marchés publics (BOAMP), données ouvertes.<br>
      Les scores sont une aide à la décision : vérifiez toujours le règlement de consultation avant de répondre.
    </div>
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>
"""

_env = Environment(autoescape=select_autoescape(default=True, default_for_string=True), trim_blocks=True, lstrip_blocks=True)
_template = _env.from_string(_TEMPLATE)


def select_digest_items(candidates: list[dict[str, Any]], threshold: int, now: datetime) -> list[dict[str, Any]]:
    """Ne garde que les opportunités ouvertes, non ignorées, dont le score atteint le seuil ; triées par score."""
    kept = []
    for item in candidates:
        if item["score"] < threshold or item.get("status") == "ignore":
            continue
        deadline = item.get("date_limite")
        if deadline is not None and deadline <= now:
            continue
        kept.append(item)
    return sorted(kept, key=lambda item: (-item["score"], item.get("date_limite") or datetime.max.replace(tzinfo=now.tzinfo)))


def _deadline_label(deadline: datetime | None, now: datetime) -> str:
    if deadline is None:
        return "non précisée"
    days = int((deadline - now).total_seconds() // 86400)
    remaining = "aujourd'hui" if days <= 0 else f"J-{days}"
    return f"{deadline.astimezone(PARIS):%d/%m/%Y à %Hh%M} ({remaining})"


def digest_subject(profile_name: str, count: int, now: datetime) -> str:
    plural = "s" if count > 1 else ""
    return f"TenderPulse — {count} opportunité{plural} pour {profile_name} ({now.astimezone(PARIS):%d/%m/%Y})"


def render_digest(
    *, tenant_name: str, profile_name: str, threshold: int, candidates: list[dict[str, Any]],
    now: datetime, app_url: str, since_hours: int | None = 24,
) -> tuple[str, int]:
    """Produit le HTML du digest. Retourne (html, nombre d'opportunités retenues)."""
    items = []
    for item in select_digest_items(candidates, threshold, now):
        label, fg, bg = DECISION_STYLE.get(item["decision"], DECISION_STYLE["a_verifier"])
        items.append({
            "score": item["score"], "decision_label": label, "badge_fg": fg, "badge_bg": bg,
            "objet": item["objet"] or "Objet non précisé", "acheteur": item["acheteur"] or "Acheteur non précisé",
            "departments": item.get("departments") or [], "idweb": item["idweb"], "url_avis": item["url_avis"],
            "deadline_label": _deadline_label(item.get("date_limite"), now),
            "budget_label": format_eur(item.get("budget_estime")),
            "eliminatory": item.get("eliminatory") or [],
            "summary_lines": [line for line in (item.get("summary") or "").splitlines() if line.strip()],
        })
    period_label = f" sur les dernières {since_hours} heures" if since_hours else " parmi les consultations ouvertes"
    html = _template.render(
        subject=digest_subject(profile_name, len(items), now), generated_label=f"{now.astimezone(PARIS):%d/%m/%Y}",
        tenant_name=tenant_name, profile_name=profile_name, threshold=threshold, items=items,
        period_label=period_label, app_url=app_url,
    )
    return html, len(items)
