import os, io, json, time, hashlib, datetime, sys
import requests
from PIL import Image
from cryptography.fernet import Fernet

Image.MAX_IMAGE_PIXELS = None
BASE = "https://fursys.atlassian.net"
AUTH = (os.environ["ATLASSIAN_EMAIL"], os.environ["ATLASSIAN_TOKEN"])
F = Fernet(os.environ["IMG_KEY"].encode())
DAYS = int(os.environ.get("DAYS", "10"))
SPACES = ["RD", "chairrnd"]
WORDS = ["시안", "리뷰", "샘플", "최종", "디자인", "품평"]
MIN_BYTES = 120_000
MAX_BYTES = 30_000_000
MAX_PER_PAGE = 3
MAX_NEW = 150
OK = ("image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp", "image/tiff")
os.makedirs("b", exist_ok=True)

def p(*a):
    print(*a, flush=True)

index = {}
if os.path.exists("index.json.enc"):
    try:
        index = json.loads(F.decrypt(open("index.json.enc", "rb").read()))
    except Exception as e:
        p("index decrypt failed", e)

def save():
    open("index.json.enc", "wb").write(F.encrypt(json.dumps(index, ensure_ascii=False).encode()))

def get(url, **kw):
    for i in range(3):
        try:
            r = requests.get(url, auth=AUTH, timeout=40, **kw)
            if r.status_code == 200:
                return r
            p("http", r.status_code, url[:90], r.text[:200])
        except Exception as e:
            p("err", e)
        time.sleep(2)
    return None

p("start days", DAYS)
since = (datetime.date.today() - datetime.timedelta(days=DAYS)).isoformat()
cql = ('type = page AND lastmodified >= "%s" AND space in ("%s") AND (%s) ORDER BY lastmodified DESC'
       % (since, '","'.join(SPACES), " OR ".join('title ~ "%s"' % w for w in WORDS)))
p(cql)
pages, seen, start = [], set(), 0
while start < 500:
    r = get(BASE + "/wiki/rest/api/content/search", params={"cql": cql, "limit": 25, "start": start, "expand": "version,space"})
    if not r:
        break
    res = r.json()["results"]
    new = [x for x in res if x["id"] not in seen]
    p("search start", start, "got", len(res), "new", len(new))
    if not new:
        break
    for x in new:
        seen.add(x["id"])
    pages += new
    start += 25
p("pages", len(pages))
n_new = 0
for k, pg in enumerate(pages):
    if n_new >= MAX_NEW:
        break
    pid = pg["id"]
    try:
        ent = index.get(pid) or {"title": pg["title"], "space": pg["space"]["key"], "modified": pg["version"]["when"],
                                  "url": BASE + "/wiki" + pg["_links"]["webui"], "images": []}
        ent["title"] = pg["title"]; ent["modified"] = pg["version"]["when"]
        have = {i["id"] for i in ent["images"]}
        r = get(BASE + "/wiki/rest/api/content/%s/child/attachment" % pid, params={"limit": 100, "expand": "version,extensions"})
        if not r:
            continue
        atts = [a for a in r.json()["results"]
                if a["extensions"].get("mediaType") in OK and MIN_BYTES <= a["extensions"].get("fileSize", 0) <= MAX_BYTES]
        atts.sort(key=lambda a: -a["extensions"]["fileSize"])
        p("page", k + 1, "/", len(pages), pg["title"][:30], "cands", len(atts))
        for a in atts[:MAX_PER_PAGE]:
            aid = "%s_v%s" % (a["id"], a["version"]["number"])
            if aid in have:
                continue
            try:
                d = get(BASE + "/wiki" + a["_links"]["download"])
                if not d:
                    continue
                im = Image.open(io.BytesIO(d.content)); ow, oh = im.size
                im = im.convert("RGB"); im.thumbnail((1100, 1100))
                for q in (82, 74, 66, 60):
                    buf = io.BytesIO(); im.save(buf, "JPEG", quality=q)
                    if buf.tell() < 230_000:
                        break
                name = hashlib.sha256((pid + aid).encode()).hexdigest()[:20] + ".bin"
                open("b/" + name, "wb").write(F.encrypt(buf.getvalue()))
                ent["images"].append({"id": aid, "file": name, "name": a["title"], "w": im.size[0], "h": im.size[1], "orig_w": ow, "orig_h": oh})
                n_new += 1
                p("img", pid, a["title"][:40])
            except Exception as e:
                p("skip att", a.get("title"), e)
        if ent["images"]:
            index[pid] = ent
        save()
    except Exception as e:
        p("skip page", pid, e)
save()
p("new images:", n_new, "pages:", len(index))
