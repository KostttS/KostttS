#!/usr/bin/env python3
"""Hourly public Threads buyer-request scan; does not publish replies.

Discovers publicly served posts by high-intent RU/EN queries.
A match is a lead CANDIDATE, not proof of budget, legitimacy or authorization.
Never use public PK as Threads Graph reply_to_id.
"""
import json
import os
import time
import re
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from discover_public_trends import fetch, normalize, buyer_signal

ROOT=Path(__file__).resolve().parent
OUT=ROOT/"lead_discovery.json"
STATE=ROOT/"lead_hunt_state.json"
QUERIES=[
    "looking for developer", "need mobile app developer", "hire Flutter",
    "FlutterFlow developer", "Flutter developer", "app developer",
    "looking for app developer", "need app built",
    "нужен разработчик", "ищу разработчика",
    "FlutterFlow", "разработчик приложения",
    "restaurant app", "MVP app",
]
SELF="konstantin47209"
VERSION=2


def fingerprint(text):
    value=" ".join((text or "").lower().split())
    value=re.sub(r"https?://\S+|@\w+|#\w+","",value)
    value=re.sub(r"[^a-zа-яё0-9]+"," ",value)
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()[:20]


def disqualifiers(text):
    value=(text or "").lower()
    out=[]
    if any(s in value for s in ("commission-based", "commission only", "work on commission", "за процент", "оплата процент")):
        out.append("commission_only")
    if any(s in value for s in ("indonesia only","only indonesia", "send us your cv", "send your cv", "присылайте резюме", "вакансия в штат")):
        out.append("location_or_employment_restrictions")
    # Employee recruitment ads are not paid client development briefs.
    # Require BOTH a hiring marker and a payroll/HR marker to avoid filtering
    # genuine project briefs that merely say they are hiring a contractor.
    hiring_markers=("we are hiring", "we\u0027re hiring", "job vacancy", "job opening", "вакансия", "ищем в штат")
    employment_markers=("salary", "notice period", "full-time", "full time", "monthly pay", "зарплата", "оклад")
    internship_markers=("internship", "developer intern", "flutter intern", "стажёр", "стажер", "стажировка")
    internship_recruitment_markers=("looking for", "hiring", "apply", "career", "freshers welcome", "вакансия", "ищем")
    if (any(s in value for s in hiring_markers) and any(s in value for s in employment_markers)) or (any(s in value for s in internship_markers) and any(s in value for s in internship_recruitment_markers)):
        out.append("employee_job_ad_not_project")
    # A profit split or work before payment is not a funded mobile-app order.
    if any(s in value for s in ("no money involved until it pays", "no money until it pays", "equity only", "profit share", "profit split", "revenue share", "revenue split", "60% to you", "unpaid project", "work for exposure")):
        out.append("contingent_or_unfunded_compensation")
    # Public search often returns freelancers quoting a buyer's request.
    if any(s in value for s in ("i came across your post about looking for", "i'd love to help bring your idea to life", "here's my portfolio so you can check", "looking for a new opportunity as a flutter developer", "open to remote opportunities worldwide")):
        out.append("developer_self_promotion_not_buyer")
    return out

def load(path,default):
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError,ValueError):
        return default

def save(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n","utf-8")

def main():
    now=datetime.now(timezone.utc)
    hour=now.astimezone(ZoneInfo("Asia/Jerusalem")).strftime("%Y-%m-%d %H")
    previous=load(STATE,{"last_hour":None,"seen":{}})
    if previous.get("last_hour")==hour and previous.get("version")==VERSION:
        save(OUT,{"checked_at":now.isoformat(),"status":"already_scanned_this_local_hour",
                  "last_scan_at":previous.get("last_scan_at"),
                  "coverage":"limited_public_pages_no_automatic_replies"})
        return
    rows={}
    diagnostics=[]
    deadline=time.monotonic()+90
    old=previous.get("seen") or {}
    budget_exhausted=False
    for q in QUERIES:
        for view in ("recent","default"):
            if time.monotonic()>=deadline:
                budget_exhausted=True
                break
            posts,diag=fetch(q,view)
            diagnostics.append({"query":q,"view":view,**diag})
            for item in posts:
                row=normalize(item,q,view,now,{})
                if not row or not buyer_signal(row):
                    continue
                post_code=row["code"]
                previous_row=rows.get(post_code)
                if previous_row:
                    previous_row["matched_queries"]=sorted(set(previous_row["matched_queries"]+[q]))
                else:
                    row["first_seen_by_scanner"]=post_code not in old
                    row["lead_status"]="potential_request_unverified_budget"
                    row["verified_api_reply_id"]=None
                    row["requires_manual_or_approved_api_resolution"]=True
                    rows[post_code]=row
            time.sleep(0.22)
        if budget_exhausted:
            break
    # A repeated copy-pasted hiring announcement across unrelated accounts
    # is not automatically a second buyer or an authenticated original.
    seen_fingerprints={}
    for row in rows.values():
        fp=fingerprint(row.get("text_excerpt"))
        row["content_fingerprint"]=fp
        seen_fingerprints.setdefault(fp,set()).add(row["username"])
    for row in rows.values():
        flags=disqualifiers(row.get("text_excerpt"))
        authors=seen_fingerprints.get(row["content_fingerprint"],set())
        if len(authors)>1:
            flags.append("same_text_from_multiple_accounts")
            row["duplicate_accounts"]=sorted(authors)
        row["risk_flags"]=flags
        row["lead_status"]="review_duplicate_or_nonbuyer" if flags else "potential_request_unverified_budget"
    leads=sorted(rows.values(),key=lambda x:(not x["risk_flags"],x["first_seen_by_scanner"],x["timestamp"]),reverse=True)
    out={
        "checked_at":now.isoformat(),
        "status":"public_lead_candidates_found" if leads else "no_verified_public_buyer_candidates",
        "coverage":"bounded_public_threads_keyword_sample_not_all_threads",
        "queries":QUERIES,"pages_checked":len(diagnostics),
        "pages_with_public_posts":sum(x.get("embedded_posts",0)>0 for x in diagnostics),
        "time_budget_exhausted":budget_exhausted,
        "unique_buyer_candidates":len(leads),
        "newly_discovered_candidates":sum(x["first_seen_by_scanner"] for x in leads),
        "candidates_without_obvious_disqualifiers":sum(not x["risk_flags"] for x in leads),
        "candidates":leads[:30],"diagnostics":diagnostics,
        "guardrails":[
            "Public PK is not an official media ID; no automatic replies from this dataset.",
            "A phrase match is not verification of payment or an active project.",
            "Do not copy personal stories or quote prices/deadlines.",
            "Deduplicate with public_lead_candidates.json and replies.json before contact."
        ]
    }
    save(OUT,out)
    saved=dict(old)
    for code,row in rows.items():
        seen=saved.get(code) or {}
        saved[code]={
            "first_seen_at":seen.get("first_seen_at") or now.isoformat(),
            "last_seen_at":now.isoformat(),
            "url":row["url"],
        }
    saved=dict(list(sorted(saved.items(),key=lambda pair:pair[1]["last_seen_at"],reverse=True))[:1000])
    save(STATE,{"version":VERSION,"last_hour":hour,"last_scan_at":now.isoformat(),"seen":saved})
    print(f"Threads hourly buyer hunt: {len(leads)} candidates ({sum(x['first_seen_by_scanner'] for x in leads)} new), {len(diagnostics)} search pages")

if __name__=="__main__":
    main()
