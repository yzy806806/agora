"""Quick DOM inspection — dump page structure after login."""
import asyncio
from playwright.async_api import async_playwright

DASHBOARD_URL = "http://localhost:18765"
ADMIN_PASS = "wKHITmcn2mIrat2"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()

        # Login
        resp = await page.request.post(
            DASHBOARD_URL + "/auth/password-login",
            data='{"provider":"basic","username":"admin","password":"' + ADMIN_PASS + '"}',
            headers={"Content-Type": "application/json"},
        )
        print(f"Login: {resp.status}")

        # Navigate to dashboard
        await page.goto(DASHBOARD_URL + "/", wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(3000)

        # Dump page structure
        html = await page.content()
        print(f"Page length: {len(html)}")
        print(f"Page title: {await page.title()}")

        # Find all visible text
        texts = await page.evaluate("""() => {
            const texts = [];
            document.querySelectorAll('h1, h2, h3, button, a, [role="tab"], [role="button"]').forEach(el => {
                const t = el.textContent.trim();
                if (t && t.length < 100) texts.push(el.tagName + ': ' + t);
            });
            return texts.slice(0, 30);
        }""")
        print("\nVisible elements:")
        for t in texts:
            print(f"  {t}")

        # Find plugin-related elements
        plugins = await page.evaluate("""() => {
            const els = [];
            document.querySelectorAll('[class*="plugin"], [class*="agora"], [data-plugin], iframe').forEach(el => {
                els.push({
                    tag: el.tagName,
                    class: el.className,
                    id: el.id,
                    text: el.textContent.trim().slice(0, 80),
                });
            });
            return els.slice(0, 20);
        }""")
        print("\nPlugin/Agora elements:")
        for p in plugins:
            print(f"  {p}")

        # Check if there are iframes
        iframes = await page.locator('iframe').count()
        print(f"\nIframes: {iframes}")

        # Check sidebar/nav
        nav = await page.evaluate("""() => {
            const navs = document.querySelectorAll('nav, aside, [class*="sidebar"], [class*="nav"]');
            return Array.from(navs).map(n => ({
                tag: n.tagName,
                class: n.className,
                text: n.textContent.trim().slice(0, 200),
            }));
        }""")
        print("\nNav/Sidebar:")
        for n in nav:
            print(f"  {n}")

        # Take screenshot without waiting for fonts
        await page.screenshot(path="/root/agora/e2e-screenshots/dom-inspect.png", full_page=False)
        print("\nScreenshot saved")

        await browser.close()

asyncio.run(main())
