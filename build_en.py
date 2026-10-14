#!/usr/bin/env python3
"""生成英文版单位换算页面到 dist/en/,并给中英文对应页面互相加上 hreflang 和语言切换链接。

需要在 build.py 之后运行(它会修改 build.py 生成的中文页面和 sitemap.xml)。
"""
import html
import json
import re
import urllib.parse
from fractions import Fraction as F

from build import CSS, OUT, ROOT, esc, fmt
from units import CATEGORIES

# 中文类别 -> (英文 slug, 英文名)
CAT_EN = {"changdu": ("length", "Length"), "zhongliang": ("weight", "Weight"), "mianji": ("area", "Area"),
          "tiji": ("volume", "Volume"), "wendu": ("temperature", "Temperature"), "sudu": ("speed", "Speed"),
          "shuju": ("data", "Data Storage"), "yaqiang": ("pressure", "Pressure"), "nengliang": ("energy", "Energy"),
          "gonglv": ("power", "Power")}

# 单位 -> (单数, 复数, 符号, 网址 slug);不在这里的中文单位(如里、丈、两)不出英文页
UNIT_EN = {
    "km": ("kilometer", "kilometers", "km", "kilometers"), "m": ("meter", "meters", "m", "meters"),
    "dm": ("decimeter", "decimeters", "dm", "decimeters"), "cm": ("centimeter", "centimeters", "cm", "centimeters"),
    "mm": ("millimeter", "millimeters", "mm", "millimeters"), "um": ("micrometer", "micrometers", "μm", "micrometers"),
    "nm": ("nanometer", "nanometers", "nm", "nanometers"), "mile": ("mile", "miles", "mi", "miles"),
    "yard": ("yard", "yards", "yd", "yards"), "foot": ("foot", "feet", "ft", "feet"), "inch": ("inch", "inches", "in", "inches"),
    "nmi": ("nautical mile", "nautical miles", "nmi", "nautical-miles"),
    "t": ("metric ton", "metric tons", "t", "metric-tons"), "kg": ("kilogram", "kilograms", "kg", "kilograms"),
    "jin": ("jin (catty)", "jin", "jin", "jin"), "g": ("gram", "grams", "g", "grams"), "mg": ("milligram", "milligrams", "mg", "milligrams"),
    "lb": ("pound", "pounds", "lb", "pounds"), "oz": ("ounce", "ounces", "oz", "ounces"),
    "ozt": ("troy ounce", "troy ounces", "oz t", "troy-ounces"), "ct": ("carat", "carats", "ct", "carats"),
    "st": ("stone", "stone", "st", "stone"), "ston": ("US short ton", "US short tons", "ton", "us-tons"),
    "lton": ("imperial long ton", "imperial long tons", "LT", "long-tons"),
    "km2": ("square kilometer", "square kilometers", "km²", "square-kilometers"), "ha": ("hectare", "hectares", "ha", "hectares"),
    "mu": ("mu (Chinese acre)", "mu", "mu", "mu"), "m2": ("square meter", "square meters", "m²", "square-meters"),
    "cm2": ("square centimeter", "square centimeters", "cm²", "square-centimeters"),
    "mm2": ("square millimeter", "square millimeters", "mm²", "square-millimeters"), "acre": ("acre", "acres", "ac", "acres"),
    "sqmi": ("square mile", "square miles", "mi²", "square-miles"), "sqyd": ("square yard", "square yards", "yd²", "square-yards"),
    "sqft": ("square foot", "square feet", "ft²", "square-feet"), "sqin": ("square inch", "square inches", "in²", "square-inches"),
    "m3": ("cubic meter", "cubic meters", "m³", "cubic-meters"), "l": ("liter", "liters", "L", "liters"),
    "ml": ("milliliter", "milliliters", "mL", "milliliters"), "usgal": ("US gallon", "US gallons", "gal", "gallons"),
    "ukgal": ("imperial gallon", "imperial gallons", "imp gal", "imperial-gallons"),
    "usfloz": ("US fluid ounce", "US fluid ounces", "fl oz", "fluid-ounces"), "ft3": ("cubic foot", "cubic feet", "ft³", "cubic-feet"),
    "bbl": ("barrel of oil", "barrels of oil", "bbl", "barrels"), "cup": ("US cup", "US cups", "cup", "cups"),
    "tbsp": ("tablespoon", "tablespoons", "tbsp", "tablespoons"), "tsp": ("teaspoon", "teaspoons", "tsp", "teaspoons"),
    "pint": ("US pint", "US pints", "pt", "pints"), "quart": ("US quart", "US quarts", "qt", "quarts"),
    "c": ("degree Celsius", "degrees Celsius", "°C", "celsius"), "f": ("degree Fahrenheit", "degrees Fahrenheit", "°F", "fahrenheit"),
    "k": ("kelvin", "kelvins", "K", "kelvin"),
    "kmh": ("kilometer per hour", "kilometers per hour", "km/h", "kmh"), "ms": ("meter per second", "meters per second", "m/s", "meters-per-second"),
    "mph": ("mile per hour", "miles per hour", "mph", "mph"), "knot": ("knot", "knots", "kn", "knots"),
    "bit": ("bit", "bits", "bit", "bits"), "byte": ("byte", "bytes", "B", "bytes"), "kb": ("kilobyte", "kilobytes", "KB", "kb"),
    "mb": ("megabyte", "megabytes", "MB", "mb"), "gb": ("gigabyte", "gigabytes", "GB", "gb"), "tb": ("terabyte", "terabytes", "TB", "tb"),
    "pb": ("petabyte", "petabytes", "PB", "pb"),
    "pa": ("pascal", "pascals", "Pa", "pascals"), "kpa": ("kilopascal", "kilopascals", "kPa", "kpa"), "mpa": ("megapascal", "megapascals", "MPa", "mpa"),
    "bar": ("bar", "bars", "bar", "bar"), "atm": ("atmosphere", "atmospheres", "atm", "atm"), "psi": ("psi", "psi", "psi", "psi"),
    "mmhg": ("millimeter of mercury", "millimeters of mercury", "mmHg", "mmhg"), "kgfcm2": ("kgf/cm²", "kgf/cm²", "kgf/cm²", "kgf-cm2"),
    "j": ("joule", "joules", "J", "joules"), "kj": ("kilojoule", "kilojoules", "kJ", "kilojoules"), "cal": ("calorie", "calories", "cal", "calories"),
    "kcal": ("kilocalorie", "kilocalories", "kcal", "kcal"), "kwh": ("kilowatt-hour", "kilowatt-hours", "kWh", "kwh"),
    "w": ("watt", "watts", "W", "watts"), "kw": ("kilowatt", "kilowatts", "kW", "kilowatts"),
    "hp": ("metric horsepower", "metric horsepower", "PS", "metric-horsepower"), "hpi": ("horsepower", "horsepower", "hp", "horsepower"),
}
# 英文版额外的英美常用单位(精确定义值)
EXTRA = {
    "zhongliang": [("st", F("6.35029318")), ("ston", F("907.18474")), ("lton", F("1016.0469088"))],
    "tiji": [("cup", F("0.2365882365")), ("tbsp", F("0.01478676478125")), ("tsp", F("0.00492892159375")),
             ("pint", F("0.473176473")), ("quart", F("0.946352946"))],
}
STD = [1, 2, 3, 5, 10, 20, 50, 100, 500, 1000]
COMMON = [
    ("changdu", "cm", "inch", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 20, 25, 30, 40, 50, 60, 70, 80, 90, 100]),
    ("changdu", "inch", "cm", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 20, 24, 27, 32, 36, 40, 43, 50, 55, 65, 75]),
    ("changdu", "cm", "foot", list(range(140, 205, 5))), ("changdu", "foot", "m", STD), ("changdu", "m", "foot", STD),
    ("changdu", "mm", "inch", [1, 2, 3, 5, 6, 8, 10, 12, 15, 20, 25, 50, 100]), ("changdu", "inch", "mm", [0.25, 0.5, 0.75, 1, 2, 3, 5]),
    ("changdu", "mile", "km", [1, 2, 3, 5, 10, 13.1, 20, 26.2, 50, 100]), ("changdu", "km", "mile", [1, 3, 5, 10, 15, 21.0975, 42.195, 50, 100]),
    ("zhongliang", "kg", "lb", [1, 2, 3, 5, 10, 20, 25, 30, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100]),
    ("zhongliang", "lb", "kg", [1, 5, 10, 20, 50, 100, 110, 120, 130, 140, 150, 160, 170, 180, 190, 200, 220, 250]),
    ("zhongliang", "g", "oz", [1, 10, 50, 100, 200, 250, 500, 1000]), ("zhongliang", "oz", "g", [1, 2, 4, 8, 12, 16]),
    ("zhongliang", "st", "kg", [8, 9, 10, 11, 12, 13, 14, 15, 16, 18, 20]), ("zhongliang", "kg", "st", [50, 60, 70, 80, 90, 100]),
    ("tiji", "cup", "ml", [0.25, 0.33, 0.5, 0.75, 1, 1.5, 2, 3, 4]), ("tiji", "ml", "cup", [50, 100, 120, 150, 200, 250, 300, 500, 1000]),
    ("tiji", "tbsp", "ml", [1, 2, 3, 4, 5]), ("tiji", "tsp", "ml", [0.5, 1, 2, 3]), ("tiji", "usfloz", "ml", [1, 2, 4, 6, 8, 12, 16, 20, 32]),
    ("tiji", "ml", "usfloz", [100, 250, 330, 355, 500, 750, 1000]), ("tiji", "l", "usgal", STD), ("tiji", "usgal", "l", STD),
    ("wendu", "c", "f", [-40, -20, -10, -5, 0, 5, 10, 15, 18, 20, 21, 22, 23, 25, 27, 30, 32, 35, 37, 38, 40, 100, 160, 180, 200, 220]),
    ("wendu", "f", "c", [-40, 0, 10, 20, 32, 40, 50, 60, 65, 68, 70, 72, 75, 80, 85, 90, 95, 98.6, 100, 212, 325, 350, 375, 400, 425, 450]),
    ("sudu", "mph", "kmh", [10, 20, 25, 30, 40, 50, 55, 60, 65, 70, 75, 80, 100]), ("sudu", "kmh", "mph", [10, 30, 50, 60, 80, 90, 100, 110, 120, 130, 200]),
    ("mianji", "sqft", "m2", [1, 10, 100, 500, 1000, 1500, 2000, 2500, 3000]), ("mianji", "m2", "sqft", [1, 10, 50, 100, 150, 200, 500, 1000]),
    ("mianji", "acre", "ha", STD), ("mianji", "ha", "acre", STD),
    ("nengliang", "kcal", "kj", STD), ("nengliang", "kj", "kcal", STD), ("shuju", "gb", "mb", STD), ("shuju", "mb", "gb", [100, 500, 1000, 1024, 2048]),
]


class En:
    def __init__(self):
        self.cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        self.base = self.cfg["base_url"].rstrip("/")
        self.prefix = urllib.parse.urlparse(self.cfg["base_url"]).path.rstrip("/")
        self.units, self.factor, self.pairs, self.urls = {}, {}, {}, []
        for c, cat in CATEGORIES.items():
            us = [u[0] for u in cat["units"] if u[0] in UNIT_EN]
            for u in cat["units"]:
                self.factor[(c, u[0])] = u[3]
            for key, f in EXTRA.get(c, []):
                us.append(key)
                self.factor[(c, key)] = f
            self.units[c] = us
            ps = []
            for a in us:
                for b in us:
                    if a == b:
                        continue
                    if c != "wendu" and not (F(1, 10**7) <= F(self.factor[(c, a)]) / F(self.factor[(c, b)]) <= 10**7):
                        continue
                    ps.append((a, b))
            self.pairs[c] = ps
        self.common = {(c, a, b): v for c, a, b, v in COMMON}
        self.zh_pairs = {(c, a, b) for c in CATEGORIES for a in [u[0] for u in CATEGORIES[c]["units"]]
                         for b in [u[0] for u in CATEGORIES[c]["units"]] if (OUT / c / f"{a}-{b}" / "index.html").exists()}
        self.alt = {}  # 英文路径 -> 中文路径

    # ----- 工具 -----
    def conv(self, c, a, b, x):
        x = F(str(x))
        if c == "wendu":
            cel = {"c": x, "f": (x - 32) * F(5, 9), "k": x - F("273.15")}[a]
            return {"c": cel, "f": cel * F(9, 5) + 32, "k": cel + F("273.15")}[b]
        return x * F(self.factor[(c, a)]) / F(self.factor[(c, b)])

    def n(self, u, x=None):
        s, p, _, _ = UNIT_EN[u]
        return s if x is not None and F(str(x)) == 1 else p

    def title_name(self, u):
        return UNIT_EN[u][1][0].upper() + UNIT_EN[u][1][1:]

    def sym(self, u):
        return UNIT_EN[u][2]

    def url(self, c, a=None, b=None, v=None):
        p = f"/en/{CAT_EN[c][0]}/"
        if a:
            p += f"{UNIT_EN[a][3]}-to-{UNIT_EN[b][3]}/"
        if v is not None:
            p += f"{fmt(v)}/"
        return p

    def formula(self, c, a, b):
        if c == "wendu":
            return {("c", "f"): "°F = °C × 9/5 + 32", ("f", "c"): "°C = (°F − 32) × 5/9", ("c", "k"): "K = °C + 273.15",
                    ("k", "c"): "°C = K − 273.15", ("f", "k"): "K = (°F − 32) × 5/9 + 273.15", ("k", "f"): "°F = (K − 273.15) × 9/5 + 32"}[(a, b)]
        return f"{self.sym(b)} = {self.sym(a)} × {fmt(self.conv(c, a, b, 1))}"

    # ----- 布局 -----
    def ad(self):
        c = self.cfg.get("adsense_client")
        if not c:
            return ""
        return (f'<div class="ad"><ins class="adsbygoogle" style="display:block" data-ad-client="{esc(c)}" data-ad-format="auto" '
                'data-full-width-responsive="true"></ins><script>(adsbygoogle=window.adsbygoogle||[]).push({});</script></div>')

    def write(self, path, title, desc, body, zh=None):
        ads = ""
        if self.cfg.get("adsense_client"):
            ads = (f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client='
                   f'{esc(self.cfg["adsense_client"])}" crossorigin="anonymous"></script>')
        alt = ""
        if zh:
            self.alt[path] = zh
            alt = (f'<link rel="alternate" hreflang="en" href="{esc(self.base + path)}">'
                   f'<link rel="alternate" hreflang="zh-CN" href="{esc(self.base + zh)}">'
                   f'<link rel="alternate" hreflang="x-default" href="{esc(self.base + path)}">')
        nav = "".join(f'<a href="{self.url(c)}">{name}</a>' for c, (_, name) in CAT_EN.items())
        page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{esc(self.base + path)}">{alt}{ads}<style>{CSS}</style></head><body>
<header><a class="logo" href="/en/">Unit Converter</a><nav>{nav}<a href="/en/bmi/">BMI</a><a href="{zh or '/'}" hreflang="zh-CN">中文</a></nav></header>
<main>{body}</main>
<footer>Conversion factors use exact definitions from the International System of Units (SI) and NIST. Results are rounded to 10 significant digits.</footer>
</body></html>""".replace('href="/', f'href="{self.prefix}/')
        f = OUT / path.strip("/") / "index.html"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(page, encoding="utf-8")
        self.urls.append(path)

    # ----- 组件 -----
    def converter(self, c, a, b, x=1):
        if c == "wendu":
            fwd = {"c": "x", "f": "(x-32)*5/9", "k": "x-273.15"}[a]
            back = {"c": "C", "f": "C*9/5+32", "k": "C+273.15"}[b]
            inv = {"c": "y", "f": "(y-32)*5/9", "k": "y-273.15"}[b]
            inv_b = {"c": "C", "f": "C*9/5+32", "k": "C+273.15"}[a]
            f1, f2 = f"function(x){{var C={fwd};return {back}}}", f"function(y){{var C={inv};return {inv_b}}}"
        else:
            r = float(self.conv(c, a, b, 1))
            f1, f2 = f"function(x){{return x*{r!r}}}", f"function(y){{return y/{r!r}}}"
        return f"""<div class="card"><h2>{self.title_name(a)} to {self.title_name(b)} converter</h2><div class="form">
<label>{esc(self.title_name(a))} ({esc(self.sym(a))})<input id="x" type="number" inputmode="decimal" value="{fmt(x)}"></label>
<label>{esc(self.title_name(b))} ({esc(self.sym(b))})<input id="y" type="number" inputmode="decimal"></label></div>
<script>(function(){{var F={f1},G={f2},x=document.getElementById('x'),y=document.getElementById('y');
function p(v){{return isFinite(v)?+v.toPrecision(10):''}}x.oninput=function(){{y.value=x.value===''?'':p(F(+x.value))}};
y.oninput=function(){{x.value=y.value===''?'':p(G(+y.value))}};x.oninput();}})();</script></div>"""

    def ft_in(self, c, a, v):
        inches = round(float(self.conv(c, a, "inch", v)))
        return f"{inches // 12} ft {inches % 12} in"

    def table(self, c, a, b, values):
        rows = []
        for v in values:
            left = f"{fmt(v)} {esc(self.sym(a))}"
            if (c, a, b) in self.common:
                left = f'<a href="{self.url(c, a, b, v)}">{left}</a>'
            extra = f" ({self.ft_in(c, a, v)})" if (c, b) == ("changdu", "foot") else ""
            rows.append(f"<tr><td>{left}</td><td>{fmt(self.conv(c, a, b, v))} {esc(self.sym(b))}{extra}</td></tr>")
        return f"<table><tr><th>{esc(self.title_name(a))}</th><th>{esc(self.title_name(b))}</th></tr>{''.join(rows)}</table>"

    def values_for(self, c, a, b):
        return self.common.get((c, a, b), [-40, -10, 0, 10, 20, 30, 37, 50, 100] if c == "wendu" else STD)

    # ----- 页面 -----
    def pair_page(self, c, a, b):
        one, back = self.conv(c, a, b, 1), self.conv(c, b, a, 1)
        A, B = self.title_name(a), self.title_name(b)
        related = "".join(f'<a href="{self.url(c, x, y)}">{self.title_name(x)} to {self.title_name(y)}</a>'
                          for x, y in self.pairs[c] if (x == a or y == b) and (x, y) != (a, b))
        note = ""
        if c == "shuju":
            note = "<p>This converter uses binary units (1 KB = 1024 bytes), as operating systems do. Drive makers use decimal units (1 GB = 1000 MB), which is why a drive shows less space than its label.</p>"
        if c == "tiji" and {"cup", "tbsp", "tsp", "pint", "quart", "usfloz", "usgal"} & {a, b}:
            note += "<p>Cups, spoons, pints, quarts, fluid ounces and gallons here are US customary units. Imperial (UK) gallons are larger: 1 imperial gallon = 4.54609 liters.</p>"
        body = f"""<div class="card"><h1>{A} to {B} ({esc(self.sym(a))} to {esc(self.sym(b))})</h1>
<div class="big">1 {esc(self.n(a, 1))} = {fmt(one)} {esc(self.n(b, one))}</div>
<p class="muted">1 {esc(self.n(b, 1))} = {fmt(back)} {esc(self.n(a, back))} · Formula: {esc(self.formula(c, a, b))}</p></div>
{self.converter(c, a, b)}{self.ad()}
<div class="card"><h2>{A} to {B} conversion table</h2>{self.table(c, a, b, self.values_for(c, a, b))}</div>
<div class="card"><h2>{B} to {A} conversion table</h2>{self.table(c, b, a, self.values_for(c, b, a))}</div>
<div class="card"><h2>FAQ</h2><p><b>How many {esc(UNIT_EN[b][1])} are in a {esc(UNIT_EN[a][0])}?</b><br>1 {esc(self.n(a, 1))} equals {fmt(one)} {esc(self.n(b, one))}.</p>
<p><b>How do I convert {esc(UNIT_EN[b][1])} to {esc(UNIT_EN[a][1])}?</b><br>Use {esc(self.formula(c, b, a))}. For example, 10 {esc(self.sym(b))} = {fmt(self.conv(c, b, a, 10))} {esc(self.sym(a))}.</p>{note}</div>
<div class="card"><h2>More {CAT_EN[c][1].lower()} conversions</h2><div class="links">{related}</div><p><a href="{self.url(c)}">{CAT_EN[c][1]} converter »</a></p></div>"""
        zh = f"/{c}/{a}-{b}/" if (c, a, b) in self.zh_pairs else None
        self.write(self.url(c, a, b), f"{A} to {B} Converter ({self.sym(a)} to {self.sym(b)})",
                   f"Convert {UNIT_EN[a][1]} to {UNIT_EN[b][1]}: 1 {self.sym(a)} = {fmt(one)} {self.sym(b)}. Free converter with formula and conversion table.", body, zh)

    def value_page(self, c, a, b, v):
        r = self.conv(c, a, b, v)
        calc = f"{fmt(v)} × {fmt(self.conv(c, a, b, 1))} = {fmt(r)}" if c != "wendu" else f"{self.formula(c, a, b)}, so {fmt(v)} {self.sym(a)} = {fmt(r)} {self.sym(b)}"
        extra = f"<p>That is about <b>{self.ft_in(c, a, v)}</b>.</p>" if (c, b) == ("changdu", "foot") else ""
        body = f"""<div class="card"><h1>{fmt(v)} {esc(self.n(a, v))} to {esc(UNIT_EN[b][1])}</h1>
<div class="big">{fmt(v)} {esc(self.sym(a))} = {fmt(r)} {esc(self.sym(b))}</div>{extra}
<p class="muted">Calculation: {esc(calc)} · <a href="{self.url(c, a, b)}">{self.title_name(a)} to {self.title_name(b)} converter »</a></p></div>{self.ad()}
{self.converter(c, a, b, v)}
<div class="card"><h2>Other values</h2>{self.table(c, a, b, self.common[(c, a, b)])}</div>"""
        self.write(self.url(c, a, b, v), f"{fmt(v)} {self.n(a, v)} to {UNIT_EN[b][1]} ({fmt(v)} {self.sym(a)} = {fmt(r)} {self.sym(b)})",
                   f"{fmt(v)} {self.n(a, v)} equals {fmt(r)} {self.n(b, r)}. Calculation: {calc}.", body)

    def category_page(self, c):
        us = self.units[c]
        name = CAT_EN[c][1]
        js_units = "null" if c == "wendu" else json.dumps([[u, float(F(self.factor[(c, u)]))] for u in us])
        inputs = "".join(f'<label>{esc(self.title_name(u))} ({esc(self.sym(u))})<input data-u="{u}" type="number" inputmode="decimal"></label>' for u in us)
        pairs = "".join(f'<a href="{self.url(c, a, b)}">{self.title_name(a)} to {self.title_name(b)}</a>' for a, b in self.pairs[c])
        js = """<script>(function(){var U=__U__,ins=[].slice.call(document.querySelectorAll('[data-u]'));
function toC(u,v){return u=='c'?v:u=='f'?(v-32)*5/9:v-273.15}function fromC(u,c){return u=='c'?c:u=='f'?c*9/5+32:c+273.15}
var f={};if(U)U.forEach(function(p){f[p[0]]=p[1]});
ins.forEach(function(el){el.oninput=function(){var v=+el.value,u=el.dataset.u;if(el.value===''){return}
ins.forEach(function(o){if(o===el)return;var r=U?v*f[u]/f[o.dataset.u]:fromC(o.dataset.u,toC(u,v));o.value=+r.toPrecision(10)})}});
ins[0].value=1;ins[0].oninput();})();</script>""".replace("__U__", js_units)
        body = f"""<div class="card"><h1>{name} Converter</h1><p class="muted">Type a value in any box and every other unit updates instantly.</p>
<div class="form">{inputs}</div>{js}</div>{self.ad()}
<div class="card"><h2>All {name.lower()} conversions</h2><div class="links">{pairs}</div></div>"""
        names = ", ".join(UNIT_EN[u][1] for u in us[:5])
        self.write(self.url(c), f"{name} Converter – Convert {names} and more",
                   f"Free online {name.lower()} converter for {len(us)} units including {names}.", body, f"/{c}/")

    def bmi_page(self):
        body = """<div class="card"><h1>BMI Calculator</h1><div class="form">
<label>Height (ft)<input id="ft" type="number" inputmode="decimal" value="5"></label>
<label>Height (in)<input id="in" type="number" inputmode="decimal" value="9"></label>
<label>Weight (lb)<input id="lb" type="number" inputmode="decimal" value="160"></label></div>
<p class="muted">Metric: <input id="cm" type="number" inputmode="decimal" placeholder="cm" style="width:90px"> cm <input id="kg" type="number" inputmode="decimal" placeholder="kg" style="width:90px"> kg</p>
<div class="out" id="r"></div></div>
<script>(function(){var $=function(i){return document.getElementById(i)};
function show(m,k){if(!(m>0&&k>0)){$('r').textContent='';return}var b=k/m/m,t=b<18.5?'underweight':b<25?'healthy weight':b<30?'overweight':'obesity';
$('r').textContent='BMI = '+b.toFixed(1)+' ('+t+'). Healthy weight for your height: '+(18.5*m*m*2.20462).toFixed(0)+'–'+(24.9*m*m*2.20462).toFixed(0)+' lb'}
function imp(){var m=((+$('ft').value)*12+(+$('in').value))*0.0254,k=(+$('lb').value)*0.45359237;$('cm').value=m?+(m*100).toFixed(1):'';$('kg').value=k?+k.toFixed(1):'';show(m,k)}
function met(){var m=+$('cm').value/100,k=+$('kg').value;var i=m/0.0254;$('ft').value=Math.floor(i/12);$('in').value=+(i%12).toFixed(1);$('lb').value=+(k/0.45359237).toFixed(1);show(m,k)}
['ft','in','lb'].forEach(function(i){$(i).oninput=imp});['cm','kg'].forEach(function(i){$(i).oninput=met});imp();})();</script>__AD__
<div class="card"><h2>Adult BMI categories (WHO)</h2><table><tr><th>Category</th><th>BMI</th></tr>
<tr><td>Underweight</td><td>&lt; 18.5</td></tr><tr><td>Healthy weight</td><td>18.5 – 24.9</td></tr><tr><td>Overweight</td><td>25.0 – 29.9</td></tr><tr><td>Obesity</td><td>≥ 30.0</td></tr></table>
<p>BMI = weight (kg) ÷ height (m)², or 703 × weight (lb) ÷ height (in)². BMI is a screening measure, not a diagnosis, and does not apply to children, pregnant women or very muscular people.</p></div>""".replace("__AD__", self.ad())
        self.write("/en/bmi/", "BMI Calculator – Body Mass Index in lb/ft or kg/cm", "Free BMI calculator using feet, inches and pounds or metric units, with WHO adult BMI categories.", body, "/bmi/")

    def home(self):
        cats = "".join(f'<a href="{self.url(c)}">{name}</a>' for c, (_, name) in CAT_EN.items())
        popular = "".join(f'<a href="{self.url(c, a, b)}">{self.title_name(a)} to {self.title_name(b)}</a>' for c, a, b, _ in COMMON)
        body = f"""<div class="card"><h1>Unit Converter</h1><p class="muted">Convert length, weight, volume, temperature, area, speed, data, pressure, energy and power — {sum(len(u) for u in self.units.values())} units with exact conversion factors.</p>
<div class="grid">{cats}<a href="/en/bmi/">BMI Calculator</a></div></div>{self.ad()}
<div class="card"><h2>Popular conversions</h2><div class="links">{popular}</div></div>"""
        self.write("/en/", "Unit Converter – Free Online Conversion Calculator", "Free online unit converter: inches to cm, kg to lbs, Celsius to Fahrenheit, cups to ml and more, with exact formulas and tables.", body, "/")

    # ----- 中文页面加上英文对应链接 -----
    def link_chinese(self):
        for en, zh in self.alt.items():
            f = OUT / zh.strip("/") / "index.html"
            s = f.read_text(encoding="utf-8")
            tags = (f'<link rel="alternate" hreflang="zh-CN" href="{esc(self.base + zh)}">'
                    f'<link rel="alternate" hreflang="en" href="{esc(self.base + en)}">')
            s = s.replace("<style>", tags + "<style>", 1)
            s = s.replace("</nav></header>", f'<a href="{self.prefix}{en}" hreflang="en">English</a></nav></header>', 1)
            f.write_text(s, encoding="utf-8")

    def build(self):
        self.home()
        for c in CATEGORIES:
            self.category_page(c)
            for a, b in self.pairs[c]:
                self.pair_page(c, a, b)
        for (c, a, b), vals in self.common.items():
            assert (a, b) in self.pairs[c], (c, a, b)
            for v in vals:
                self.value_page(c, a, b, v)
        self.bmi_page()
        self.link_chinese()
        sm = OUT / "sitemap.xml"
        extra = "".join(f"<url><loc>{esc(self.base + u)}</loc></url>" for u in self.urls)
        sm.write_text(sm.read_text(encoding="utf-8").replace("</urlset>", extra + "</urlset>"), encoding="utf-8")
        print(f"英文页面 {len(self.urls)} 个,其中 {len(self.alt)} 个与中文页面互相关联")


if __name__ == "__main__":
    En().build()
