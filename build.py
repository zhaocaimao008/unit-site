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

    def write(self, path, title, desc, body):
        cfg = self.cfg
        ads = ""
        if cfg.get("adsense_client"):
            ads = (f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client='
                   f'{esc(cfg["adsense_client"])}" crossorigin="anonymous"></script>')
        nav = "".join(f'<a href="/{c}/">{cat["name"]}</a>' for c, cat in CATEGORIES.items())
        prefix = urllib.parse.urlparse(cfg["base_url"]).path.rstrip("/")
        page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{esc(cfg["base_url"].rstrip("/") + path)}">{ads}<style>{CSS}</style></head><body>
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
        body = f"""<div class="card"><h1>{esc(na)}和{esc(nb)}换算 - 1{esc(na)}等于多少{esc(nb)}</h1>
<div class="big">1 {esc(na)} = {fmt(one)} {esc(nb)}</div>
<p class="muted">1 {esc(nb)} = {fmt(back)} {esc(na)} · 公式:{esc(self.formula(c, a, b))}</p></div>
{self.converter(c, a, b)}{self.ad()}
<div class="card"><h2>{esc(na)}换{esc(nb)}对照表</h2>{self.table(c, a, b, self.values_for(c, a, b), link=True)}</div>
<div class="card"><h2>{esc(nb)}换{esc(na)}对照表</h2>{self.table(c, b, a, self.values_for(c, b, a), link=True)}</div>
<div class="card"><h2>常见问题</h2><p><b>1{esc(na)}等于多少{esc(nb)}?</b><br>1 {esc(self.full(c, a))} 等于 {fmt(one)} {esc(self.full(c, b))}。</p>
<p><b>{esc(nb)}怎么换算成{esc(na)}?</b><br>{esc(self.formula(c, b, a))}。例如 10 {esc(nb)} = {fmt(self.conv(c, b, a, 10))} {esc(na)}。</p>{note}</div>
<div class="card"><h2>其他{cat["name"]}换算</h2><div class="links">{related}</div><p><a href="/{c}/">{cat["name"]}单位换算器 »</a></p></div>"""
        self.write(self.url(c, a, b), f"1{na}等于多少{nb} - {na}和{nb}换算({na}换{nb})",
                   f"1{na}={fmt(one)}{nb},1{nb}={fmt(back)}{na}。在线{na}{nb}换算器,附换算公式和对照表。", body)

    def value_page(self, c, a, b, v, vals):
        na, nb = self.name(c, a), self.name(c, b)
        r = self.conv(c, a, b, v)
        extra = ""
        if (c, b) == ("changdu", "foot"):  # 身高常用"几英尺几英寸"表示
            inches = round(float(self.conv(c, a, "inch", v)))
            extra = f"<p>换算成英制身高写法约为 <b>{inches // 12} 英尺 {inches % 12} 英寸</b>(即 {inches // 12}'{inches % 12}\")。</p>"
        calc = (f"{fmt(v)} × {fmt(self.conv(c, a, b, 1))} = {fmt(r)}" if c != "wendu" else f"{self.formula(c, a, b)},代入 {fmt(v)} 得 {fmt(r)}")
        body = f"""<div class="card"><h1>{fmt(v)}{esc(na)}等于多少{esc(nb)}?</h1>
<div class="big">{fmt(v)} {esc(na)} = {fmt(r)} {esc(nb)}</div>
<p class="muted">计算方法:{esc(calc)} · <a href="{self.url(c, a, b)}">{esc(na)}{esc(nb)}换算器 »</a></p>{extra}</div>{self.ad()}
{self.converter(c, a, b, v)}
<div class="card"><h2>其他数值</h2>{self.table(c, a, b, vals, link=True)}</div>"""
        self.write(self.url(c, a, b, v), f"{fmt(v)}{na}等于多少{nb} - {fmt(v)}{na}是多少{nb}",
                   f"{fmt(v)}{na}等于{fmt(r)}{nb}。计算方法:{calc}。", body)

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
        self.write(f"/{c}/", f"{cat['name']}单位换算 - {cat['name']}换算器({names}等)",
                   f"在线{cat['name']}单位换算器,支持{names}等{len(units)}种单位互相换算,附单位对照表。", body)

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
        self.write("/daxie/", "数字转大写 - 人民币大写金额转换器(在线)", "在线数字转人民币大写金额,输入数字自动生成财务大写,附大写数字对照表和书写规则。", body)

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
        self.write("/bmi/", "BMI 计算器 - 身体质量指数在线计算(中国标准)", "在线 BMI 计算器,输入身高体重计算身体质量指数,按中国成人标准判断偏瘦、正常、超重或肥胖。", body)

    def home(self):
        cats = "".join(f'<a href="/{c}/">{cat["name"]}换算</a>' for c, cat in CATEGORIES.items())
        popular = "".join(f'<a href="{self.url(c, a, b)}">{self.name(c, a)}换{self.name(c, b)}</a>'
                          for c, a, b, _ in COMMON)
        body = f"""<div class="card"><h1>单位换算大全</h1><p class="muted">长度、重量、面积、体积、温度、速度、数据存储、压强、能量、功率 10 大类 {len(self.unit)} 种单位在线换算,含斤、两、亩、尺等市制单位。</p>
<div class="grid">{cats}<a href="/daxie/">金额大写</a><a href="/bmi/">BMI 计算</a></div></div>{self.ad()}
<div class="card"><h2>常用换算</h2><div class="links">{popular}</div></div>"""
        self.write("/", f"{self.cfg['site_name']} - 在线单位换算器(长度重量面积温度等)",
                   "免费在线单位换算:长度、重量、面积、体积、温度、速度、数据存储、压强、能量、功率换算,支持斤两亩尺等市制单位,另有人民币大写和 BMI 计算。", body)

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
        sm = "".join(f"<url><loc>{esc(base + u)}</loc></url>" for u in self.urls)
        (OUT / "sitemap.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{sm}</urlset>', encoding="utf-8")
        (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n", encoding="utf-8")
        if self.cfg.get("adsense_client"):
            (OUT / "ads.txt").write_text(f"google.com, {self.cfg['adsense_client'].replace('ca-', '')}, DIRECT, f08c47fec0942fa0\n", encoding="utf-8")
        print(f"生成 {len(self.urls)} 个页面")


if __name__ == "__main__":
    Site().build()
