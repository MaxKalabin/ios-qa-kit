"""mitmproxy addon for iOS QA.

Run:  mitmdump -s qa_addon.py --set qa_run=<name> --listen-port 8080

Storage (traffic/<run>.db, SQLite, safe for heavy websocket traffic):
  flows(id, ts, case_id, method, url, host, status, dur_s, req_body, resp_body, flags, rule)
  ws(id, ts, case_id, host, url, direction, size, data)      -- every websocket message
  tunnels(ts, case_id, host, up, down)                       -- non-decrypted hosts
Plus traffic/<run>.jsonl: one short line per HTTP flow / ws connection summary
(no message bodies) so a human or LLM can skim it without choking.

Current test case: write its ID to traffic/CURRENT_CASE.
Fault injection: edit traffic/RULES.json at any time (hot-reloaded), see RULES.example.json.
"""
import json, os, re, time
try:
    import sqlite3
except ImportError:  # bundled mitmproxy has no sqlite3: JSONL only
    sqlite3 = None


class _NoDB:
    def execute(self, *a, **k): pass
    def executescript(self, *a, **k): pass
    def commit(self): pass

from mitmproxy import ctx, http

SLOW_S = 3.0
JL_BODY = 20_000            # body chars kept per jsonl line
BODY_LIMIT = 256_000          # bytes of body kept per flow/message
WS_HOSTS = tuple(h for h in os.environ.get("QA_WS_HOSTS", "").split(",") if h)
# Hosts whose HTTPS is decrypted (regex on host:port); all others are tunnelled only.
TARGETS = [h for h in os.environ.get("QA_TARGETS", "").split(",") if h]  # regex on host:port, comma-separated
TOKEN_RE = re.compile(r"(token|apikey|api_key|access_token|password|secret)=", re.I)
PII_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|\+?\d[\d\s().-]{9,}\d")


def _txt(b):
    if not b:
        return ""
    return b[:BODY_LIMIT].decode("utf-8", "replace")


class QA:
    def __init__(self):
        self.db = None
        self.ws_stats = {}
        self.seen = {}
        self.rules = []
        self.rules_mtime = 0

    # ---------- setup ----------
    def load(self, loader):
        here = os.path.dirname(os.path.abspath(__file__))
        loader.add_option("qa_run", str, time.strftime("%Y%m%d-%H%M%S"), "run name")
        loader.add_option("qa_dir", str, os.path.join(here, "..", "traffic"), "output dir")

    def configure(self, updated):
        if "allow_hosts" in updated and not ctx.options.allow_hosts:
            ctx.options.allow_hosts = TARGETS

    def _open(self):
        if self.db is not None:
            return
        d = ctx.options.qa_dir
        os.makedirs(d, exist_ok=True)
        self.db = sqlite3.connect(os.path.join(d, ctx.options.qa_run + ".db"), check_same_thread=False) if sqlite3 else _NoDB()
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS flows(id INTEGER PRIMARY KEY, ts REAL, case_id TEXT, method TEXT, url TEXT,
          host TEXT, status INT, dur_s REAL, req_body TEXT, resp_body TEXT, flags TEXT, rule TEXT);
        CREATE TABLE IF NOT EXISTS ws(id INTEGER PRIMARY KEY, ts REAL, case_id TEXT, host TEXT, url TEXT,
          direction TEXT, size INT, data TEXT);
        CREATE TABLE IF NOT EXISTS tunnels(ts REAL, case_id TEXT, host TEXT, up INT, down INT);
        CREATE INDEX IF NOT EXISTS i_flows_url ON flows(url);
        CREATE INDEX IF NOT EXISTS i_ws_case ON ws(case_id);
        """)
        self.jl = open(os.path.join(d, ctx.options.qa_run + ".jsonl"), "a", encoding="utf-8")

    def _case(self):
        try:
            return open(os.path.join(ctx.options.qa_dir, "CURRENT_CASE")).read().strip()
        except OSError:
            return ""

    def _jl(self, obj):
        self.jl.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.jl.flush()

    # ---------- fault-injection rules ----------
    def _load_rules(self):
        p = os.path.join(ctx.options.qa_dir, "RULES.json")
        try:
            m = os.path.getmtime(p)
        except OSError:
            self.rules = []
            return
        if m != self.rules_mtime:
            self.rules_mtime = m
            try:
                self.rules = json.load(open(p, encoding="utf-8"))
                ctx.log.info(f"qa: loaded {len(self.rules)} rules")
            except Exception as e:
                ctx.log.warn(f"qa: bad RULES.json: {e}")
                self.rules = []

    def _match(self, flow, when):
        self._load_rules()
        for r in self.rules:
            if r.get("when", "response") != when or r.get("enabled", True) is False:
                continue
            if r.get("times") is not None and r.get("_used", 0) >= r["times"]:
                continue
            if r.get("method") and r["method"].upper() != flow.request.method:
                continue
            if not re.search(r.get("url", ".*"), flow.request.pretty_url):
                continue
            if r.get("body_match") and not re.search(r["body_match"], flow.request.get_text(strict=False) or ""):
                continue
            r["_used"] = r.get("_used", 0) + 1
            return r
        return None

    def _apply(self, flow, r, when):
        """actions: block, status, delay_s, set_header, replace_body, json_set"""
        a = r.get("action", {})
        msg = flow.request if when == "request" else flow.response
        if "delay_s" in a:
            time.sleep(a["delay_s"])
        if "remove_header" in a:
            for k in a["remove_header"]:
                msg.headers.pop(k, None)
        if "set_query" in a and when == "request":   # {"page": "999", "lang": null -> delete}
            for k, v in a["set_query"].items():
                if v is None:
                    flow.request.query.pop(k, None)
                else:
                    flow.request.query[k] = str(v)
        if "set_header" in a:
            for k, v in a["set_header"].items():
                msg.headers[k] = v
        if "replace_body" in a:
            msg.text = a["replace_body"]
        if "json_set" in a:   # {"a.b.0.c": value}
            try:
                data = json.loads(msg.text)
                for path, val in a["json_set"].items():
                    cur = data
                    keys = path.split(".")
                    for k in keys[:-1]:
                        cur = cur[int(k)] if isinstance(cur, list) else cur[k]
                    last = keys[-1]
                    if isinstance(cur, list):
                        cur[int(last)] = val
                    else:
                        cur[last] = val
                msg.text = json.dumps(data, ensure_ascii=False)
            except Exception as e:
                ctx.log.warn(f"qa: json_set failed: {e}")
        if when == "request" and a.get("block"):
            flow.response = http.Response.make(a.get("status", 503), a.get("body", "blocked by qa rule"))
        elif when == "response" and "status" in a:
            flow.response.status_code = a["status"]
        flow.metadata["qa_rule"] = r.get("name", r.get("url"))

    # ---------- HTTP ----------
    def request(self, flow):
        r = self._match(flow, "request")
        if r:
            flow.metadata["qa_orig_req"] = {"url": flow.request.pretty_url, "body": _txt(flow.request.raw_content)[:JL_BODY]}
            self._apply(flow, r, "request")

    def response(self, flow):
        if flow.websocket:      # the 101 upgrade itself
            return
        r = self._match(flow, "response")
        if r:
            self._apply(flow, r, "response")
        self._open()
        req, resp = flow.request, flow.response
        dur = (resp.timestamp_end or 0) - req.timestamp_start
        flags = []
        if resp.status_code >= 500: flags.append("5xx")
        elif resp.status_code >= 400: flags.append("4xx")
        if dur > SLOW_S: flags.append("slow")
        if TOKEN_RE.search(req.pretty_url): flags.append("secret_in_url")
        if PII_RE.search(req.pretty_url): flags.append("pii_in_url")
        if req.scheme == "http": flags.append("plain_http")
        key = (req.method, req.pretty_url)
        self.seen[key] = self.seen.get(key, 0) + 1
        if self.seen[key] > 2 and resp.status_code >= 400: flags.append("retry")
        rule = flow.metadata.get("qa_rule")
        if rule: flags.append("injected")
        case = self._case()
        self.db.execute(
            "INSERT INTO flows(ts,case_id,method,url,host,status,dur_s,req_body,resp_body,flags,rule) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (time.time(), case, req.method, req.pretty_url, req.host, resp.status_code, round(dur, 3),
             _txt(req.raw_content), _txt(resp.get_content(strict=False)), ",".join(flags), rule))
        self.db.commit()
        self._jl({"ts": time.time(), "case": case, "method": req.method, "url": req.pretty_url,
                  "status": resp.status_code, "dur_s": round(dur, 3), "resp_bytes": len(resp.raw_content or b""),
                  "flags": flags, "rule": rule,
                  "req_body": _txt(req.raw_content)[:JL_BODY], "resp_body": _txt(resp.get_content(strict=False))[:JL_BODY],
                  "orig_req": flow.metadata.get("qa_orig_req")})

    def error(self, flow):
        self._open()
        self._jl({"ts": time.time(), "case": self._case(), "url": flow.request.pretty_url,
                  "flags": ["conn_error"], "error": str(flow.error)})

    # ---------- WebSocket: full messages go to SQLite, jsonl gets only a summary ----------
    def websocket_message(self, flow):
        self._open()
        m = flow.websocket.messages[-1]
        # tampering: rules with when=ws_in / ws_out, action.replace_body
        self._load_rules()
        for r in self.rules:
            if r.get("when") in ("ws_in", "ws_out") and r.get("enabled", True) is not False:
                if (r["when"] == "ws_in") == (not m.from_client) and re.search(r.get("url", ".*"), flow.request.pretty_url):
                    if r.get("times") is not None and r.get("_used", 0) >= r["times"]:
                        continue
                    if "match" in r and not re.search(r["match"], m.text if m.is_text else ""):
                        continue
                    r["_used"] = r.get("_used", 0) + 1
                    if "replace_body" in r.get("action", {}):
                        m.text = r["action"]["replace_body"]
                    if r.get("action", {}).get("drop"):
                        m.drop()
                    break
        d = "out" if m.from_client else "in"
        data = m.text if m.is_text else f"<binary {len(m.content)}b>"
        self.db.execute("INSERT INTO ws(ts,case_id,host,url,direction,size,data) VALUES(?,?,?,?,?,?,?)",
                        (time.time(), self._case(), flow.request.host, flow.request.pretty_url, d,
                         len(m.content), data[:BODY_LIMIT]))
        s = self.ws_stats.setdefault(flow.id, {"in": 0, "out": 0, "bytes": 0})
        s[d] += 1
        s["bytes"] += len(m.content)
        if (s["in"] + s["out"]) % 500 == 0:   # one summary line per 500 messages
            self._jl({"ts": time.time(), "case": self._case(), "ws": flow.request.pretty_url, **s})
        if (s["in"] + s["out"]) % 200 == 0:
            self.db.commit()

    def websocket_end(self, flow):
        if self.db:
            self.db.commit()
            s = self.ws_stats.pop(flow.id, {})
            self._jl({"ts": time.time(), "case": self._case(), "ws_closed": flow.request.pretty_url, **s})

    # ---------- tunnelled (not decrypted) connections ----------
    def tcp_end(self, flow):
        self._open()
        host = flow.server_conn.address[0] if flow.server_conn.address else "?"
        up = sum(len(m.content) for m in flow.messages if m.from_client)
        down = sum(len(m.content) for m in flow.messages if not m.from_client)
        self.db.execute("INSERT INTO tunnels VALUES(?,?,?,?,?)", (time.time(), self._case(), host, up, down))
        self.db.commit()


addons = [QA()]

