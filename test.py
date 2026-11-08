"""Exercise the actual archive on a dedicated, empty Linux Docker guest."""
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.parse import urlencode


def output(*args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def check(value, label):
    if not value:
        raise RuntimeError(label)
    print("PASS", label, flush=True)


def run(package):
    check(sys.platform == "linux" and os.geteuid() == 0 and not output("docker", "ps", "-aq"), "dedicated empty Linux engine")
    print("Archive", hashlib.sha256(package.read_bytes()).hexdigest())
    with tempfile.TemporaryDirectory(prefix="renewledger-") as folder:
        root = Path(folder)
        with tarfile.open(package) as archive:
            (root/"docker-compose.yml").write_bytes(archive.extractfile("docker-compose.yml").read())
        data = root/"data"
        data.mkdir(mode=0o700)
        os.chown(data,1000,1000)

        def compose(*args):
            return output("docker","compose","-p","renewledgertest",*args,cwd=root)

        def request(path, payload=None, auth=None):
            conn = http.client.HTTPConnection("127.0.0.1",18765,timeout=5)
            headers = {"Content-Type":"application/x-www-form-urlencoded"}
            if auth:
                headers["Authorization"] = "Basic " + base64.b64encode(("admin:"+auth).encode()).decode()
            try:
                conn.request("POST" if payload is not None else "GET", path,
                             None if payload is None else urlencode(payload), headers)
                result = conn.getresponse()
                return result.status, result.read().decode()
            finally:
                conn.close()

        def boot():
            compose("up","-d")
            for _ in range(60):
                state = json.loads(output("docker","inspect","renewledger"))[0]
                if state["State"]["Health"]["Status"] == "healthy":
                    return state
                time.sleep(1)
            raise RuntimeError("healthcheck timed out")

        try:
            state = boot()
            image = json.loads(output("docker","image","inspect",state["Image"]))[0]
            check((image["Os"],image["Architecture"]) == ("linux","amd64"),"running amd64 image")
            status = Path(f'/proc/{state["State"]["Pid"]}/status').read_text().splitlines()
            check(all(next(s.split()[1:] for s in status if s.startswith(k+":")) == ["1000"]*4 for k in ("Uid","Gid"))
                  and "NoNewPrivs:\t1" in status and int(next(s.split()[1] for s in status if s.startswith("CapEff:")),16)==0
                  and state["HostConfig"]["ReadonlyRootfs"] and not state["HostConfig"]["Privileged"], "runtime least privilege")
            check(request("/")[0] == request("/new", auth="invalid")[0] == 401, "private ledger and form")
            password_file = data/"password.txt"
            check(password_file.stat().st_mode & 0o777 == 0o600, "owner-only credential file")
            password = password_file.read_text().strip()
            def get(path):
                code, body = request(path, auth=password)
                check(code == 200, path)
                return body
            def post(path, payload):
                return request(path, payload, password)[0]
            def tokens(path):
                return dict(re.findall(r'<input type="hidden" name="(\w+)" value="([\w-]+)">',get(path)))
            item = dict(name="Studio <sample>", price="19.90", cycle="month", due="2028-01-31")
            check(post("/save",item)==403, "CSRF enforced")
            add=tokens("/new")
            check(post("/save",dict(item,**add,))==303, "create subscription")
            check(post("/save",dict(item,price="-1",**add))==400, "invalid price rejected")
            check("¥238.80" in get("/") and "&lt;sample&gt;" in get("/?q=studio") and "Studio" not in get("/?q=unknown"), "annual estimate, search and escaping")
            if os.environ.get("LEDGER_CAPTURE"):
                capture = Path(os.environ["LEDGER_CAPTURE"])
                (capture/"overview.html").write_text(get("/"))
                (capture/"edit.html").write_text(get("/edit?id=1"))
            old=tokens("/edit?id=1")
            check(post("/renew",old)==303 and "2028-02-29" in get("/"), "leap month renewal")
            check(post("/renew",old)==409, "duplicate renewal rejected")
            check(post("/renew",tokens("/edit?id=1"))==303 and "2028-03-31" in get("/"), "month-end anchor retained")
            check(post("/save",dict(item,**tokens("/edit?id=1"),due="2028-02-29",cycle="year",price="159.00"))==303, "edit billing cycle and price")
            check(post("/renew",tokens("/edit?id=1"))==303 and "2029-02-28" in get("/"), "yearly leap-day rollover")
            compose("down")
            boot()
            check("2029-02-28" in get("/") and "¥159.00" in get("/"), "credentials and ledger survive recreation")
            check(post("/delete",tokens("/delete?id=1"))==303 and "没有符合条件" in get("/"), "confirmed deletion")
        finally:
            compose("down")
    check(not root.exists() and not output("docker","ps","-aq"), "synthetic data and containers cleaned")


if __name__ == "__main__":
    run(Path(sys.argv[1]))
