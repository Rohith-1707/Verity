"""VERITY API. All writes happen here, after server-side authentication, role and organisation checks."""
import json, os
from datetime import date
from functools import lru_cache

import jwt
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import create_engine, text

from . import engine as E
from .extract import ExtractError, extract_text
from .llm import LLMUnavailable, screen
from .retrieval import KeywordRetriever

app = FastAPI(title="VERITY API")
app.add_middleware(CORSMiddleware, allow_origins=[o for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o],
                   allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter


@lru_cache
def db():
    return create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)


@lru_cache
def chroma():
    from .retrieval import ChromaRetriever
    return ChromaRetriever(os.environ["CHROMA_PATH"])


def retriever_for(c, org):
    """Persistent ChromaDB when CHROMA_PATH is set; otherwise a keyword index rebuilt from the database."""
    if os.getenv("CHROMA_PATH"):
        return chroma()
    r = KeywordRetriever()
    for v in c.execute(text("""select v.document_id::text d, d.title, v.version, v.status, v.effective_date e, v.review_date rv, v.body
                               from document_versions v join documents d on d.id=v.document_id where v.org_id=:o and v.status in ('approved','superseded')"""), {"o": org}).mappings():
        r.index(org, v["d"], v["title"], v["version"], v["status"], v["e"], v["rv"], v["body"])
    return r


@lru_cache
def jwks():
    return jwt.PyJWKClient(os.environ["SUPABASE_URL"].rstrip("/") + "/auth/v1/.well-known/jwks.json")


def token_payload(authorization):
    """Verify a Supabase token: the legacy shared secret (HS256) or the project's public signing keys (ES256/RS256)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing token")
    tok = authorization[7:]
    try:
        alg = jwt.get_unverified_header(tok).get("alg")
        if alg == "HS256":
            return jwt.decode(tok, os.environ["SUPABASE_JWT_SECRET"], algorithms=["HS256"], audience="authenticated")
        if alg in ("ES256", "RS256"):
            return jwt.decode(tok, jwks().get_signing_key_from_jwt(tok).key, algorithms=[alg], audience="authenticated")
    except Exception:
        pass
    raise HTTPException(401, "Invalid or expired token")


def current_user(authorization: str = Header(None)):
    p = token_payload(authorization)
    with db().begin() as c:
        row = c.execute(text("select org_id::text org, role, display_name name, blocked from profiles where id=:i"), {"i": p["sub"]}).mappings().first()
    if not row or row["blocked"]:
        raise HTTPException(403, "No active profile for this account")
    return {"id": p["sub"], **row}


def need(*roles):
    def dep(u=Depends(current_user)):
        if u["role"] not in roles:
            raise HTTPException(403, "Your role cannot perform this action")
        return u
    return dep


def audit(c, u, action, detail=""):
    c.execute(text("insert into audit_logs(org_id,actor_id,action,detail) values (:o,:a,:x,:d)"), {"o": u["org"], "a": u["id"], "x": action, "d": detail})


def notify(c, org, message, role=None, user=None):
    c.execute(text("insert into notifications(org_id,user_id,role,message) values (:o,:u,:r,:m)"), {"o": org, "u": user, "r": role, "m": message})


class Register(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    role: str = "creator"
    org_name: str | None = Field(None, max_length=120)
    org_id: str | None = None


@app.post("/api/register")
@limiter.limit("10/minute")
def register(request: Request, body: Register, authorization: str = Header(None)):
    p = token_payload(authorization)
    with db().begin() as c:
        if c.execute(text("select 1 from profiles where id=:i"), {"i": p["sub"]}).first():
            raise HTTPException(409, "Profile already exists")
        if body.org_name:  # the first person creates the organisation and becomes its administrator
            org = c.execute(text("insert into organisations(name) values (:n) returning id::text"), {"n": body.org_name}).scalar()
            role = "admin"
        elif body.org_id and body.role in ("creator", "reviewer"):
            org, role = body.org_id, body.role
            if not c.execute(text("select 1 from organisations where id=cast(:o as uuid)"), {"o": org}).first():
                raise HTTPException(404, "Organisation not found")
        else:
            raise HTTPException(422, "Provide org_name to create an organisation, or org_id and a creator/reviewer role to join one")
        c.execute(text("insert into profiles(id,org_id,display_name,role) values (:i,cast(:o as uuid),:n,:r)"), {"i": p["sub"], "o": org, "n": body.display_name, "r": role})
        audit(c, {"org": org, "id": p["sub"]}, "Registered", role)
    return {"org_id": org, "role": role}


@app.get("/api/me")
def me(u=Depends(current_user)):
    return u


@app.post("/api/documents")
@limiter.limit("20/minute")
async def upload_document(request: Request, title: str = Form(..., max_length=200), category: str = Form("Policy"), version: str = Form("1"),
                          effective_date: date | None = Form(None), review_date: date | None = Form(None),
                          file: UploadFile = File(...), u=Depends(need("admin"))):
    try:
        body = extract_text(file.filename or "", await file.read())
    except ExtractError as e:
        raise HTTPException(422, str(e))
    org, impacts = u["org"], []
    with db().begin() as c:
        ret = retriever_for(c, org)
        doc = c.execute(text("select id::text from documents where org_id=cast(:o as uuid) and title=:t"), {"o": org, "t": title}).scalar()
        if doc:
            old = c.execute(text("select body from document_versions where document_id=cast(:d as uuid) and status='approved' order by uploaded_at desc limit 1"), {"d": doc}).scalar()
            c.execute(text("update document_versions set status='superseded' where document_id=cast(:d as uuid) and status='approved'"), {"d": doc})
            ret.set_status(org, doc, "superseded")
            if old:
                subs = c.execute(text("""select distinct on (s.id) s.id::text id, v.body text from submissions s join submission_versions v on v.submission_id=s.id
                                         where s.org_id=cast(:o as uuid) and s.status<>'rejected' order by s.id, v.n desc"""), {"o": org}).mappings().all()
                impacts = E.find_impacts(old, body, [dict(s) for s in subs])
        else:
            doc = c.execute(text("insert into documents(org_id,title,category,created_by) values (cast(:o as uuid),:t,:c,cast(:u as uuid)) returning id::text"),
                            {"o": org, "t": title, "c": category, "u": u["id"]}).scalar()
        c.execute(text("""insert into document_versions(document_id,org_id,version,effective_date,review_date,body,uploaded_by)
                          values (cast(:d as uuid),cast(:o as uuid),:v,:e,:r,:b,cast(:u as uuid))"""), {"d": doc, "o": org, "v": version, "e": effective_date, "r": review_date, "b": body, "u": u["id"]})
        ret.index(org, doc, title, version, "approved", effective_date, review_date, body)
        for h in impacts:
            c.execute(text("insert into impacts(org_id,submission_id,document_id,old_text,sentence,location) values (cast(:o as uuid),cast(:s as uuid),cast(:d as uuid),:t,:x,:l)"),
                      {"o": org, "s": h["content_id"], "d": doc, "t": h["old_text"], "x": h["sentence"], "l": h["location"]})
        if impacts:
            notify(c, org, f"{len(impacts)} registered content item(s) may contain outdated information after \"{title}\" changed.", role="reviewer")
        audit(c, u, "Approved document", f"{title} v{version}")
    return {"document_id": doc, "characters": len(body), "impacts_found": len(impacts)}


@app.get("/api/documents")
def list_documents(u=Depends(current_user)):
    with db().begin() as c:
        rows = c.execute(text("""select d.title, d.category, v.version, v.status, v.effective_date, v.review_date, v.uploaded_at from document_versions v
                                 join documents d on d.id=v.document_id where v.org_id=cast(:o as uuid) order by v.uploaded_at desc"""), {"o": u["org"]}).mappings().all()
    return [dict(r) for r in rows]


class Guideline(BaseModel):
    kind: str = Field(pattern="^(banned|required)$")
    value: str = Field(min_length=1, max_length=300)
    reason: str | None = Field(None, max_length=300)
    platform: str = "Any"


@app.post("/api/guidelines")
def add_guideline(g: Guideline, u=Depends(need("admin"))):
    with db().begin() as c:
        c.execute(text("insert into guidelines(org_id,kind,value,reason,platform) values (cast(:o as uuid),:k,:v,:r,:p)"), {"o": u["org"], "k": g.kind, "v": g.value, "r": g.reason, "p": g.platform})
        audit(c, u, "Added guideline", f"{g.kind}: {g.value}")
    return {"ok": True}


@app.get("/api/guidelines")
def list_guidelines(u=Depends(current_user)):
    with db().begin() as c:
        return [dict(r) for r in c.execute(text("select kind,value,reason,platform from guidelines where org_id=cast(:o as uuid)"), {"o": u["org"]}).mappings()]


class Content(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=20000)
    context: dict = {}
    deadline: date | None = None
    skip_ai: bool = False


def pipeline(org, body, ctx, skip_ai):
    """Validate, retrieve evidence, check freshness and guidelines, screen with AI, assess risk."""
    with db().begin() as c:
        if not c.execute(text("select 1 from document_versions where org_id=cast(:o as uuid) and status='approved' limit 1"), {"o": org}).first():
            raise HTTPException(409, "No approved documents exist. An administrator must add evidence before content can be verified.")
        g = c.execute(text("select kind,value,reason,platform from guidelines where org_id=cast(:o as uuid)"), {"o": org}).mappings().all()
        ret = retriever_for(c, org)
    findings = [E.classify_claim(cl, ret.search(org, cl, "approved"), ret.search(org, cl, "superseded"), min_score=ret.min_score, strong=ret.strong) for cl in E.extract_claims(body)]
    findings += E.check_guidelines(body, ctx, [x for x in g if x["kind"] == "banned"], [x for x in g if x["kind"] == "required"])
    if skip_ai:
        ai = {"skipped": True}
    else:
        try:
            ai = screen(body, ctx)
        except LLMUnavailable as e:
            raise HTTPException(502, f"{e} You may retry or submit without AI analysis.")
        findings += [{"type": "ai", "claim": f"AI signal: \"{str(s.get('quote', ''))[:120]}\"", "why": str(s.get("issue", "")), "evidence": None, "fix": None} for s in ai.get("signals", [])[:8]]
    return findings, E.assess_risk(findings), ai


def save_version(c, org, sid, n, body, findings, risk, ai):
    c.execute(text("insert into submission_versions(submission_id,org_id,n,body,findings,risk,ai) values (cast(:s as uuid),cast(:o as uuid),:n,:b,cast(:f as jsonb),cast(:r as jsonb),cast(:a as jsonb))"),
              {"s": sid, "o": org, "n": n, "b": body, "f": json.dumps(findings), "r": json.dumps(risk), "a": json.dumps(ai)})


@app.post("/api/submissions")
@limiter.limit("20/minute")
def create_submission(request: Request, body: Content, u=Depends(need("creator"))):
    findings, risk, ai = pipeline(u["org"], body.text, body.context, body.skip_ai)
    with db().begin() as c:
        sid = c.execute(text("insert into submissions(org_id,creator_id,title,context,deadline) values (cast(:o as uuid),cast(:u as uuid),:t,cast(:c as jsonb),:d) returning id::text"),
                        {"o": u["org"], "u": u["id"], "t": body.title, "c": json.dumps(body.context), "d": body.deadline}).scalar()
        save_version(c, u["org"], sid, 1, body.text, findings, risk, ai)
        notify(c, u["org"], f"New submission \"{body.title}\" ({risk['level']} risk) awaits review.", role="reviewer")
        audit(c, u, "Submitted content", f"{body.title} - {risk['level']} risk")
    return {"id": sid, "risk": risk, "findings": findings, "ai": ai}


class Revision(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    skip_ai: bool = False


@app.post("/api/submissions/{sid}/revise")
@limiter.limit("20/minute")
def revise(request: Request, sid: str, body: Revision, u=Depends(need("creator"))):
    with db().begin() as c:
        s = c.execute(text("select title, context, status from submissions where id=cast(:s as uuid) and org_id=cast(:o as uuid) and creator_id=cast(:u as uuid)"),
                      {"s": sid, "o": u["org"], "u": u["id"]}).mappings().first()
        prev = c.execute(text("select n, body, findings from submission_versions where submission_id=cast(:s as uuid) order by n desc limit 1"), {"s": sid}).mappings().first() if s else None
    if not s:
        raise HTTPException(404, "Submission not found")
    if s["status"] == "approved":
        raise HTTPException(409, "Approved content cannot be revised. Submit new content instead.")
    findings, risk, ai = pipeline(u["org"], body.text, s["context"], body.skip_ai)
    with db().begin() as c:
        save_version(c, u["org"], sid, prev["n"] + 1, body.text, findings, risk, ai)
        c.execute(text("update submissions set status='pending' where id=cast(:s as uuid)"), {"s": sid})
        notify(c, u["org"], f"\"{s['title']}\" was revised (v{prev['n'] + 1}) and awaits review.", role="reviewer")
        audit(c, u, "Resubmitted", f"{s['title']} v{prev['n'] + 1}")
    return {"version": prev["n"] + 1, "risk": risk, "findings": findings, "ai": ai, "diff": E.diff_words(prev["body"], body.text), "changes": E.compare_versions(prev["findings"], findings)}


@app.get("/api/submissions")
def list_submissions(u=Depends(current_user)):
    own = "and s.creator_id=cast(:u as uuid)" if u["role"] == "creator" else ""
    with db().begin() as c:
        rows = c.execute(text(f"""select distinct on (s.id) s.id::text id, s.title, s.status, s.deadline, s.created_at, v.n version, v.risk->>'level' risk, v.findings
                                  from submissions s join submission_versions v on v.submission_id=s.id where s.org_id=cast(:o as uuid) {own} order by s.id, v.n desc"""),
                         {"o": u["org"], "u": u["id"]}).mappings().all()
    out = []
    for r in rows:
        issues = [f for f in r["findings"] if f["type"] != "verified"]
        out.append({**{k: r[k] for k in ("id", "title", "status", "deadline", "created_at", "version", "risk")}, "issues": len(issues),
                    "priority": {"High": 30, "Medium": 15, "Low": 5}[r["risk"]] + len(issues) + 5 * sum(f["type"] == "contradictory" for f in r["findings"])})
    return sorted(out, key=lambda x: -x["priority"])


@app.get("/api/submissions/{sid}")
def get_submission(sid: str, u=Depends(current_user)):
    with db().begin() as c:
        s = c.execute(text("select id::text id,title,status,context,deadline,creator_id::text creator from submissions where id=cast(:s as uuid) and org_id=cast(:o as uuid)"), {"s": sid, "o": u["org"]}).mappings().first()
        if not s or (u["role"] == "creator" and s["creator"] != u["id"]):
            raise HTTPException(404, "Submission not found")
        vs = [dict(v) for v in c.execute(text("select n,body,findings,risk,ai,created_at from submission_versions where submission_id=cast(:s as uuid) order by n"), {"s": sid}).mappings()]
        ds = [dict(d) for d in c.execute(text("select action,genuineness,comment,version_n,created_at from decisions where submission_id=cast(:s as uuid) order by created_at"), {"s": sid}).mappings()]
    changes = E.compare_versions(vs[-2]["findings"], vs[-1]["findings"]) if len(vs) > 1 else None
    diff = E.diff_words(vs[-2]["body"], vs[-1]["body"]) if len(vs) > 1 else None
    return {**dict(s), "versions": vs, "decisions": ds, "changes": changes, "diff": diff}


class Decision(BaseModel):
    action: str = Field(pattern="^(approved|revision|rejected)$")
    genuineness: str = Field(pattern="^(Genuine|Misleading|Cannot determine)$")
    comment: str = Field("", max_length=2000)


@app.post("/api/submissions/{sid}/decision")
def decide(sid: str, d: Decision, u=Depends(need("reviewer"))):
    with db().begin() as c:
        s = c.execute(text("select title, creator_id::text creator, status from submissions where id=cast(:s as uuid) and org_id=cast(:o as uuid)"), {"s": sid, "o": u["org"]}).mappings().first()
        v = c.execute(text("select n, risk->>'level' level from submission_versions where submission_id=cast(:s as uuid) order by n desc limit 1"), {"s": sid}).mappings().first() if s else None
        if not s:
            raise HTTPException(404, "Submission not found")
        if s["status"] != "pending":
            raise HTTPException(409, "This submission is not awaiting review")
        if d.action == "approved" and d.genuineness == "Misleading":
            raise HTTPException(422, "Content judged misleading cannot be approved")
        if d.action != "approved" and not d.comment.strip() or d.action == "approved" and v["level"] == "High" and not d.comment.strip():
            raise HTTPException(422, "A written comment is required for this decision")
        c.execute(text("insert into decisions(submission_id,org_id,reviewer_id,version_n,action,genuineness,comment) values (cast(:s as uuid),cast(:o as uuid),cast(:r as uuid),:n,:a,:g,:c)"),
                  {"s": sid, "o": u["org"], "r": u["id"], "n": v["n"], "a": d.action, "g": d.genuineness, "c": d.comment})
        c.execute(text("update submissions set status=:a where id=cast(:s as uuid)"), {"a": d.action, "s": sid})
        notify(c, u["org"], f"\"{s['title']}\" was {d.action} by {u['name']}.", user=s["creator"])
        audit(c, u, f"Decision {d.action}", s["title"])
    return {"status": d.action}


@app.get("/api/impacts")
def impacts(u=Depends(need("admin", "reviewer"))):
    with db().begin() as c:
        return [dict(r) for r in c.execute(text("""select i.id::text id, d.title document, s.title content, i.old_text, i.sentence, i.location, i.status
                                                   from impacts i join submissions s on s.id=i.submission_id left join documents d on d.id=i.document_id
                                                   where i.org_id=cast(:o as uuid) order by i.created_at desc"""), {"o": u["org"]}).mappings()]


@app.post("/api/impacts/{iid}/resolve")
def resolve_impact(iid: str, u=Depends(need("admin", "reviewer"))):
    with db().begin() as c:
        n = c.execute(text("update impacts set status='resolved' where id=cast(:i as uuid) and org_id=cast(:o as uuid)"), {"i": iid, "o": u["org"]}).rowcount
        if not n:
            raise HTTPException(404, "Impact not found")
        audit(c, u, "Resolved impact", iid)
    return {"ok": True}


@app.get("/api/brand-health")
def brand_health(u=Depends(need("admin", "reviewer"))):
    with db().begin() as c:
        rows = c.execute(text("""select distinct on (s.id) s.status, v.risk->>'level' level, v.findings, v.created_at from submissions s join submission_versions v on v.submission_id=s.id
                                 where s.org_id=cast(:o as uuid) order by s.id, v.n desc"""), {"o": u["org"]}).mappings().all()
        open_impacts = c.execute(text("select count(distinct submission_id) from impacts where org_id=cast(:o as uuid) and status='open'"), {"o": u["org"]}).scalar()
    if not rows:
        return {"score": None, "message": "Not enough data. Verify content to calculate a score."}
    n = len(rows)
    claims = [f for r in rows for f in r["findings"] if f["type"] in ("verified", "unsupported", "contradictory", "outdated", "review")]
    ev = sum(f["type"] == "verified" for f in claims) / len(claims) if claims else None
    high = sum(r["status"] in ("pending", "revision") and r["level"] == "High" for r in rows)
    done = sum(r["status"] in ("approved", "rejected") for r in rows)
    outdated = open_impacts + sum(any(f["type"] == "outdated" for f in r["findings"]) for r in rows)
    parts = [("Claims with evidence", round(35 * ev) if ev is not None else 0, 35), ("Unresolved high-risk", round(20 * (1 - high / n)), 20),
             ("Potentially outdated assets", round(15 * (1 - min(outdated, n) / n)), 15), ("Review completion", round(20 * done / n), 20)]
    return {"score": sum(p[1] for p in parts), "components": [{"measure": a, "points": b, "max": m} for a, b, m in parts],
            "period_start": min(r["created_at"] for r in rows), "submissions": n}


@app.get("/api/notifications")
def notifications(u=Depends(current_user)):
    with db().begin() as c:
        return [dict(r) for r in c.execute(text("""select id::text id, message, created_at from notifications where org_id=cast(:o as uuid)
                                                   and (user_id=cast(:u as uuid) or role=:r) order by created_at desc limit 30"""), {"o": u["org"], "u": u["id"], "r": u["role"]}).mappings()]


@app.get("/api/audit")
def audit_log(u=Depends(need("admin", "reviewer"))):
    with db().begin() as c:
        return [dict(r) for r in c.execute(text("select action, detail, actor_id::text actor, created_at from audit_logs where org_id=cast(:o as uuid) order by created_at desc limit 200"), {"o": u["org"]}).mappings()]


@app.get("/api/health")
def health():
    return {"status": "ok"}
