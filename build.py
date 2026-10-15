#!/usr/bin/env python3
"""生成单位换算静态网站到 dist/。所有换算系数为标准定义的精确值,计算用分数避免浮点误差。"""
import html
import json
import re
import shutil
import urllib.parse
from decimal import Decimal, localcontext
from fractions import Fraction as F
from pathlib import Path

from units import CATEGORIES, COMMON, STD

ROOT = Path(__file__).parent
OUT = ROOT / "dist"
RMB_JS = (ROOT / "rmb.js").read_text(encoding="utf-8").split("if (typeof module")[0]

CSS = """
:root{--bg:#f7f8fa;--card:#fff;--text:#1d2129;--muted:#6b7280;--line:#e5e7eb;--accent:#0f766e;--soft:#ecfdf5}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a21;--text:#e6e8eb;--muted:#9aa1ac;--line:#2a2f3a;--accent:#2dd4bf;--soft:#0f2a26}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
header,main,footer{max-width:860px;margin:0 auto;padding:0 16px}
header{padding-top:16px}header .logo{font-weight:700;font-size:18px;color:var(--text)}
nav{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:15px;margin-top:6px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px;margin:16px 0}
h1{font-size:24px;line-height:1.4;margin:8px 0;overflow-wrap:anywhere}h2{font-size:19px;margin:0 0 12px}
.big{font-size:28px;font-weight:700;margin:4px 0;overflow-wrap:anywhere}.muted{color:var(--muted);font-size:14px}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}td,th{padding:8px 6px;border-bottom:1px solid var(--line);text-align:right;overflow-wrap:anywhere}
td:first-child,th:first-child{text-align:left}
.links{display:flex;flex-wrap:wrap;gap:8px 16px;font-size:15px}
.form{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;align-items:end}.form label{display:flex;flex-direction:column;font-size:14px;color:var(--muted)}
.form input,.form select,.form textarea{font-size:17px;padding:8px 10px;margin-top:4px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--text);width:100%}
.out{margin-top:12px;font-size:20px;font-weight:600;overflow-wrap:anywhere}.ad{margin:16px 0;min-height:90px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}.grid a{display:block;background:var(--soft);border-radius:10px;padding:12px;font-weight:600}
footer{padding:24px 16px;color:var(--muted);font-size:13px}
"""


def esc(s):
    return html.escape(str(s))


def og_tags(title, desc, url, site_name, locale):
    """Open Graph 与 title、description、canonical 使用同一份文案。"""
    return (
        f'<meta property="og:title" content="{esc(title)}">'
        f'<meta property="og:description" content="{esc(desc)}">'
        f'<meta property="og:url" content="{esc(url)}">'
        f'<meta property="og:type" content="website">'
        f'<meta property="og:site_name" content="{esc(site_name)}">'
        f'<meta property="og:locale" content="{locale}">'
    )


def jsonld_script(node):
    payload = {"@context": "https://schema.org"}
    payload.update(node)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    raw = raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return f'<script type="application/ld+json">{raw}</script>'


def jsonld_scripts(nodes):
    return "".join(jsonld_script(n) for n in nodes)


def faq_node(pairs):
    return {
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a in pairs
        ],
    }


def howto_node(name, steps):
    return {
        "@type": "HowTo",
        "name": name,
        "step": [{"@type": "HowToStep", "position": i, "text": text} for i, text in enumerate(steps, 1)],
    }


def breadcrumb_node(base, crumbs):
    base = base.rstrip("/")
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i, "name": cr["name"], "item": base + cr["url"]}
            for i, cr in enumerate(crumbs, 1)
        ],
    }


def website_node(name, url, lang, desc):
    return {"@type": "WebSite", "name": name, "url": url, "inLanguage": lang, "description": desc}


def webapp_node(name, url, lang, desc):
    return {
        "@type": "WebApplication",
        "name": name,
        "url": url,
        "applicationCategory": "UtilitiesApplication",
        "operatingSystem": "All",
        "inLanguage": lang,
        "description": desc,
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "CNY"},
    }


def guide_card(title, paragraph, headers, rows):
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{esc(cell)}</td>" for cell in row) + "</tr>" for row in rows)
    return f'<div class="card"><h2>{esc(title)}</h2><p>{esc(paragraph)}</p><table><tr>{head}</tr>{body}</table></div>'


def howto_card(name, steps):
    return f'<div class="card"><h2>{esc(name)}</h2>{"".join(f"<p>{esc(s)}</p>" for s in steps)}</div>'


def faq_html(pairs):
    return "\n".join(f"<p><b>{esc(q)}</b><br>{esc(a)}</p>" for q, a in pairs)

def network_html(cfg):
    """页脚"更多实用工具":同系列网站互相链接(列表见 config.json 的 network)。"""
    sites = [s for s in cfg.get("network", []) if s["url"].rstrip("/") != cfg["base_url"].rstrip("/")]
    if not sites:
        return ""
    return "<br>更多实用工具:" + " · ".join(f'<a href="{esc(s["url"])}">{esc(s["name"])}</a>' for s in sites)



def fmt(x):
    """最多 10 位有效数字,去掉末尾 0,过大过小用科学计数法。"""
    x = F(x)
    if x == 0:
        return "0"
    with localcontext() as ctx:
        ctx.prec = 10
        d = Decimal(x.numerator) / Decimal(x.denominator)
    if abs(d) >= Decimal("1e15") or abs(d) < Decimal("1e-9"):
        m, e = f"{d:.6e}".split("e")
        return f"{m.rstrip('0').rstrip('.')}×10^{int(e)}"
    s = format(d.normalize(), "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def num_slug(v):
    return fmt(v)


class Site:
    def __init__(self):
        self.cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        self.urls = []
        self.unit = {(c, u[0]): u for c, cat in CATEGORIES.items() for u in cat["units"]}
        self.pairs = {}  # 类别 -> [(a, b)]
        for c, cat in CATEGORIES.items():
            ps = []
            for a in cat["units"]:
                for b in cat["units"]:
                    if a is b:
                        continue
                    if c != "wendu":
                        r = F(a[3]) / F(b[3])
                        if not (F(1, 10**7) <= r <= 10**7):
                            continue  # 跳过差距过大、没人会查的组合(如纳米和海里)
                    ps.append((a[0], b[0]))
            self.pairs[c] = ps
        self.common_pairs = {(c, a, b) for c, a, b, _ in COMMON}

    # ----- 换算 -----
    def conv(self, c, a, b, x):
        x = F(str(x))
        if c == "wendu":
            cel = {"c": x, "f": (x - 32) * F(5, 9), "k": x - F("273.15")}[a]
            return {"c": cel, "f": cel * F(9, 5) + 32, "k": cel + F("273.15")}[b]
        return x * F(self.unit[(c, a)][3]) / F(self.unit[(c, b)][3])

    def formula(self, c, a, b):
        na, nb = self.name(c, a), self.name(c, b)
        if c == "wendu":
            f = {("c", "f"): "华氏度 = 摄氏度 × 9/5 + 32", ("f", "c"): "摄氏度 = (华氏度 − 32) × 5/9",
                 ("c", "k"): "开尔文 = 摄氏度 + 273.15", ("k", "c"): "摄氏度 = 开尔文 − 273.15",
                 ("f", "k"): "开尔文 = (华氏度 − 32) × 5/9 + 273.15", ("k", "f"): "华氏度 = (开尔文 − 273.15) × 9/5 + 32"}
            return f[(a, b)]
        return f"{nb} = {na} × {fmt(self.conv(c, a, b, 1))}"

    def name(self, c, u):
        return self.unit[(c, u)][1]

    def full(self, c, u):
        _, n, alias, _ = self.unit[(c, u)]
        return f"{n}({alias})" if alias and alias != n else n

    def url(self, c, a=None, b=None, v=None):
        p = f"/{c}/"
        if a:
            p += f"{a}-{b}/"
        if v is not None:
            p += f"{num_slug(v)}/"
        return p

    # ----- 布局 -----
    def ad(self):
        c = self.cfg.get("adsense_client")
        if not c:
            return ""
        return (f'<div class="ad"><ins class="adsbygoogle" style="display:block" data-ad-client="{esc(c)}" data-ad-format="auto" '
                'data-full-width-responsive="true"></ins><script>(adsbygoogle=window.adsbygoogle||[]).push({});</script></div>')

    def write(self, path, title, desc, body, *, crumbs=None, faq=None, howto=None, home=False):
        cfg = self.cfg
        ads = ""
        if cfg.get("adsense_client"):
            ads = (f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client='
                   f'{esc(cfg["adsense_client"])}" crossorigin="anonymous"></script>')
        nav = "".join(f'<a href="/{c}/">{cat["name"]}</a>' for c, cat in CATEGORIES.items())
        prefix = urllib.parse.urlparse(cfg["base_url"]).path.rstrip("/")
        base = cfg["base_url"].rstrip("/")
        canon = base + path
        # 英文版 build_en.py 会在 x-default 后面补上对应的 en alternate。没有英文版的页面保持自指。
        alternates = (
            f'<link rel="alternate" hreflang="zh-CN" href="{esc(canon)}">'
            f'<link rel="alternate" hreflang="x-default" href="{esc(canon)}">'
        )
        nodes = []
        if home:
            nodes.append(website_node(cfg["site_name"], canon, "zh-CN", desc))
            nodes.append(webapp_node(cfg["site_name"], canon, "zh-CN", desc))
        else:
            if not crumbs or crumbs[-1]["url"] != path:
                raise SystemExit(f"面包屑末项必须是当前页: {path}")
            nodes.append(breadcrumb_node(base, crumbs))
        if howto:
            nodes.append(howto_node(howto["name"], howto["steps"]))
        if faq:
            questions = [q for q, _ in faq]
            if len(questions) != len(set(questions)):
                raise SystemExit(f"重复的 FAQ 问题: {path}")
            nodes.append(faq_node(faq))
        page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{esc(canon)}">{alternates}{og_tags(title, desc, canon, cfg["site_name"], "zh_CN")}{jsonld_scripts(nodes)}{ads}<style>{CSS}</style></head><body>
<header><a class="logo" href="/">{esc(cfg["site_name"])}</a><nav>{nav}<a href="/daxie/">金额大写</a><a href="/bmi/">BMI</a></nav></header>
<main>{body}</main>
<footer>换算系数采用国际单位制及国家标准规定的定义值,计算结果最多保留 10 位有效数字,仅供参考。{network_html(cfg)}</footer>
</body></html>""".replace('href="/', f'href="{prefix}/')
        f = OUT / path.strip("/") / "index.html"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(page, encoding="utf-8")
        self.urls.append(path)

    # ----- 组件 -----
    def converter(self, c, a, b, x=1):
        na, nb = self.name(c, a), self.name(c, b)
        if c == "wendu":
            fwd = {"c": "x", "f": "(x-32)*5/9", "k": "x-273.15"}[a]
            back = {"c": "C", "f": "C*9/5+32", "k": "C+273.15"}[b]
            inv_a = {"c": "y", "f": "(y-32)*5/9", "k": "y-273.15"}[b]
            inv_b = {"c": "C", "f": "C*9/5+32", "k": "C+273.15"}[a]
            f1 = f"function(x){{var C={fwd};return {back}}}"
            f2 = f"function(y){{var C={inv_a};return {inv_b}}}"
        else:
            r = float(self.conv(c, a, b, 1))
            f1, f2 = f"function(x){{return x*{r!r}}}", f"function(y){{return y/{r!r}}}"
        return f"""<div class="card"><h2>{na}{nb}换算器</h2><div class="form">
<label>{esc(na)}<input id="x" type="number" inputmode="decimal" value="{fmt(x)}"></label>
<label>{esc(nb)}<input id="y" type="number" inputmode="decimal"></label></div>
<script>(function(){{var F={f1},G={f2},x=document.getElementById('x'),y=document.getElementById('y');
function p(v){{return isFinite(v)?+v.toPrecision(10):''}}x.oninput=function(){{y.value=x.value===''?'':p(F(+x.value))}};
y.oninput=function(){{x.value=y.value===''?'':p(G(+y.value))}};x.oninput();}})();</script></div>"""

    def table(self, c, a, b, values, link=False):
        na, nb = self.name(c, a), self.name(c, b)
        rows = []
        for v in values:
            left = f"{fmt(v)} {na}"
            if link and (c, a, b) in self.common_pairs:
                left = f'<a href="{self.url(c, a, b, v)}">{left}</a>'
            rows.append(f"<tr><td>{left}</td><td>{fmt(self.conv(c, a, b, v))} {nb}</td></tr>")
        return f"<table><tr><th>{esc(na)}</th><th>{esc(nb)}</th></tr>{''.join(rows)}</table>"

    def values_for(self, c, a, b):
        for cc, aa, bb, vals in COMMON:
            if (cc, aa, bb) == (c, a, b):
                return vals
        return [-40, -10, 0, 10, 20, 30, 37, 50, 100] if c == "wendu" else STD

    def fconv(self, c, a, b, v):
        return fmt(self.conv(c, a, b, v))

    def base_faq(self, c, a, b):
        """和原先对照页「常见问题」两问的可见文字保持一致。"""
        na, nb = self.name(c, a), self.name(c, b)
        return [
            (f"1{na}等于多少{nb}?", f"1 {self.full(c, a)} 等于 {self.fconv(c, a, b, 1)} {self.full(c, b)}。"),
            (f"{nb}怎么换算成{na}?", f"{self.formula(c, b, a)}。例如 10 {nb} = {self.fconv(c, b, a, 10)} {na}。"),
        ]

    def key_content(self, c, a, b):
        """斤↔公斤、亩↔平方米、英寸↔厘米、华氏度↔摄氏度的独特说明。其他组合返回 None。"""
        key = (c, a, b)

        def pack(paragraph, headers, rows, name, steps, faq):
            return {"html": guide_card("使用场景和常用数值", paragraph, headers, rows), "name": name, "steps": steps, "faq": faq}

        if key == ("zhongliang", "jin", "kg"):
            para = (
                f"菜市场、菜谱和口语里的体重用的是市斤，食品包装和体检报告用的是公斤（千克）。"
                f"市斤和千克是固定的二比一：1 斤 = {self.fconv(c, 'jin', 'kg', 1)} 千克，把斤数除以 2 就是公斤。"
                f"公斤和千克是同一个单位，符号都是 kg。"
            )
            rows = [
                ["一斤菜", "1 斤", f"{self.fconv(c, 'jin', 'kg', 1)} 千克"],
                ["两斤", "2 斤", f"{self.fconv(c, 'jin', 'kg', 2)} 千克"],
                ["一袋米（常见 10 斤装）", "10 斤", f"{self.fconv(c, 'jin', 'kg', 10)} 千克"],
                ["口语里的一百斤", "100 斤", f"{self.fconv(c, 'jin', 'kg', 100)} 千克"],
                ["体重一百二十斤", "120 斤", f"{self.fconv(c, 'jin', 'kg', 120)} 千克"],
            ]
            steps = [
                f"先确认用的是市斤：1 斤 = {self.fconv(c, 'jin', 'kg', 1)} 千克（公斤），1 千克 = {self.fconv(c, 'kg', 'jin', 1)} 斤。公斤和千克没有区别。",
                f"斤换千克，把斤数除以 2。例如 100 斤 = {self.fconv(c, 'jin', 'kg', 100)} 千克。",
                f"千克换回斤，把千克数乘以 2。例如 60 千克 = {self.fconv(c, 'kg', 'jin', 60)} 斤。",
            ]
            faq = [
                ("斤和公斤怎么换算?", f"1 斤等于 {self.fconv(c, 'jin', 'kg', 1)} 公斤，1 公斤等于 {self.fconv(c, 'kg', 'jin', 1)} 斤。口算时把斤数除以 2 就是公斤。"),
                ("100斤等于多少公斤?", f"100 斤等于 {self.fconv(c, 'jin', 'kg', 100)} 公斤。"),
                ("120斤是多少公斤?", f"120 斤等于 {self.fconv(c, 'jin', 'kg', 120)} 公斤，也就是体检报告上的 {self.fconv(c, 'jin', 'kg', 120)} 千克。"),
            ]
            return pack(para, ["场景", "斤", "千克（公斤）"], rows, "怎么把斤换算成千克", steps, faq)
        if key == ("zhongliang", "kg", "jin"):
            para = (
                f"体检单、营养成分表和进口包装写的是千克或公斤，日常生活仍常说斤。"
                f"1 千克正好等于 {self.fconv(c, 'kg', 'jin', 1)} 斤，看到公斤数乘以 2 就是斤。"
                f"例如体重 60 公斤，口头就是 {self.fconv(c, 'kg', 'jin', 60)} 斤。"
            )
            rows = [
                ["一公斤水果", "1 千克", f"{self.fconv(c, 'kg', 'jin', 1)} 斤"],
                ["五公斤米", "5 千克", f"{self.fconv(c, 'kg', 'jin', 5)} 斤"],
                ["体重 50 公斤", "50 千克", f"{self.fconv(c, 'kg', 'jin', 50)} 斤"],
                ["体重 60 公斤", "60 千克", f"{self.fconv(c, 'kg', 'jin', 60)} 斤"],
                ["体重 70 公斤", "70 千克", f"{self.fconv(c, 'kg', 'jin', 70)} 斤"],
            ]
            steps = [
                f"记住 1 千克（公斤）= {self.fconv(c, 'kg', 'jin', 1)} 斤，1 斤 = {self.fconv(c, 'jin', 'kg', 1)} 千克。",
                f"千克换斤，把千克数乘以 2。例如 50 千克 = {self.fconv(c, 'kg', 'jin', 50)} 斤。",
                f"斤换回千克，把斤数除以 2。例如 120 斤 = {self.fconv(c, 'jin', 'kg', 120)} 千克。",
            ]
            faq = [
                ("1公斤等于多少斤?", f"1 公斤等于 {self.fconv(c, 'kg', 'jin', 1)} 斤。公斤就是千克。"),
                ("50公斤是多少斤?", f"50 公斤等于 {self.fconv(c, 'kg', 'jin', 50)} 斤。"),
                ("公斤和千克有什么区别?", f"没有区别。1 公斤 = 1 千克 = {self.fconv(c, 'kg', 'jin', 1)} 斤，符号都是 kg。"),
            ]
            return pack(para, ["场景", "千克（公斤）", "斤"], rows, "怎么把千克换算成斤", steps, faq)
        if key == ("mianji", "mu", "m2"):
            one, fen = self.fconv(c, "mu", "m2", 1), self.fconv(c, "mu", "m2", "0.1")
            half, three = self.fconv(c, "mu", "m2", "1.5"), self.fconv(c, "mu", "m2", 3)
            para = (
                f"农田、宅基地和口头说地常用亩，房产证、规划和工程图用平方米。"
                f"市亩的定义是 1 亩 = 2000/3 平方米，本页按 10 位有效数字写成 {one} 平方米，口头通常记成约 666.67 平方米。"
                f"有两个正好凑整的数：1.5 亩 = {half} 平方米，3 亩 = {three} 平方米。"
            )
            rows = [
                ["一分地（0.1 亩）", "0.1 亩", f"{fen} 平方米"],
                ["一亩", "1 亩", f"{one} 平方米"],
                ["一亩半", "1.5 亩", f"{half} 平方米"],
                ["三亩", "3 亩", f"{three} 平方米"],
            ]
            steps = [
                f"使用市亩：1 亩 = 2000/3 平方米，也就是 {one} 平方米（约 666.67 平方米）。",
                f"亩换平方米，用亩数乘以 2000/3。例如 1.5 亩 = {half} 平方米，3 亩 = {three} 平方米。",
                f"平方米换回亩，用平方米数乘以 0.0015。例如 100 平方米 = {self.fconv(c, 'm2', 'mu', 100)} 亩。",
            ]
            faq = [
                ("一亩大约是多少平方米?", f"1 亩等于 {one} 平方米，精确值是 2000/3 平方米，通常约记为 666.67 平方米。"),
                ("一分地是多少平方米?", f"一分是 0.1 亩，等于 {fen} 平方米（约 66.67 平方米）。"),
                ("1.5亩是多少平方米?", f"1.5 亩正好等于 {half} 平方米。"),
            ]
            return pack(para, ["场景", "亩", "平方米"], rows, "怎么把亩换算成平方米", steps, faq)
        if key == ("mianji", "m2", "mu"):
            one_m = self.fconv(c, "m2", "mu", 1)
            h100, h200 = self.fconv(c, "m2", "mu", 100), self.fconv(c, "m2", "mu", 200)
            h500, h1000 = self.fconv(c, "m2", "mu", 500), self.fconv(c, "m2", "mu", 1000)
            mu_m = self.fconv(c, "mu", "m2", 1)
            para = (
                f"买房、装修和工程量清单一律用平方米。换成农村习惯的亩时，把平方米数乘以 0.0015，"
                f"因为 1 平方米正好是 {one_m} 亩。因此 100 平方米 = {h100} 亩，1000 平方米 = {h1000} 亩，都不用四舍五入。"
            )
            rows = [
                ["100 平方米的房间", "100 平方米", f"{h100} 亩"],
                ["200 平方米", "200 平方米", f"{h200} 亩"],
                ["500 平方米", "500 平方米", f"{h500} 亩"],
                ["1000 平方米", "1000 平方米", f"{h1000} 亩"],
                ["一亩对应的面积", f"{mu_m} 平方米", "1 亩"],
            ]
            steps = [
                f"按市亩定义，1 平方米 = {one_m} 亩，1 亩 = {mu_m} 平方米。",
                f"平方米换亩，把平方米数乘以 0.0015。例如 100 平方米 = {h100} 亩，1000 平方米 = {h1000} 亩。",
                f"亩换回平方米，把亩数乘以 2000/3。例如 1 亩 = {mu_m} 平方米。",
            ]
            faq = [
                ("100平方米是多少亩?", f"100 平方米等于 {h100} 亩。"),
                ("1000平方米等于几亩?", f"1000 平方米等于 {h1000} 亩。"),
                ("平方米换亩怎么口算?", f"把平方米数乘以 0.0015。1 平方米是 {one_m} 亩，100 平方米是 {h100} 亩。"),
            ]
            return pack(para, ["场景", "平方米", "亩"], rows, "怎么把平方米换算成亩", steps, faq)
        if key == ("changdu", "inch", "cm"):
            para = (
                f"显示器、手机屏幕、服装尺码以及螺丝、管件常用英寸，国内日常长度用厘米。"
                f"这里用的是国际英寸，1 英寸正好等于 {self.fconv(c, 'inch', 'cm', 1)} 厘米，把英寸数乘以 2.54 就是厘米。"
                f"屏幕上标的英寸是对角线，不是长或宽。"
            )
            rows = [
                ["1 英寸（定义）", "1 英寸", f"{self.fconv(c, 'inch', 'cm', 1)} 厘米"],
                ["6 英寸对角线", "6 英寸", f"{self.fconv(c, 'inch', 'cm', 6)} 厘米"],
                ["24 英寸显示器", "24 英寸", f"{self.fconv(c, 'inch', 'cm', 24)} 厘米"],
                ["27 英寸显示器", "27 英寸", f"{self.fconv(c, 'inch', 'cm', 27)} 厘米"],
                ["32 英寸显示器", "32 英寸", f"{self.fconv(c, 'inch', 'cm', 32)} 厘米"],
            ]
            steps = [
                f"使用国际英寸：1 英寸 = {self.fconv(c, 'inch', 'cm', 1)} 厘米。",
                f"英寸换厘米，把英寸数乘以 2.54。例如 10 英寸 = {self.fconv(c, 'inch', 'cm', 10)} 厘米，27 英寸 = {self.fconv(c, 'inch', 'cm', 27)} 厘米。屏幕尺寸按对角线算。",
                f"厘米换回英寸，把厘米数除以 2.54。例如 100 厘米 = {self.fconv(c, 'cm', 'inch', 100)} 英寸。",
            ]
            faq = [
                ("英寸换厘米的公式是什么?", f"厘米 = 英寸 × 2.54。例如 10 英寸 = {self.fconv(c, 'inch', 'cm', 10)} 厘米。"),
                ("27英寸是多少厘米?", f"27 英寸等于 {self.fconv(c, 'inch', 'cm', 27)} 厘米。显示器和电视的英寸数指对角线。"),
                ("24英寸等于多少厘米?", f"24 英寸等于 {self.fconv(c, 'inch', 'cm', 24)} 厘米。"),
            ]
            return pack(para, ["场景", "英寸", "厘米"], rows, "怎么把英寸换算成厘米", steps, faq)
        if key == ("changdu", "cm", "inch"):
            para = (
                f"身高、家具和国内图纸用厘米，对照英美尺码、屏幕和管径时要换成英寸。"
                f"1 厘米 = {self.fconv(c, 'cm', 'inch', 1)} 英寸，也就是把厘米数除以 2.54。"
                f"100 厘米 = {self.fconv(c, 'cm', 'inch', 100)} 英寸。"
            )
            rows = [
                ["1 厘米", "1 厘米", f"{self.fconv(c, 'cm', 'inch', 1)} 英寸"],
                ["10 厘米", "10 厘米", f"{self.fconv(c, 'cm', 'inch', 10)} 英寸"],
                ["30 厘米（一把直尺）", "30 厘米", f"{self.fconv(c, 'cm', 'inch', 30)} 英寸"],
                ["100 厘米", "100 厘米", f"{self.fconv(c, 'cm', 'inch', 100)} 英寸"],
                ["身高 170 厘米", "170 厘米", f"{self.fconv(c, 'cm', 'inch', 170)} 英寸"],
            ]
            steps = [
                f"1 厘米 = {self.fconv(c, 'cm', 'inch', 1)} 英寸，因为 1 英寸 = {self.fconv(c, 'inch', 'cm', 1)} 厘米。",
                f"厘米换英寸，把厘米数除以 2.54。例如 10 厘米 = {self.fconv(c, 'cm', 'inch', 10)} 英寸，100 厘米 = {self.fconv(c, 'cm', 'inch', 100)} 英寸。",
                f"英寸换回厘米，把英寸数乘以 2.54。例如 1 英寸 = {self.fconv(c, 'inch', 'cm', 1)} 厘米。",
            ]
            faq = [
                ("厘米换英寸怎么算?", f"英寸 = 厘米 ÷ 2.54。例如 10 厘米 = {self.fconv(c, 'cm', 'inch', 10)} 英寸。"),
                ("100厘米是多少英寸?", f"100 厘米等于 {self.fconv(c, 'cm', 'inch', 100)} 英寸。"),
                ("170厘米是多少英寸?", f"170 厘米等于 {self.fconv(c, 'cm', 'inch', 170)} 英寸。"),
            ]
            return pack(para, ["场景", "厘米", "英寸"], rows, "怎么把厘米换算成英寸", steps, faq)
        if key == ("wendu", "f", "c"):
            f2c, c2f = self.formula("wendu", "f", "c"), self.formula("wendu", "c", "f")
            para = (
                f"美国天气预报、一部分烤箱和体温计用华氏度，中国用摄氏度。两者不是倍数关系，公式是：{f2c}。"
                f"先记三个锚点：32 华氏度是冰点 {self.fconv(c, 'f', 'c', 32)} 摄氏度，"
                f"98.6 华氏度是体温 {self.fconv(c, 'f', 'c', '98.6')} 摄氏度，"
                f"212 华氏度是沸点 {self.fconv(c, 'f', 'c', 212)} 摄氏度。"
            )
            rows = [
                ["冰点", "32 华氏度", f"{self.fconv(c, 'f', 'c', 32)} 摄氏度"],
                ["室温", "68 华氏度", f"{self.fconv(c, 'f', 'c', 68)} 摄氏度"],
                ["体温", "98.6 华氏度", f"{self.fconv(c, 'f', 'c', '98.6')} 摄氏度"],
                ["水的沸点", "212 华氏度", f"{self.fconv(c, 'f', 'c', 212)} 摄氏度"],
                ["烤箱 350 华氏度", "350 华氏度", f"{self.fconv(c, 'f', 'c', 350)} 摄氏度"],
            ]
            steps = [
                f"用公式：{f2c}。不能把华氏度直接乘一个固定倍数。",
                f"先减去 32，再乘以 5/9。例如 68 华氏度 = {self.fconv(c, 'f', 'c', 68)} 摄氏度，98.6 华氏度 = {self.fconv(c, 'f', 'c', '98.6')} 摄氏度。",
                f"摄氏度换回华氏度用公式：{c2f}。例如 0 摄氏度 = {self.fconv(c, 'c', 'f', 0)} 华氏度，100 摄氏度 = {self.fconv(c, 'c', 'f', 100)} 华氏度。",
            ]
            faq = [
                ("华氏度怎么换算成摄氏度?", f"用公式：{f2c}。例如 68 华氏度等于 {self.fconv(c, 'f', 'c', 68)} 摄氏度。"),
                ("98.6华氏度是多少摄氏度?", f"98.6 华氏度等于 {self.fconv(c, 'f', 'c', '98.6')} 摄氏度，这是常用的人体体温对照。"),
                ("0华氏度是多少摄氏度?", f"0 华氏度等于 {self.fconv(c, 'f', 'c', 0)} 摄氏度。"),
            ]
            return pack(para, ["场景", "华氏度", "摄氏度"], rows, "怎么把华氏度换算成摄氏度", steps, faq)
        if key == ("wendu", "c", "f"):
            f2c, c2f = self.formula("wendu", "f", "c"), self.formula("wendu", "c", "f")
            para = (
                f"国内气温、体温和烤箱用摄氏度，看美国预报或进口食谱时换成华氏度。公式是：{c2f}。"
                f"常用对照：0 摄氏度 = {self.fconv(c, 'c', 'f', 0)} 华氏度，"
                f"37 摄氏度 = {self.fconv(c, 'c', 'f', 37)} 华氏度，"
                f"100 摄氏度 = {self.fconv(c, 'c', 'f', 100)} 华氏度，"
                f"烤箱 180 摄氏度 = {self.fconv(c, 'c', 'f', 180)} 华氏度。"
            )
            rows = [
                ["冰点", "0 摄氏度", f"{self.fconv(c, 'c', 'f', 0)} 华氏度"],
                ["室温", "20 摄氏度", f"{self.fconv(c, 'c', 'f', 20)} 华氏度"],
                ["体温", "37 摄氏度", f"{self.fconv(c, 'c', 'f', 37)} 华氏度"],
                ["水的沸点", "100 摄氏度", f"{self.fconv(c, 'c', 'f', 100)} 华氏度"],
                ["烤箱 180 摄氏度", "180 摄氏度", f"{self.fconv(c, 'c', 'f', 180)} 华氏度"],
            ]
            steps = [
                f"用公式：{c2f}。",
                f"先乘以 9/5，再加上 32。例如 20 摄氏度 = {self.fconv(c, 'c', 'f', 20)} 华氏度，37 摄氏度 = {self.fconv(c, 'c', 'f', 37)} 华氏度。",
                f"华氏度换回摄氏度用公式：{f2c}。例如 32 华氏度 = {self.fconv(c, 'f', 'c', 32)} 摄氏度，212 华氏度 = {self.fconv(c, 'f', 'c', 212)} 摄氏度。",
            ]
            faq = [
                ("摄氏度怎么换算成华氏度?", f"用公式：{c2f}。例如 20 摄氏度等于 {self.fconv(c, 'c', 'f', 20)} 华氏度。"),
                ("37摄氏度是多少华氏度?", f"37 摄氏度等于 {self.fconv(c, 'c', 'f', 37)} 华氏度，是人体体温的常用对照。"),
                ("100摄氏度是多少华氏度?", f"100 摄氏度等于 {self.fconv(c, 'c', 'f', 100)} 华氏度，也就是水在标准大气压下的沸点。"),
            ]
            return pack(para, ["场景", "摄氏度", "华氏度"], rows, "怎么把摄氏度换算成华氏度", steps, faq)
        return None

    # ----- 页面 -----
    def pair_page(self, c, a, b):
        na, nb = self.name(c, a), self.name(c, b)
        one, back = self.conv(c, a, b, 1), self.conv(c, b, a, 1)
        cat = CATEGORIES[c]
        related = "".join(f'<a href="{self.url(c, x, y)}">{self.name(c, x)}换{self.name(c, y)}</a>'
                          for x, y in self.pairs[c] if (x == a or y == b) and (x, y) != (a, b))
        note = ""
        if c == "shuju":
            note = "<p>本站按计算机常用的二进制计算(1 KB = 1024 字节)。硬盘、U 盘厂商标称容量按十进制计算(1 GB = 1000 MB),所以电脑里显示的容量会比标称值小一些。</p>"
        if any(self.unit[(c, u)][2].startswith("市") for u in (a, b)):
            note += "<p>市制单位为中国传统计量单位:1 公里 = 2 里,1 米 = 3 尺,1 尺 = 10 寸,1 千克 = 2 斤,1 斤 = 10 两,1 公顷 = 15 亩。</p>"
        extra = self.key_content(c, a, b)
        faqs = self.base_faq(c, a, b)
        guide_html, howto_html, howto = "", "", None
        if extra:
            faqs = faqs + extra["faq"]
            guide_html = extra["html"]
            howto = {"name": extra["name"], "steps": extra["steps"]}
            howto_html = howto_card(extra["name"], extra["steps"])
        h1 = f"{na}和{nb}换算 - 1{na}等于多少{nb}"
        body = f"""<div class="card"><h1>{esc(na)}和{esc(nb)}换算 - 1{esc(na)}等于多少{esc(nb)}</h1>
<div class="big">1 {esc(na)} = {fmt(one)} {esc(nb)}</div>
<p class="muted">1 {esc(nb)} = {fmt(back)} {esc(na)} · 公式:{esc(self.formula(c, a, b))}</p></div>
{guide_html}{self.converter(c, a, b)}{self.ad()}
<div class="card"><h2>{esc(na)}换{esc(nb)}对照表</h2>{self.table(c, a, b, self.values_for(c, a, b), link=True)}</div>
<div class="card"><h2>{esc(nb)}换{esc(na)}对照表</h2>{self.table(c, b, a, self.values_for(c, b, a), link=True)}</div>
{howto_html}<div class="card"><h2>常见问题</h2>{faq_html(faqs)}{note}</div>
<div class="card"><h2>其他{cat["name"]}换算</h2><div class="links">{related}</div><p><a href="/{c}/">{cat["name"]}单位换算器 »</a></p></div>"""
        crumbs = [
            {"name": self.cfg["site_name"], "url": "/"},
            {"name": cat["name"], "url": f"/{c}/"},
            {"name": h1, "url": self.url(c, a, b)},
        ]
        self.write(self.url(c, a, b), f"1{na}等于多少{nb} - {na}和{nb}换算({na}换{nb})",
                   f"1{na}={fmt(one)}{nb},1{nb}={fmt(back)}{na}。在线{na}{nb}换算器,附换算公式和对照表。", body,
                   crumbs=crumbs, faq=faqs, howto=howto)

    def value_page(self, c, a, b, v, vals):
        na, nb = self.name(c, a), self.name(c, b)
        cat = CATEGORIES[c]
        r = self.conv(c, a, b, v)
        extra = ""
        if (c, b) == ("changdu", "foot"):  # 身高常用"几英尺几英寸"表示
            inches = round(float(self.conv(c, a, "inch", v)))
            extra = f"<p>换算成英制身高写法约为 <b>{inches // 12} 英尺 {inches % 12} 英寸</b>(即 {inches // 12}'{inches % 12}\")。</p>"
        calc = (f"{fmt(v)} × {fmt(self.conv(c, a, b, 1))} = {fmt(r)}" if c != "wendu" else f"{self.formula(c, a, b)},代入 {fmt(v)} 得 {fmt(r)}")
        h1 = f"{fmt(v)}{na}等于多少{nb}?"
        body = f"""<div class="card"><h1>{fmt(v)}{esc(na)}等于多少{esc(nb)}?</h1>
<div class="big">{fmt(v)} {esc(na)} = {fmt(r)} {esc(nb)}</div>
<p class="muted">计算方法:{esc(calc)} · <a href="{self.url(c, a, b)}">{esc(na)}{esc(nb)}换算器 »</a></p>{extra}</div>{self.ad()}
{self.converter(c, a, b, v)}
<div class="card"><h2>其他数值</h2>{self.table(c, a, b, vals, link=True)}</div>"""
        crumbs = [
            {"name": self.cfg["site_name"], "url": "/"},
            {"name": cat["name"], "url": f"/{c}/"},
            {"name": f"{na}{nb}换算器", "url": self.url(c, a, b)},
            {"name": h1, "url": self.url(c, a, b, v)},
        ]
        self.write(self.url(c, a, b, v), f"{fmt(v)}{na}等于多少{nb} - {fmt(v)}{na}是多少{nb}",
                   f"{fmt(v)}{na}等于{fmt(r)}{nb}。计算方法:{calc}。", body, crumbs=crumbs)

    def category_page(self, c):
        cat = CATEGORIES[c]
        units = cat["units"]
        if c == "wendu":
            js_units = "null"
            defs = "<p>摄氏度(℃)、华氏度(℉)、开尔文(K)之间不是简单的倍数关系:℉ = ℃ × 9/5 + 32,K = ℃ + 273.15。</p>"
        else:
            js_units = json.dumps([[u[0], float(F(u[3]))] for u in units])
            defs = "<table><tr><th>单位</th><th>等于多少" + esc(cat["base"]) + "</th></tr>" + "".join(
                f"<tr><td>{esc(self.full(c, u[0]))}</td><td>{fmt(u[3])} {esc(cat['base'])}</td></tr>" for u in units) + "</table>"
        inputs = "".join(f'<label>{esc(self.full(c, u[0]))}<input data-u="{u[0]}" type="number" inputmode="decimal"></label>' for u in units)
        pairs = "".join(f'<a href="{self.url(c, a, b)}">{self.name(c, a)}换{self.name(c, b)}</a>' for a, b in self.pairs[c])
        js = """<script>(function(){var U=__U__,ins=[].slice.call(document.querySelectorAll('[data-u]'));
function toC(u,v){return u=='c'?v:u=='f'?(v-32)*5/9:v-273.15}function fromC(u,c){return u=='c'?c:u=='f'?c*9/5+32:c+273.15}
var f={};if(U)U.forEach(function(p){f[p[0]]=p[1]});
ins.forEach(function(el){el.oninput=function(){var v=+el.value,u=el.dataset.u;if(el.value===''){return}
ins.forEach(function(o){if(o===el)return;var r=U?v*f[u]/f[o.dataset.u]:fromC(o.dataset.u,toC(u,v));o.value=+r.toPrecision(10)})}});
ins[0].value=1;ins[0].oninput();})();</script>""".replace("__U__", js_units)
        body = f"""<div class="card"><h1>{cat["name"]}单位换算器</h1><p class="muted">在任意一个框里输入数值,其他单位自动换算。</p>
<div class="form">{inputs}</div>{js}</div>{self.ad()}
<div class="card"><h2>{cat["name"]}单位对照</h2>{defs}</div>
<div class="card"><h2>全部{cat["name"]}换算</h2><div class="links">{pairs}</div></div>"""
        names = "、".join(u[1] for u in units[:6])
        h1 = f"{cat['name']}单位换算器"
        crumbs = [{"name": self.cfg["site_name"], "url": "/"}, {"name": h1, "url": f"/{c}/"}]
        self.write(f"/{c}/", f"{cat['name']}单位换算 - {cat['name']}换算器({names}等)",
                   f"在线{cat['name']}单位换算器,支持{names}等{len(units)}种单位互相换算,附单位对照表。", body, crumbs=crumbs)

    def daxie_page(self):
        body = f"""<div class="card"><h1>数字转人民币大写</h1><p class="muted">输入金额,自动转换为财务票据上使用的中文大写金额。</p>
<div class="form"><label>金额(元,最多两位小数)<input id="m" inputmode="decimal" value="1234.56"></label></div>
<div class="out" id="r"></div></div>
<script>{RMB_JS}(function(){{var m=document.getElementById('m'),r=document.getElementById('r');
m.oninput=function(){{var v=rmbUpper(m.value);r.textContent=v||'请输入正确的金额(最多两位小数)'}};m.oninput();}})();</script>{self.ad()}
<div class="card"><h2>大写数字对照</h2><table><tr><th>小写</th><th>大写</th></tr>
{"".join(f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in zip("0123456789", "零壹贰叁肆伍陆柒捌玖"))}
<tr><td>十 / 百 / 千</td><td>拾 / 佰 / 仟</td></tr><tr><td>万 / 亿</td><td>万 / 亿</td></tr></table></div>
<div class="card"><h2>大写金额书写规则</h2>
<p>1. 金额到"元"或"角"为止的,在最后写"整"字,如 10.50 写作"壹拾元伍角整";金额到"分"的,不写"整",如 1234.56 写作"壹仟贰佰叁拾肆元伍角陆分"。</p>
<p>2. 中间有一个或连续几个"0"时,大写只写一个"零",如 1005 写作"壹仟零伍元整",100200.03 写作"壹拾万零贰佰元零叁分"。</p>
<p>3. 万位、亿位后面紧跟的是"仟"位时不写"零",如 105000 写作"壹拾万伍仟元整"。</p>
<p>4. 以"壹拾"开头的金额,"壹"字不能省略,如 10 元写作"壹拾元整"。</p>
<p class="muted">具体填写要求以所在单位和银行的规定为准。</p></div>"""
        h1 = "数字转人民币大写"
        crumbs = [{"name": self.cfg["site_name"], "url": "/"}, {"name": h1, "url": "/daxie/"}]
        self.write("/daxie/", "数字转大写 - 人民币大写金额转换器(在线)", "在线数字转人民币大写金额,输入数字自动生成财务大写,附大写数字对照表和书写规则。", body, crumbs=crumbs)

    def bmi_page(self):
        body = """<div class="card"><h1>BMI 计算器(身体质量指数)</h1><div class="form">
<label>身高(厘米)<input id="h" type="number" inputmode="decimal" value="170"></label>
<label>体重(公斤)<input id="w" type="number" inputmode="decimal" value="65"></label></div><div class="out" id="r"></div></div>
<script>(function(){var h=document.getElementById('h'),w=document.getElementById('w'),r=document.getElementById('r');
function run(){var m=+h.value/100,k=+w.value;if(!(m>0&&k>0)){r.textContent='';return}var b=k/m/m,t=b<18.5?'偏瘦':b<24?'正常':b<28?'超重':'肥胖';
r.textContent='BMI = '+b.toFixed(1)+',属于'+t+'(正常体重范围约 '+(18.5*m*m).toFixed(1)+'～'+(23.9*m*m).toFixed(1)+' 公斤)'}
h.oninput=w.oninput=run;run();})();</script>__AD__
<div class="card"><h2>中国成人 BMI 标准</h2><table><tr><th>分类</th><th>BMI</th></tr>
<tr><td>体重过低</td><td>&lt; 18.5</td></tr><tr><td>正常</td><td>18.5 ～ 23.9</td></tr><tr><td>超重</td><td>24.0 ～ 27.9</td></tr><tr><td>肥胖</td><td>≥ 28.0</td></tr></table>
<p>BMI = 体重(公斤)÷ 身高(米)的平方。以上为《成人体重判定》(WS/T 428-2013)中国成人标准,不适用于儿童、孕妇和肌肉特别发达的人。</p>
<p class="muted">BMI 只是粗略参考,不能代替医学诊断。</p></div>""".replace("__AD__", self.ad())
        h1 = "BMI 计算器(身体质量指数)"
        crumbs = [{"name": self.cfg["site_name"], "url": "/"}, {"name": h1, "url": "/bmi/"}]
        self.write("/bmi/", "BMI 计算器 - 身体质量指数在线计算(中国标准)", "在线 BMI 计算器,输入身高体重计算身体质量指数,按中国成人标准判断偏瘦、正常、超重或肥胖。", body, crumbs=crumbs)

    def home(self):
        cats = "".join(f'<a href="/{c}/">{cat["name"]}换算</a>' for c, cat in CATEGORIES.items())
        popular = "".join(f'<a href="{self.url(c, a, b)}">{self.name(c, a)}换{self.name(c, b)}</a>'
                          for c, a, b, _ in COMMON)
        body = f"""<div class="card"><h1>单位换算大全</h1><p class="muted">长度、重量、面积、体积、温度、速度、数据存储、压强、能量、功率 10 大类 {len(self.unit)} 种单位在线换算,含斤、两、亩、尺等市制单位。</p>
<div class="grid">{cats}<a href="/daxie/">金额大写</a><a href="/bmi/">BMI 计算</a></div></div>{self.ad()}
<div class="card"><h2>常用换算</h2><div class="links">{popular}</div></div>"""
        self.write("/", f"{self.cfg['site_name']} - 在线单位换算器(长度重量面积温度等)",
                   "免费在线单位换算:长度、重量、面积、体积、温度、速度、数据存储、压强、能量、功率换算,支持斤两亩尺等市制单位,另有人民币大写和 BMI 计算。", body,
                   home=True)

    def build(self):
        if OUT.exists():
            shutil.rmtree(OUT)
        OUT.mkdir()
        self.home()
        for c in CATEGORIES:
            self.category_page(c)
            for a, b in self.pairs[c]:
                self.pair_page(c, a, b)
        for c, a, b, vals in COMMON:
            assert (a, b) in self.pairs[c], (c, a, b)
            for v in vals:
                self.value_page(c, a, b, v, vals)
        self.daxie_page()
        self.bmi_page()
        base = self.cfg["base_url"].rstrip("/")
        # lastmod 取 config.json。页面文案或 head 里的 SEO 信息有变时,把那个日期一并改掉。
        lastmod = self.cfg["lastmod"]
        sm = "".join(f"<url><loc>{esc(base + u)}</loc><lastmod>{esc(lastmod)}</lastmod></url>" for u in self.urls)
        (OUT / "sitemap.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{sm}</urlset>', encoding="utf-8")
        (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n", encoding="utf-8")
        if self.cfg.get("adsense_client"):
            (OUT / "ads.txt").write_text(f"google.com, {self.cfg['adsense_client'].replace('ca-', '')}, DIRECT, f08c47fec0942fa0\n", encoding="utf-8")
        print(f"生成 {len(self.urls)} 个页面")


if __name__ == "__main__":
    Site().build()
