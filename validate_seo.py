#!/usr/bin/env python3
"""检查 dist/ 的 Open Graph、JSON-LD、hreflang 和 sitemap。在 build.py 与 build_en.py 之后运行。"""
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).parent
OUT = ROOT / "dist"
BASE = "https://saylian.com"
NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
EXPECTED_PAGES = 2168
ZH_CATS = {"changdu", "zhongliang", "mianji", "tiji", "wendu", "sudu", "shuju", "yaqiang", "nengliang", "gonglv"}
EN_CATS = {"length", "weight", "area", "volume", "temperature", "speed", "data", "pressure", "energy", "power"}
KEY = {
    "/zhongliang/jin-kg/", "/zhongliang/kg-jin/",
    "/mianji/mu-m2/", "/mianji/m2-mu/",
    "/changdu/inch-cm/", "/changdu/cm-inch/",
    "/wendu/f-c/", "/wendu/c-f/",
    "/en/weight/jin-to-kilograms/", "/en/weight/kilograms-to-jin/",
    "/en/area/mu-to-square-meters/", "/en/area/square-meters-to-mu/",
    "/en/length/inches-to-centimeters/", "/en/length/centimeters-to-inches/",
    "/en/temperature/fahrenheit-to-celsius/", "/en/temperature/celsius-to-fahrenheit/",
}
GUIDE_H2 = {"zh": "使用场景和常用数值", "en": "Common uses and values"}


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def page_path(index):
    rel = index.parent.relative_to(OUT).as_posix()
    return "/" if rel == "." else f"/{rel}/"


def is_pair(path):
    parts = path.strip("/").split("/")
    if len(parts) == 2 and parts[0] in ZH_CATS and "-" in parts[1]:
        return True
    return len(parts) == 3 and parts[0] == "en" and parts[1] in EN_CATS and "-to-" in parts[2]


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lang = ""
        self.title = []
        self.in_title = False
        self.h1 = []
        self.in_h1 = False
        self.h1_done = False
        self.metas = []
        self.links = []
        self.scripts = []
        self.visible = []
        self.skip = 0
        self.in_ld = False
        self.ld_buf = []

    def handle_starttag(self, tag, attrs):
        d = {k: (v or "") for k, v in attrs}
        if tag == "html":
            self.lang = d.get("lang", "")
        elif tag == "title":
            self.in_title = True
        elif tag == "h1" and not self.h1_done:
            self.in_h1 = True
        elif tag == "meta":
            self.metas.append(d)
        elif tag == "link":
            self.links.append(d)
        if tag in ("script", "style"):
            self.skip += 1
            if tag == "script" and d.get("type") == "application/ld+json":
                self.in_ld = True
                self.ld_buf = []

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        elif tag == "h1" and self.in_h1:
            self.in_h1 = False
            self.h1_done = True
        elif tag in ("script", "style") and self.skip:
            self.skip -= 1
            if tag == "script" and self.in_ld:
                self.scripts.append("".join(self.ld_buf))
                self.in_ld = False

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)
            return
        if self.in_ld:
            self.ld_buf.append(data)
            return
        if self.in_h1:
            self.h1.append(data)
        if not self.skip:
            self.visible.append(data)


def meta(page, name=None, prop=None):
    hits = []
    for m in page.metas:
        if name is not None and m.get("name") == name:
            hits.append(m.get("content", ""))
        if prop is not None and m.get("property") == prop:
            hits.append(m.get("content", ""))
    return hits


def main():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    errors = []

    def err(path, msg):
        errors.append(f"{path}: {msg}")

    pages = {}
    indexes = sorted(OUT.rglob("index.html"))
    if len(indexes) != EXPECTED_PAGES:
        err("(site)", f"页面数 {len(indexes)} ,应为 {EXPECTED_PAGES}(不能增删 URL)")

    for index in indexes:
        path = page_path(index)
        raw = index.read_text(encoding="utf-8")
        if "noindex" in raw.lower():
            err(path, "出现了 noindex")
        parser = Page()
        parser.feed(raw)
        title = norm("".join(parser.title))
        h1 = norm("".join(parser.h1))
        visible = norm("".join(parser.visible))
        desc = meta(parser, name="description")
        canonicals = [l.get("href", "") for l in parser.links if l.get("rel") == "canonical"]
        alternates = {}
        for link in parser.links:
            if link.get("rel") != "alternate" or "hreflang" not in link:
                continue
            lang = link["hreflang"]
            if lang in alternates:
                err(path, f"重复的 hreflang {lang}")
            alternates[lang] = link.get("href", "")
        nodes = []
        for blob in parser.scripts:
            if "<" in blob:
                err(path, "JSON-LD 含未转义的 <")
            try:
                nodes.append(json.loads(blob))
            except json.JSONDecodeError as exc:
                err(path, f"JSON-LD 无法解析: {exc}")
        types = [n.get("@type") for n in nodes if isinstance(n, dict)]
        pages[path] = {
            "lang": parser.lang, "title": title, "h1": h1, "visible": visible,
            "desc": desc,             "canonical": canonicals, "alts": alternates, "nodes": nodes, "types": types,
        }

        if parser.lang == "zh-CN":
            if not path.startswith("/en/"):
                pass
            else:
                err(path, "英文路径却标了 zh-CN")
        elif parser.lang == "en":
            if not path.startswith("/en/"):
                err(path, "英文页不在 /en/ 下")
        else:
            err(path, f"未知 lang {parser.lang!r}")

        if path.startswith("/en/"):
            expect_locale, expect_site = "en_US", "Unit Converter"
        else:
            expect_locale, expect_site = "zh_CN", cfg["site_name"]
        og = {
            "og:title": meta(parser, prop="og:title"),
            "og:description": meta(parser, prop="og:description"),
            "og:url": meta(parser, prop="og:url"),
            "og:type": meta(parser, prop="og:type"),
            "og:site_name": meta(parser, prop="og:site_name"),
            "og:locale": meta(parser, prop="og:locale"),
        }
        for key, vals in og.items():
            if len(vals) != 1:
                err(path, f"{key} 应恰好出现 1 次,实际 {len(vals)}")
        if len(desc) != 1:
            err(path, "meta description 应恰好出现 1 次")
        elif og["og:description"] and og["og:description"][0] != desc[0]:
            err(path, "og:description 与 meta description 不一致")
        if og["og:title"] and og["og:title"][0] != title:
            err(path, "og:title 与 title 不一致")
        if len(canonicals) != 1:
            err(path, "canonical 应恰好出现 1 次")
        else:
            canon = canonicals[0]
            if canon != BASE + path:
                err(path, f"canonical {canon} 不是 {BASE + path}")
            if og["og:url"] and og["og:url"][0] != canon:
                err(path, "og:url 与 canonical 不一致")
        if og["og:type"] and og["og:type"][0] != "website":
            err(path, "og:type 不是 website")
        if og["og:site_name"] and og["og:site_name"][0] != expect_site:
            err(path, f"og:site_name 不是 {expect_site}")
        if og["og:locale"] and og["og:locale"][0] != expect_locale:
            err(path, f"og:locale 不是 {expect_locale}")
        if not title or not desc or not desc[0]:
            err(path, "title 或 description 为空")

        if "x-default" not in alternates:
            err(path, "缺少 hreflang x-default")
        if path.startswith("/en/"):
            if alternates.get("en") != BASE + path:
                err(path, "英文页没有指向自己的 hreflang en")
        else:
            if alternates.get("zh-CN") != BASE + path:
                err(path, "中文页没有指向自己的 hreflang zh-CN")
        if "zh-CN" in alternates:
            if alternates.get("x-default") != alternates["zh-CN"]:
                err(path, "x-default 应指向对应中文页")
        elif alternates.get("x-default") != (canonicals[0] if canonicals else ""):
            err(path, "没有中文版时 x-default 应指向本页")

        home = path in ("/", "/en/")
        if home:
            if types != ["WebSite", "WebApplication"]:
                err(path, f"首页 JSON-LD 类型应为 WebSite + WebApplication,实际 {types}")
        else:
            if "BreadcrumbList" not in types:
                err(path, "内页缺少 BreadcrumbList")
            if "WebSite" in types or "WebApplication" in types:
                err(path, "内页不应再放 WebSite/WebApplication")
        if is_pair(path):
            if "FAQPage" not in types:
                err(path, "对照页缺少 FAQPage")
        elif "FAQPage" in types:
            err(path, "非对照页不应有 FAQPage")
        if path in KEY:
            if "HowTo" not in types:
                err(path, "重点页缺少 HowTo")
            heading = GUIDE_H2["en" if path.startswith("/en/") else "zh"]
            if heading not in visible:
                err(path, f"重点页缺少可见说明「{heading}」")
        elif "HowTo" in types:
            err(path, "非重点页不应有 HowTo")

        for node in nodes:
            if not isinstance(node, dict) or node.get("@context") != "https://schema.org":
                err(path, "JSON-LD 缺少 @context https://schema.org")
                continue
            kind = node.get("@type")
            if kind == "WebSite":
                if not node.get("name") or not node.get("url"):
                    err(path, "WebSite 缺少 name 或 url")
            elif kind == "WebApplication":
                offers = node.get("offers") or {}
                if node.get("applicationCategory") != "UtilitiesApplication":
                    err(path, "WebApplication.applicationCategory 不正确")
                if node.get("operatingSystem") != "All":
                    err(path, "WebApplication.operatingSystem 不正确")
                if offers.get("@type") != "Offer" or offers.get("price") != "0" or offers.get("priceCurrency") != "CNY":
                    err(path, "WebApplication.offers 应为免费(price 0, CNY)")
            elif kind == "BreadcrumbList":
                items = node.get("itemListElement") or []
                if not items:
                    err(path, "BreadcrumbList 为空")
                for i, item in enumerate(items, 1):
                    if item.get("@type") != "ListItem" or item.get("position") != i:
                        err(path, "BreadcrumbList 的 position 不连续")
                    name = item.get("name") or ""
                    if not name or norm(name) not in visible:
                        err(path, f"面包屑「{name}」不在可见文字里")
                    loc = item.get("item") or ""
                    if not loc.startswith(BASE + "/"):
                        err(path, f"面包屑 URL 不是绝对地址: {loc}")
                if items and canonicals and items[-1].get("item") != canonicals[0]:
                    err(path, "面包屑末项不是当前 canonical")
                if items and h1 and norm(items[-1].get("name")) != h1:
                    err(path, f"面包屑末项「{items[-1].get('name')}」与 H1「{h1}」不一致")
            elif kind == "FAQPage":
                entities = node.get("mainEntity") or []
                if len(entities) < 2:
                    err(path, "FAQPage 至少要有两个问答")
                seen = set()
                for qn in entities:
                    question = (qn.get("name") or "").strip()
                    answer = ((qn.get("acceptedAnswer") or {}).get("text") or "").strip()
                    if not question or not answer:
                        err(path, "FAQ 问答有空字段")
                        continue
                    if question in seen:
                        err(path, f"FAQ 问题重复: {question}")
                    seen.add(question)
                    if norm(question) not in visible or norm(answer) not in visible:
                        err(path, f"FAQ 与可见文字不一致: {question}")
            elif kind == "HowTo":
                steps = node.get("step") or []
                name = node.get("name") or ""
                if not name or norm(name) not in visible:
                    err(path, "HowTo 标题不在可见文字里")
                if len(steps) < 2:
                    err(path, "HowTo 步骤太少")
                for i, step in enumerate(steps, 1):
                    text = (step.get("text") or "").strip()
                    if step.get("@type") != "HowToStep" or step.get("position") != i or not text:
                        err(path, "HowTo 步骤结构不完整")
                    elif norm(text) not in visible:
                        err(path, f"HowTo 步骤不在可见文字里: {text[:40]}")
            else:
                err(path, f"未预期的 JSON-LD 类型 {kind}")

    # hreflang 互指:同一组语言版本必须列出同一套 alternate
    for path, info in pages.items():
        for lang, href in info["alts"].items():
            if lang == "x-default":
                continue
            other = href[len(BASE):] if href.startswith(BASE) else ""
            if other not in pages:
                err(path, f"hreflang {lang} 指向不存在的页面 {href}")
                continue
            if pages[other]["alts"] != info["alts"]:
                err(path, f"与 {other} 的 hreflang 不是互相一致")

    sm_path = OUT / "sitemap.xml"
    try:
        root = ET.parse(sm_path).getroot()
    except ET.ParseError as exc:
        err("sitemap.xml", f"XML 无法解析: {exc}")
        root = None
    locs = []
    if root is not None:
        for node in root.findall(f"{NS}url"):
            loc = node.find(f"{NS}loc")
            lastmod = node.find(f"{NS}lastmod")
            loc_text = loc.text if loc is not None else ""
            last_text = lastmod.text if lastmod is not None else ""
            locs.append(loc_text)
            if last_text != cfg["lastmod"]:
                err(loc_text or "(sitemap)", f"lastmod 应为 {cfg['lastmod']},实际 {last_text!r}")
        if len(locs) != len(set(locs)):
            err("sitemap.xml", "有重复的 loc")
        want = {BASE + p for p in pages}
        got = set(locs)
        if want - got:
            err("sitemap.xml", f"缺少 {len(want - got)} 个页面,例如 {sorted(want - got)[:3]}")
        if got - want:
            err("sitemap.xml", f"多出 {len(got - want)} 个 URL,例如 {sorted(got - want)[:3]}")

    robots = (OUT / "robots.txt").read_text(encoding="utf-8") if (OUT / "robots.txt").exists() else ""
    expect_robots = f"User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml\n"
    if robots != expect_robots:
        err("robots.txt", "内容与原先不一致")

    zh_home = pages.get("/", {})
    for url in ("https://718168.com", "https://rili.718168.com", "https://liaotown.com", "https://ai427.com"):
        if url not in zh_home.get("visible", "") and url not in (OUT / "index.html").read_text(encoding="utf-8"):
            err("/", f"页脚互链缺少 {url}")
    sample = OUT / "zhongliang" / "jin-kg" / "index.html"
    if sample.exists():
        text = sample.read_text(encoding="utf-8")
        if 'id="x"' not in text or 'id="y"' not in text:
            err("/zhongliang/jin-kg/", "换算器输入框不见了")
    if "rmbUpper" not in (OUT / "daxie" / "index.html").read_text(encoding="utf-8"):
        err("/daxie/", "人民币大写脚本不见了")

    howto_pages = [p for p, info in pages.items() if "HowTo" in info["types"]]
    faq_pages = [p for p, info in pages.items() if "FAQPage" in info["types"]]
    both = [p for p, info in pages.items() if "zh-CN" in info["alts"] and "en" in info["alts"]]
    print(f"页面 {len(pages)} | FAQ {len(faq_pages)} | HowTo {len(howto_pages)} | 双语互指 {len(both)} | sitemap {len(locs)}")
    if errors:
        print(f"失败 {len(errors)} 项:")
        for line in errors[:40]:
            print(" -", line)
        if len(errors) > 40:
            print(f" ... 还有 {len(errors) - 40} 项")
        return 1
    print("SEO 检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
