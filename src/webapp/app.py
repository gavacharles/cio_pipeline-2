"""
app.py — participant web app for the CiO construction-cost forecasting pilot.

Run:   CIO_ADMIN_KEY=change-me uvicorn --app-dir src/webapp app:app --host 0.0.0.0 --port 8000
       (from the repo root; CIO_DB overrides data/market/exchange.sqlite)

Participants join with an invite code from the organiser, then:
  - report the prices they pay each week (feeds the weekly note's crowd prices),
  - trade play-money contracts on the next official index print (LMSR market maker),
  - read the weekly forecast note and the leaderboard.
Organiser: /admin?key=$CIO_ADMIN_KEY to create invite codes. Markets are opened and
settled by src/market/cycle.py, not from the browser.
"""
from __future__ import annotations

import html
import os
import sys
from pathlib import Path

import numpy as np
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "market"))
sys.path.insert(0, str(ROOT / "src" / "forecast"))

from country import load_country, list_countries        # noqa: E402
from ledger import Exchange, ExchangeError              # noqa: E402
from nowcast import expected_change                     # noqa: E402
from reports import Participants, ReportError           # noqa: E402

DB = Path(os.environ.get("CIO_DB", ROOT / "data" / "market" / "exchange.sqlite"))
NOTES = ROOT / "data" / "processed" / "notes"
COOKIE = "cio_token"

app = FastAPI(title="CiO construction cost pilot", docs_url=None, redoc_url=None)
COUNTRIES = {c: load_country(c) for c in list_countries()}


def ex() -> Exchange:
    return Exchange(DB, 1000)


def people() -> Participants:
    return Participants(DB)


def me(request: Request) -> dict | None:
    return people().by_token(request.cookies.get(COOKIE))


e = html.escape

CSS = """
:root{--bg:#fbfaf7;--card:#fff;--fg:#1d1d1b;--mut:#6b6a66;--line:#e3e0d8;--acc:#b5651d;--acc2:#1f6f78;--bar:#f1e3d3}
@media (prefers-color-scheme:dark){:root{--bg:#141412;--card:#1d1c1a;--fg:#ecebe6;--mut:#a3a29c;--line:#33322e;--acc:#e0a060;--acc2:#5fb3bc;--bar:#3a2c1e}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif}
header{display:flex;gap:12px;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid var(--line);flex-wrap:wrap}
header b{color:var(--acc)}nav a{margin-left:14px;color:var(--fg);text-decoration:none}nav a:hover{color:var(--acc)}
main{max-width:860px;margin:0 auto;padding:16px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:12px 0}
h1{font-size:1.4rem;margin:.3em 0}h2{font-size:1.1rem;margin:.2em 0 .6em}.mut{color:var(--mut);font-size:.9rem}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:6px 6px;border-bottom:1px solid var(--line)}th{color:var(--mut);font-weight:600;font-size:.88rem}
.tw{overflow-x:auto}a{color:var(--acc2)}input,select,button{font:inherit;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg);width:100%}
button{background:var(--acc);color:#fff;border:0;cursor:pointer;font-weight:600}.row{display:grid;grid-template-columns:1fr 1fr;gap:10px}
@media (max-width:560px){.row{grid-template-columns:1fr}}label{display:block;margin:8px 0 4px;font-size:.9rem;color:var(--mut)}
.bar{position:relative;background:var(--bar);border-radius:6px;height:26px;overflow:hidden}.bar span{position:absolute;inset:0 auto 0 0;background:var(--acc);opacity:.75}
.bar em{position:absolute;left:8px;top:2px;font-style:normal;font-weight:600}.ok{color:var(--acc2)}.err{color:#c0392b}
"""


def page(title: str, body: str, user: dict | None = None) -> HTMLResponse:
    nav = ("<nav><a href='/home'>Contracts</a><a href='/prices'>Report prices</a><a href='/note'>Weekly note</a>"
           "<a href='/leaderboard'>Leaderboard</a><a href='/logout'>Log out</a></nav>") if user else ""
    who = f"<span class=mut>{e(user['name'])} · {e(COUNTRIES[user['country']]['country'])}</span>" if user else ""
    return HTMLResponse(f"<!doctype html><html lang=en><head><meta charset=utf-8>"
                        f"<meta name=viewport content='width=device-width,initial-scale=1'><title>{e(title)}</title>"
                        f"<style>{CSS}</style></head><body><header><div><b>CiO</b> construction cost pilot {who}</div>"
                        f"{nav}</header><main>{body}<p class=mut>Play money only: points have no cash value.</p>"
                        f"</main></body></html>")


def need_login(request: Request):
    user = me(request)
    return user, (None if user else RedirectResponse("/", status_code=303))


# ------------------------------------------------------------------ auth --
@app.get("/", response_class=HTMLResponse)
def index(request: Request, err: str = ""):
    if me(request):
        return RedirectResponse("/home", status_code=303)
    msg = f"<p class=err>{e(err)}</p>" if err else ""
    return page("Join", f"""<div class=card><h1>Construction cost forecasting pilot</h1>
<p>Report the prices you pay for cement, steel, diesel and other inputs each week, forecast the next
official index print, and get the weekly cost note. Uganda, Kenya and Rwanda.</p>
<form method=post action=/login><label>Invite code</label><input name=code autocomplete=off required>
<p><button>Enter</button></p></form>{msg}</div>""")


@app.post("/login")
def login(code: str = Form(...)):
    try:
        token = people().redeem(code)
    except ReportError:
        return RedirectResponse("/?err=That+invite+code+was+not+recognised", status_code=303)
    user = people().by_token(token)
    ex().open_account(user["handle"])
    r = RedirectResponse("/home", status_code=303)
    r.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 180)
    return r


@app.get("/logout")
def logout():
    r = RedirectResponse("/", status_code=303)
    r.delete_cookie(COOKIE)
    return r


# ------------------------------------------------------------- contracts --
@app.get("/home", response_class=HTMLResponse)
def home(request: Request):
    user, redirect = need_login(request)
    if redirect:
        return redirect
    x = ex()
    rows = []
    for m in x.markets(status="open", country=user["country"]):
        crowd = expected_change(np.array(m["prices"]), m["cuts"])
        rows.append(f"<tr><td><a href='/m/{m['id']}'>{e(m['title'])}</a></td><td>{e(m['ref_month'])}</td>"
                    f"<td>{crowd:+.2f}%</td><td>{e(m['closes'][:10])}</td></tr>")
    cfg = COUNTRIES[user["country"]]
    table = ("<div class=tw><table><tr><th>Contract</th><th>Period</th><th>Crowd expects</th><th>Trading closes</th></tr>"
             + "".join(rows) + "</table></div>") if rows else (
        "<p>No open contracts for this country yet. " + (
            "Rwanda has no official construction index, so this pilot collects prices and forecasts only."
            if cfg["status"] == "reporting" else "New contracts open after each official release.") + "</p>")
    bal = x.balance(user["handle"])
    return page("Contracts", f"""<div class=card><h1>Open contracts — {e(cfg['country'])}</h1>
<p class=mut>Each contract pays 1 point per share if the official {e(cfg['settlement']['statistics_office'])}
change lands in the range you hold. Balance: <b>{bal:,.1f}</b> points.</p>{table}</div>
<div class=card><h2>This week</h2><p><a href='/prices'>Report this week's prices</a> — it takes a minute and
keeps the note current for everyone.</p></div>""", user)


@app.get("/m/{mid}", response_class=HTMLResponse)
def market(mid: int, request: Request, msg: str = "", err: str = ""):
    user, redirect = need_login(request)
    if redirect:
        return redirect
    x = ex()
    try:
        m = x.market(mid)
    except ExchangeError:
        return page("Not found", "<p>No such contract.</p>", user)
    held = {r["outcome"]: r["shares"] for r in x.db.execute(
        "SELECT outcome, shares FROM positions WHERE account=? AND market_id=?", (user["handle"], mid))}
    bars = "".join(
        f"<tr><td>{i}</td><td style='min-width:180px'><div class=bar><span style='width:{p * 100:.1f}%'></span>"
        f"<em>{e(lab)}</em></div></td><td>{p:.0%}</td><td class=mut>{q:.0%}</td><td>{held.get(i, 0):g}</td></tr>"
        for i, (lab, p, q) in enumerate(zip(m["outcomes"], m["prices"], m["prior"])))
    opts = "".join(f"<option value={i}>{e(lab)}</option>" for i, lab in enumerate(m["outcomes"]))
    note = f"<p class=ok>{e(msg)}</p>" if msg else (f"<p class=err>{e(err)}</p>" if err else "")
    closed = m["status"] != "open"
    form = "" if closed else f"""<form method=post action='/m/{mid}/trade'><div class=row>
<div><label>Range</label><select name=outcome id=o>{opts}</select></div>
<div><label>Shares (negative to sell)</label><input name=shares id=s type=number step=1 value=10 required></div></div>
<p class=mut id=q>Cost: –</p><p><button>Place trade</button></p></form>
<script>async function q(){{const r=await fetch('/api/quote?m={mid}&o='+o.value+'&s='+s.value);const j=await r.json();
document.getElementById('q').textContent=j.error?j.error:'Cost: '+j.cost.toFixed(2)+' points';}}
o.onchange=q;s.oninput=q;q();</script>"""
    return page(m["title"], f"""<div class=card><h1>{e(m['title'])}</h1>
<p class=mut>Change in {e(m['ref_month'])} · trading closes {e(m['closes'][:10])} · status {e(m['status'])}</p>
<div class=tw><table><tr><th>#</th><th>Range</th><th>Crowd</th><th>Model</th><th>You hold</th></tr>{bars}</table></div>
{note}{form}</div>""", user)


@app.get("/api/quote")
def quote(m: int, o: int, s: float, request: Request):
    if not me(request):
        return JSONResponse({"error": "log in"}, status_code=401)
    try:
        return {"cost": ex().quote(m, o, s)}
    except (ExchangeError, IndexError) as err:
        return {"error": str(err)}


@app.post("/m/{mid}/trade")
def trade(mid: int, request: Request, outcome: int = Form(...), shares: float = Form(...)):
    user, redirect = need_login(request)
    if redirect:
        return redirect
    try:
        cost = ex().trade(user["handle"], mid, outcome, shares)
        return RedirectResponse(f"/m/{mid}?msg=Done:+{cost:.2f}+points", status_code=303)
    except ExchangeError as err:
        return RedirectResponse(f"/m/{mid}?err={e(str(err))}", status_code=303)


# --------------------------------------------------------------- prices --
@app.get("/prices", response_class=HTMLResponse)
def prices(request: Request, msg: str = "", err: str = ""):
    user, redirect = need_login(request)
    if redirect:
        return redirect
    cfg = COUNTRIES[user["country"]]
    items = cfg.get("price_items", [])
    opts = "".join(f"<option value='{e(i['code'])}'>{e(i['name'])} (per {e(i['unit'])})</option>" for i in items)
    s = people().crowd_summary(user["country"], items)
    def num(x, fmt):
        return "" if x is None or x != x else format(x, fmt)
    rows = "".join(
        f"<tr><td>{e(r['name'])}</td><td>{num(r['median'], ',.0f')}</td><td>{r['reporters']}</td>"
        f"<td>{num(r['change_pct'], '+.1f')}{'%' if num(r['change_pct'], '+.1f') else ''}</td></tr>"
        for _, r in s.iterrows())
    note = f"<p class=ok>{e(msg)}</p>" if msg else (f"<p class=err>{e(err)}</p>" if err else "")
    return page("Report prices", f"""<div class=card><h1>Report a price you paid or were quoted</h1>
<p class=mut>{e(cfg['currency'])}, including VAT, for delivery or collection as you normally buy. One report per item per
week is enough; the note uses each person's median so repeats do not count twice.</p>
<form method=post action=/prices><label>Item</label><select name=item>{opts}</select>
<div class=row><div><label>Price ({e(cfg['currency'])})</label><input name=price type=number step=any min=1 required></div>
<div><label>Where (town / area)</label><input name=location required></div></div>
<label>Supplier type (optional)</label><input name=supplier placeholder='hardware shop, factory, quarry, fuel station'>
<p><button>Submit</button></p></form>{note}</div>
<div class=card><h2>What participants are paying — latest week</h2><div class=tw><table>
<tr><th>Item</th><th>Median ({e(cfg['currency'])})</th><th>Reporters</th><th>vs 4 weeks</th></tr>{rows}</table></div></div>""",
                user)


@app.post("/prices")
def add_price(request: Request, item: str = Form(...), price: float = Form(...), location: str = Form(...),
              supplier: str = Form("")):
    user, redirect = need_login(request)
    if redirect:
        return redirect
    items = [i["code"] for i in COUNTRIES[user["country"]].get("price_items", [])]
    try:
        people().add_report(user["handle"], user["country"], item, price, location, supplier, items=items)
        return RedirectResponse("/prices?msg=Thank+you+-+recorded", status_code=303)
    except ReportError as err:
        return RedirectResponse(f"/prices?err={e(str(err))}", status_code=303)


# -------------------------------------------------------- note, ranking --
@app.get("/note", response_class=HTMLResponse)
def note(request: Request):
    user, redirect = need_login(request)
    if redirect:
        return redirect
    notes = sorted(NOTES.glob("weekly_*.html"))
    if not notes:
        return page("Weekly note", "<p>The first weekly note has not been published yet.</p>", user)
    return HTMLResponse(notes[-1].read_text(encoding="utf-8"))


@app.get("/leaderboard", response_class=HTMLResponse)
def leaderboard(request: Request):
    user, redirect = need_login(request)
    if redirect:
        return redirect
    names = {p["handle"]: p for p in people().all()}
    rows = "".join(f"<tr><td>{i}</td><td>{e(names.get(r['account'], {}).get('name', r['account']))}</td>"
                   f"<td>{e(names.get(r['account'], {}).get('org') or '')}</td><td>{r['total']:,.1f}</td></tr>"
                   for i, r in enumerate(ex().leaderboard(), 1))
    return page("Leaderboard", f"""<div class=card><h1>Leaderboard</h1><p class=mut>Points plus open positions at
current prices. Good forecasters rise as contracts settle.</p><div class=tw><table>
<tr><th>#</th><th>Name</th><th>Organisation</th><th>Points</th></tr>{rows}</table></div></div>""", user)


# ---------------------------------------------------------------- admin --
def _admin_ok(key: str) -> bool:
    expected = os.environ.get("CIO_ADMIN_KEY")
    return bool(expected) and key == expected


@app.get("/admin", response_class=HTMLResponse)
def admin(key: str = "", made: str = ""):
    if not _admin_ok(key):
        return HTMLResponse("Forbidden", status_code=403)
    opts = "".join(f"<option value={c}>{e(v['country'])}</option>" for c, v in COUNTRIES.items())
    rows = "".join(f"<tr><td>{e(p['name'])}</td><td>{e(p['org'] or '')}</td><td>{e(p['country'])}</td>"
                   f"<td><code>{e(p['invite_code'])}</code></td><td>{'yes' if p['active'] else ''}</td></tr>"
                   for p in people().all())
    flash = f"<p class=ok>Invite code: <b>{e(made)}</b></p>" if made else ""
    return page("Admin", f"""<div class=card><h1>Invite a participant</h1>
<form method=post action='/admin/invite?key={e(key)}'><div class=row><div><label>Name</label><input name=name required></div>
<div><label>Organisation</label><input name=org></div></div><label>Country</label><select name=country>{opts}</select>
<p><button>Create invite code</button></p></form>{flash}</div>
<div class=card><h2>Participants</h2><div class=tw><table><tr><th>Name</th><th>Organisation</th><th>Country</th>
<th>Code</th><th>Joined</th></tr>{rows}</table></div></div>""")


@app.post("/admin/invite")
def invite(key: str = "", name: str = Form(...), org: str = Form(""), country: str = Form(...)):
    if not _admin_ok(key) or country not in COUNTRIES:
        return HTMLResponse("Forbidden", status_code=403)
    code = people().invite(name, org, country)
    return RedirectResponse(f"/admin?key={key}&made={code}", status_code=303)
