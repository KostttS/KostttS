#!/usr/bin/env python3
"""Read-only diagnostic: can Meta resolve public Threads lead posts into API IDs?

This never publishes or guesses reply_to_id. It checks official profile_posts,
profile_lookup and direct object lookup, and matches exact permalink/code.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parent
OUT=ROOT/"lead_id_resolution.json"
LEADS=ROOT/"public_lead_candidates.json"
BASE="https://graph.threads.net/v1.0"

def get_json(endpoint,params,token):
    params={**params,"access_token":token}
    url=f"{BASE}/{endpoint}?{urlencode(params)}"
    req=Request(url,headers={"User-Agent":"KostttS-Lead-ID-Probe/1.0"})
    try:
        with urlopen(req,timeout=12) as response:
            return json.load(response),None
    except HTTPError as error:
        try:
            payload=json.loads(error.read().decode("utf-8","replace"))
            detail=payload.get("error") or {}
            return {},{"http":error.code,"code":detail.get("code"),"subcode":detail.get("error_subcode"),"message":str(detail.get("message",""))[:200]}
        except Exception:
            return {},{"http":error.code,"message":"HTTP error"}
    except (OSError,URLError,ValueError) as error:
        return {},{"error":type(error).__name__}

def normalize_url(url):
    try:
        u=urlsplit(url)
        return (u.path.lower().replace("/%40","/@").rstrip("/"))
    except Exception:
        return ""

def scan():
    token=os.getenv("THREADS_ACCESS_TOKEN","").strip()
    if not token:
        raise RuntimeError("Missing Threads token in environment")
    leads=json.loads(LEADS.read_text("utf-8")).get("leads",[])
    result={"checked_at":datetime.now(timezone.utc).isoformat(),
            "status":"read_only_verified_api_lookup",
            "notes":"Only a returned official API ID with an exact matched permalink may be used for reply_to_id. Never substitute public PK.",
            "results":[]}
    for lead in leads[:12]:
        username=lead.get("username","")
        target_path=normalize_url(lead.get("url",""))
        row={"lead_id":lead.get("id"),"username":username,"url":lead.get("url"),"confirmed_api_media_id":None,"probes":[]}
        # Exact public profile endpoint; standard-access apps may only return Meta profiles.
        profile,err=get_json("profile_posts",{"username":username,"fields":"id,permalink,text,timestamp","limit":100},token)
        found=None
        entries=profile.get("data") or []
        for item in entries:
            if isinstance(item,dict) and normalize_url(item.get("permalink",""))==target_path and str(item.get("id","")).isdigit():
                found=item
                break
        row["probes"].append({"endpoint":"profile_posts","error":err,"returned_posts":len(entries),"exact_match":bool(found)})
        if found:
            row["confirmed_api_media_id"]=str(found["id"])
            row["proof"]={"api_permalink":found.get("permalink"),"id_source":"official_profile_posts_exact_match"}
            result["results"].append(row)
            continue
        # Additional discovery diagnostic; do not treat public PK or user ID as media ID.
        profile,err=get_json("profile_lookup",{"username":username},token)
        row["probes"].append({"endpoint":"profile_lookup","error":err,"returned_profile":bool(profile.get("username") or profile.get("data"))})
        pk=str(lead.get("public_post_pk") or "")
        if pk.isdigit():
            media,err=get_json(pk,{"fields":"id,permalink,text"},token)
            match=not err and normalize_url(media.get("permalink",""))==target_path and str(media.get("id","")).isdigit()
            row["probes"].append({"endpoint":"direct_public_pk_lookup","error":err,"exact_match":bool(match)})
            if match:
                row["confirmed_api_media_id"]=str(media["id"])
                row["proof"]={"api_permalink":media.get("permalink"),"id_source":"official_media_object_exact_match"}
        result["results"].append(row)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n","utf-8")
    print("Lead ID probe: exact confirmed API IDs",sum(bool(x.get("confirmed_api_media_id")) for x in result["results"]),"/",len(result["results"]))

if __name__=="__main__":
    scan()
