"""
Browser check for the public website (needs Playwright + Chromium).

    PORT=8766 python tests/serve_fake.py &           # real app, fake YouTube API
    python tests/e2e_site.py http://127.0.0.1:8766 [screenshot_dir]

Walks: landing -> brand name -> pick channel -> every result page -> report -> share link in a
fresh browser context -> expired link -> dark mode -> phone width. Fails on any JS error,
failed request, or Content-Security-Policy violation.
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8766"
SHOTS = sys.argv[2] if len(sys.argv) > 2 else None
problems, checks = [], []


def check(name, ok, detail=""):
    checks.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=True)


def wire(page):
    page.on("console", lambda m: problems.append(f"console {m.type}: {m.text}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    page.on("requestfailed", lambda r: problems.append(f"requestfailed: {r.url} {r.failure}"))
    page.on("response", lambda r: problems.append(f"http {r.status}: {r.url}") if r.status >= 400 and "/api/" not in r.url else None)


def wire_lenient(page):
    """For the pages that deliberately visit an expired link and a 404: those 4xx responses are expected,
    but JS errors and CSP violations are still failures."""
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    page.on("console", lambda m: problems.append(f"csp/console: {m.text}") if "Content Security Policy" in m.text else None)


def section(page, name):
    page.click(f'.section-list a[data-section="{name}"]')
    page.wait_for_function("n => document.querySelector('.section-list a[aria-current=page]').dataset.section === n", arg=name)
    page.wait_for_selector("#view h2")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1180, "height": 900}, accept_downloads=True)
        page = ctx.new_page()
        wire(page)

        # ---- landing
        page.goto(BASE)
        check("landing title", "Data Detective" in page.title())
        check("h1 and big search box", page.is_visible("h1") and page.is_visible("#q") and page.is_visible("#go"))
        check("meta description + og:image", page.get_attribute('meta[name="description"]', "content") and page.get_attribute('meta[property="og:image"]', "content").endswith("/static/og.png"))
        shot(page, "01_landing")
        page.click("#go")
        page.wait_for_selector("#search-error:not([hidden])")
        check("empty submit shows an error", "Type a YouTube channel" in page.inner_text("#search-error"))

        # ---- brand name -> candidates -> analysis
        page.fill("#q", "Some Brand")
        page.click("#go")
        page.wait_for_selector(".candidate")
        check("brand name lists candidate channels to confirm", page.locator(".candidate").count() >= 1 and "Test Channel" in page.inner_text(".candidate"))
        shot(page, "02_candidates")
        page.click(".candidate")
        page.wait_for_url("**/analysis/*/overview", timeout=30000)
        share_url = page.url
        page.wait_for_selector("#view .tiles")
        check("overview shows tiles and top videos", page.locator("#view .tile").count() >= 6 and page.locator("#view table a").count() == 10)
        check("video links go to youtube.com", page.get_attribute("#view table a", "href").startswith("https://www.youtube.com/watch?v="))
        check("snapshot banner shows fetch details", "fetched" in page.inner_text("#snapshot-text") and "API units" in page.inner_text("#snapshot-text"))
        shot(page, "03_overview")

        # ---- every page
        section(page, "cleaned")
        page.wait_for_selector("#view .steps")
        check("cleaned: steps, missing table, columns", page.locator("#view .steps li").count() >= 4 and page.locator("#view table").count() >= 3)
        check("cleaned: hidden counts explained as missing, not zero", "not counted as 0" in page.inner_text("#view"))
        shot(page, "04_cleaned")

        section(page, "explore")
        page.wait_for_selector("#view .chart svg")
        check("explore: charts + group-size column", page.locator("#view .chart svg").count() >= 3 and "Videos" in page.inner_text("#view"))
        check("explore: views-are-not-reach warning", "Views are not reach" in page.inner_text("#view"))
        page.select_option("#x-group", "category")
        page.wait_for_function("() => document.querySelector('#view h3').innerText.includes('category')")
        check("explore: changing the group re-draws", "by category" in page.inner_text("#view"))
        page.fill("#x-min", "40")
        page.wait_for_function("() => document.querySelector('#view').innerText.includes('few videos')")
        check("explore: raising the minimum flags small groups", True)
        shot(page, "05_explore")

        section(page, "sentiment")
        page.click("text=Collect and score comments")
        page.wait_for_selector("#view .sent-body .tiles", timeout=30000)
        check("sentiment: five tiles and two charts", page.locator("#view .sent-body .tiles .tile").count() == 5 and page.locator("#view .sent-body .chart svg").count() == 2)
        check("sentiment: topics, by-video table and example comments", page.locator("#view .sent-body table").count() >= 3 and page.locator("#view .quotes li").count() >= 2)
        check("sentiment: scoring caveat is shown", "estimate" in page.inner_text("#view") and "accuracy has not been measured" in page.inner_text("#view").lower())
        before = page.inner_text("#view .sent-body .tiles .tile")
        page.select_option("#f-lang", "roman_urdu")
        page.wait_for_function("b => document.querySelector('#view .sent-body .tiles .tile').innerText !== b", arg=before)
        check("sentiment: language filter re-slices without a new fetch", page.locator("#view .sent-body .tiles .tile").count() == 5)
        page.select_option("#f-lang", "")
        page.fill("#f-from", "2030-01-01"); page.dispatch_event("#f-from", "change")
        page.wait_for_selector("text=No comments match these filters")
        check("sentiment: empty selection explains itself", True)
        page.fill("#f-from", ""); page.dispatch_event("#f-from", "change")
        page.wait_for_selector("#view .sent-body .tiles")
        shot(page, "05b_sentiment")

        section(page, "meaning")
        page.wait_for_selector(".finding")
        txt = page.inner_text("#view")
        check("meaning: Finding/Evidence/Action/Limitation on every card",
              page.locator(".finding").count() >= 4 and all(w in txt for w in ("Finding", "Evidence", "Action", "Limitation")))
        check("meaning: thin evidence is flagged", page.locator(".flag").count() >= 1)
        shot(page, "06_meaning")

        section(page, "scaling")
        page.click("text=Run the experiment")
        page.wait_for_selector("#view .chart svg", timeout=30000)
        check("scaling: table + log chart", page.locator("#view table tbody tr").count() == 3)
        shot(page, "07_scaling")

        section(page, "models")
        page.click("text=Run the three previews")
        page.wait_for_selector("#view .cards .card", timeout=30000)
        check("models: three cards with baselines", page.locator("#view .cards .card").count() == 3 and "Always guessing" in page.inner_text("#view"))
        shot(page, "08_models")

        section(page, "report")
        with page.expect_download() as dl:
            page.click("text=Download report (.md)")
        d = dl.value
        body = open(d.path(), encoding="utf-8").read()
        check("report downloads as markdown with snapshot + FEAL sections", d.suggested_filename.endswith(".md") and "## 1. Data snapshot" in body and "**Limitation:**" in body)
        shot(page, "09_report")

        # ---- back/forward + deep link
        page.go_back()
        check("browser back works between pages", page.url.endswith("/models"))
        page.go_forward()
        page.reload()
        page.wait_for_selector("#view h2")
        check("reload keeps the page", page.url.endswith("/report") and "Report" in page.inner_text("#view h2"))

        # ---- share link in a fresh context
        ctx2 = browser.new_context(viewport={"width": 1180, "height": 900})
        p2 = ctx2.new_page()
        wire_lenient(p2)
        p2.goto(share_url)
        p2.wait_for_selector("#view .tiles")
        check("share link opens in a fresh browser", "Test Channel" in p2.inner_text("#view h2"))
        p2.goto(BASE + "/analysis/AAAAAAAAAAAAAAAA/overview")
        p2.wait_for_selector("text=This result has expired")
        check("expired link explains itself and offers a restart", p2.is_visible("text=Start a new analysis"))
        shot(p2, "10_expired")
        p2.goto(BASE + "/nope")
        check("404 page", "Page not found" in p2.inner_text("h1"))
        ctx2.close()

        # ---- static pages
        for path, h1 in (("/about", "About"), ("/how-it-works", "How it works"), ("/privacy", "Data and privacy")):
            page.goto(BASE + path)
            check(f"{path} renders", h1 in page.inner_text("h1"))
        shot(page, "11_how")

        # ---- keyboard: skip link, search by keyboard
        page.goto(BASE)
        page.keyboard.press("Tab")
        check("skip link is first focus stop", page.evaluate("document.activeElement.className") == "skip")

        # ---- dark mode + phone
        dctx = browser.new_context(viewport={"width": 1180, "height": 900}, color_scheme="dark")
        dp = dctx.new_page()
        wire(dp)
        dp.goto(BASE)
        bg = dp.evaluate("getComputedStyle(document.body).backgroundColor")
        check("dark mode follows the system", bg != "rgb(245, 247, 246)", bg)
        shot(dp, "12_dark_landing")
        dctx.close()
        mctx = browser.new_context(viewport={"width": 390, "height": 800}, is_mobile=True)
        mp = mctx.new_page()
        wire(mp)
        mp.goto(share_url)
        mp.wait_for_selector("#view .tiles")
        no_x = mp.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        check("phone: no sideways page scroll on results", no_x)
        shot(mp, "13_phone_results")
        mp.goto(BASE)
        check("phone: landing has no sideways scroll", mp.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"))
        shot(mp, "14_phone_landing")
        mctx.close()
        browser.close()

    check("no JS errors, failed requests or CSP violations", not problems, "; ".join(problems[:5]))
    bad = [c for c in checks if not c[1]]
    print(f"\n{len(checks) - len(bad)} of {len(checks)} checks passed")
    sys.exit(1 if bad else 0)


main()
