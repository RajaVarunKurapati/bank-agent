"""
SurfaceDriver: the only component that knows we're using a browser.
Everything else (agent, replay) talks to it in surface-neutral terms:
observe() -> what's on screen, act() -> do one thing.
Swap this class for a desktop/accessibility driver and the artifacts still apply.
"""
from playwright.sync_api import sync_playwright


class SurfaceDriver:
    def __init__(self, headless=False):
        self._pw = sync_playwright().start()
        # headed by default so a human can take over the SAME session later (Phase 7)
        self.browser = self._pw.chromium.launch(headless=headless)
        self.context = self.browser.new_context()
        self.page = self.context.new_page()

    def navigate(self, url):
        self.page.goto(url, wait_until="domcontentloaded")

    def observe(self):
        """
        Return a surface-neutral snapshot: the accessibility tree (as ARIA text),
        the current URL, and the same for any child frames (our iframe detail view).
        We read the a11y tree instead of raw HTML so the approach carries over
        to surfaces with no clean DOM.
        """
        trees = []
        for frame in [self.page.main_frame] + [
            f for f in self.page.frames if f != self.page.main_frame
        ]:
            try:
                tree = frame.locator("body").aria_snapshot()
                if tree.strip():
                    trees.append(tree)
            except Exception:
                continue
        return {
            "url": self.page.url,
            "elements": "\n".join(trees),
        }


    def screenshot(self, path):
        self.page.screenshot(path=path, full_page=True)
        return path

    # ---- actions the agent can take ----

    def click(self, role=None, name=None, text=None):
        locator = self._resolve(role, name, text)
        locator.click(timeout=5000)

    def type(self, value, role=None, name=None, text=None):
        locator = self._resolve(role, name, text)
        locator.fill(value, timeout=5000)

    def read_text(self):
        """Read all visible text on the page/frames (for extracting outputs)."""
        texts = [self.page.inner_text("body")]
        for frame in self.page.frames:
            if frame != self.page.main_frame:
                try:
                    texts.append(frame.inner_text("body"))
                except Exception:
                    pass
        return "\n".join(texts)

    def has_text(self, text):
        """Checkpoint helper: is this text present anywhere on page or in frames?"""
        return text.lower() in self.read_text().lower()

    def _resolve(self, role=None, name=None, text=None):
        """
        Ordered locator strategy. This IS the robustness story:
        1. role + accessible name (most stable)
        2. name as a button
        3. visible text
        4. role alone, if unambiguous (handles legacy inputs with no label)
        Searches the main frame and all child frames (handles the iframe).
        """
        frames = [self.page] + [f for f in self.page.frames
                                if f != self.page.main_frame]
        for frame in frames:
            try:
                if role and name:
                    loc = frame.get_by_role(role.lower(), name=name)
                    if loc.count() > 0:
                        return loc.first
                if name:
                    loc = frame.get_by_role("button", name=name)
                    if loc.count() > 0:
                        return loc.first
                if text:
                    loc = frame.get_by_text(text, exact=False)
                    if loc.count() > 0:
                        return loc.first
                # Fallback for unlabeled legacy controls: role alone if unambiguous
                if role:
                    loc = frame.get_by_role(role.lower())
                    if loc.count() == 1:
                        return loc.first
                    if loc.count() > 1:
                        return loc.first  # take the first; good enough for a linear form
            except Exception:
                continue
        raise LookupError(f"No element found for role={role} name={name} text={text}")

    def close(self):
        self.context.close()
        self.browser.close()
        self._pw.stop()