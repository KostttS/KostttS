#!/usr/bin/env python3
"""Hourly public Threads buyer-request scan; does not publish replies.

Discovers publicly served posts by high-intent RU/EN queries.
A match is a lead CANDIDATE, not proof of budget, legitimacy or authorization.
Never use public PK as Threads Graph reply_to_id.
"""
import json
import os
import time
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
    if previous.get("last_hour")==hour:
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
    leads=sorted(rows.values(),key=lambda x:(x["first_seen_by_scanner"],x["timestamp"]),reverse=True)
    out={
        "checked_at":now.isoformat(),
        "status":"public_lead_candidates_found" if leads else "no_verified_public_buyer_candidates",
        "coverage":"bounded_public_threads_keyword_sample_not_all_threads",
        "queries":QUERIES,"pages_checked":len(diagnostics),
        "pages_with_public_posts":sum(x.get("embedded_posts",0)>0 for x in diagnostics),
        "time_budget_exhausted":budget_exhausted,
        "unique_buyer_candidates":len(leads),
        "newly_discovered_candidates":sum(x["first_seen_by_scanner"] for x in leads),
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
    save(STATE,{"last_hour":hour,"last_scan_at":now.isoformat(),"seen":saved})
    print(f"Threads hourly buyer hunt: {len(leads)} candidates ({sum(x['first_seen_by_scanner'] for x in leads)} new), {len(diagnostics)} search pages")

if __name__=="__main__":
    main()
