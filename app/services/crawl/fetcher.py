from __future__ import annotations

import contextlib
import re

from app.core.config import Settings


class HttpFetcher:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._playwright = None
        self._browser = None

    async def _ensure_browser(self):
        if self._browser is not None:
            return self._browser
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - depends on optional runtime package
            raise RuntimeError(
                "未安装 Playwright。请先执行 `pip install playwright` "
                "并运行 `playwright install chromium`。"
            ) from exc

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        return self._browser

    async def _auto_scroll(self, page) -> None:
        previous_height = -1
        stable_rounds = 0
        for _ in range(self._settings.browser_scroll_rounds):
            height = await page.evaluate("() => document.body ? document.body.scrollHeight : 0")
            await page.evaluate(
                "() => window.scrollTo({ top: document.body ? document.body.scrollHeight : 0, behavior: 'instant' })"
            )
            await page.wait_for_timeout(self._settings.browser_scroll_pause_ms)
            if height == previous_height:
                stable_rounds += 1
                if stable_rounds >= 2:
                    break
            else:
                stable_rounds = 0
            previous_height = height

    async def _auto_accept_consent(self, page) -> list[str]:
        clicked: list[str] = []
        button_texts = [
            "Accept",
            "Accept All",
            "I Agree",
            "Agree",
            "Continue",
            "同意",
            "接受",
            "接受全部",
            "继续",
        ]
        selectors = [
            "button[data-tracking-opt-in-accept='true']",
            "button[mode='primary']",
            "button:has-text('Accept')",
            "button:has-text('同意')",
            "button:has-text('接受')",
        ]

        for frame in page.frames:
            for selector in selectors:
                locator = frame.locator(selector).first
                with contextlib.suppress(Exception):
                    if await locator.is_visible(timeout=1200):
                        await locator.click(timeout=1200)
                        clicked.append(selector)
            for text in button_texts:
                locator = frame.get_by_role("button", name=re.compile(text, re.I)).first
                with contextlib.suppress(Exception):
                    if await locator.is_visible(timeout=1200):
                        await locator.click(timeout=1200)
                        clicked.append(text)
        return clicked

    async def _fetch_with_browser(
        self,
        url: str,
        referer: str | None = None,
    ) -> tuple[str, int, str, str]:
        browser = await self._ensure_browser()
        headers = {"Accept-Language": f"{self._settings.browser_locale},zh;q=0.9,en;q=0.8"}
        if referer:
            headers["Referer"] = referer
        context = await browser.new_context(
            user_agent=self._settings.user_agent,
            locale=self._settings.browser_locale,
            viewport={"width": 1440, "height": 2200},
            extra_http_headers=headers,
        )
        page = await context.new_page()
        page.set_default_navigation_timeout(self._settings.browser_navigation_timeout_ms)
        page.set_default_timeout(self._settings.browser_navigation_timeout_ms)
        try:
            response = await page.goto(url, wait_until="domcontentloaded")
            if response is None:
                raise RuntimeError("浏览器抓取失败：未收到页面响应。")

            with contextlib.suppress(Exception):
                await page.wait_for_load_state("networkidle", timeout=min(5000, self._settings.browser_navigation_timeout_ms))
            if self._settings.browser_post_load_wait_ms > 0:
                await page.wait_for_timeout(self._settings.browser_post_load_wait_ms)

            if self._settings.browser_auto_accept_consent:
                clicked_buttons = await self._auto_accept_consent(page)
                if clicked_buttons and self._settings.browser_post_load_wait_ms > 0:
                    await page.wait_for_timeout(self._settings.browser_post_load_wait_ms)

            await self._auto_scroll(page)

            # 再等一小段时间，让滚动触发的延迟加载内容完成渲染。
            if self._settings.browser_post_load_wait_ms > 0:
                await page.wait_for_timeout(self._settings.browser_post_load_wait_ms)

            html = await page.content()
            status_code = response.status
            final_url = page.url
            return final_url, status_code, html, "browser"
        finally:
            await page.close()
            await context.close()

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def fetch(self, url: str, referer: str | None = None) -> tuple[str, int, str, str]:
        return await self._fetch_with_browser(url, referer=referer)
