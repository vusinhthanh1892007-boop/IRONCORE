import asyncio
import base64
import random
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel
from playwright.async_api import async_playwright, Browser, BrowserContext, Page


class BrowserProfile(BaseModel):
    profile_id: str
    name: str
    user_agent: str
    viewport: Tuple[int, int]
    locale: str
    timezone: str
    platform: str
    webgl_vendor: str
    webgl_renderer: str
    canvas_noise_seed: int
    webrtc_disabled: bool = True
    fonts: List[str] = []
    plugins: List[str] = []
    hardware_concurrency: int = 8
    device_memory: int = 8
    # Phase 5 extended fields — used by FullFingerprintSpoofer
    battery_charging: bool = True
    battery_level: float = 0.93
    battery_charging_time: float = 0.0
    battery_discharging_time: float = float("inf")
    webgl_extensions: List[str] = [
        "ANGLE_instanced_arrays", "EXT_blend_minmax",
        "EXT_color_buffer_half_float", "EXT_disjoint_timer_query",
        "EXT_float_blend", "EXT_frag_depth", "EXT_shader_texture_lod",
        "EXT_texture_compression_bptc", "EXT_texture_filter_anisotropic",
        "OES_element_index_uint", "OES_standard_derivatives",
        "OES_texture_float", "OES_texture_float_linear",
        "OES_texture_half_float", "OES_texture_half_float_linear",
        "OES_vertex_array_object", "WEBGL_color_buffer_float",
        "WEBGL_compressed_texture_s3tc", "WEBGL_debug_renderer_info",
        "WEBGL_debug_shaders", "WEBGL_depth_texture",
        "WEBGL_draw_buffers", "WEBGL_lose_context",
    ]



class NavigationResult(BaseModel):
    success: bool
    url: str
    status_code: Optional[int]
    error: Optional[str] = None


class FingerprintSpoofer:
    """Inject scripts before page load to spoof fingerprint vectors."""

    @staticmethod
    def _spoof_navigator_webdriver() -> str:
        return """
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
        });
        """

    @staticmethod
    def _spoof_navigator_languages(locale: str) -> str:
        return f"""
        Object.defineProperty(navigator, 'languages', {{
            get: () => ['{locale}', '{locale.split('-')[0]}'],
        }});
        Object.defineProperty(navigator, 'language', {{
            get: () => '{locale}',
        }});
        """

    @staticmethod
    def _spoof_canvas(noise_seed: int) -> str:
        return f"""
        (function() {{
            const seed = {noise_seed};
            // Seeded pseudo-random number generator (LCG) for deterministic noise
            function seededRand(s) {{
                return function() {{
                    s = (s * 1664525 + 1013904223) & 0xFFFFFFFF;
                    return (s >>> 0) / 0xFFFFFFFF;
                }};
            }}
            const rand = seededRand(seed);

            // Override toDataURL to inject deterministic pixel noise
            const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
            HTMLCanvasElement.prototype.toDataURL = function(...args) {{
                const ctx = this.getContext('2d');
                if (ctx) {{
                    const imageData = ctx.getImageData(0, 0, this.width, this.height);
                    for (let i = 0; i < imageData.data.length; i += 4) {{
                        // Add ±1 noise to R, G, B channels only (alpha unchanged)
                        imageData.data[i]     = Math.min(255, Math.max(0, imageData.data[i]     + (rand() > 0.5 ? 1 : -1)));
                        imageData.data[i + 1] = Math.min(255, Math.max(0, imageData.data[i + 1] + (rand() > 0.5 ? 1 : -1)));
                        imageData.data[i + 2] = Math.min(255, Math.max(0, imageData.data[i + 2] + (rand() > 0.5 ? 1 : -1)));
                    }}
                    ctx.putImageData(imageData, 0, 0);
                }}
                return origToDataURL.apply(this, args);
            }};

            // Also override getImageData to add noise directly
            const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
            CanvasRenderingContext2D.prototype.getImageData = function(...args) {{
                const imageData = origGetImageData.apply(this, args);
                const r = seededRand(seed + args[0] + args[1]);
                for (let i = 0; i < imageData.data.length; i += 4) {{
                    imageData.data[i]     = Math.min(255, Math.max(0, imageData.data[i]     + (r() > 0.5 ? 1 : 0)));
                    imageData.data[i + 1] = Math.min(255, Math.max(0, imageData.data[i + 1] + (r() > 0.5 ? 1 : 0)));
                    imageData.data[i + 2] = Math.min(255, Math.max(0, imageData.data[i + 2] + (r() > 0.5 ? 1 : 0)));
                }}
                return imageData;
            }};
        }})();
        """

    @staticmethod
    def _spoof_webgl(vendor: str, renderer: str) -> str:
        return f"""
        const getParameterProxyHandler = {{
            apply: function(target, ctx, args) {{
                const param = args[0];
                if (param === 37445) return '{vendor}'; // UNMASKED_VENDOR_WEBGL
                if (param === 37446) return '{renderer}'; // UNMASKED_RENDERER_WEBGL
                return Reflect.apply(target, ctx, args);
            }}
        }};
        if (typeof WebGLRenderingContext !== 'undefined') {{
            WebGLRenderingContext.prototype.getParameter = new Proxy(
                WebGLRenderingContext.prototype.getParameter,
                getParameterProxyHandler
            );
        }}
        if (typeof WebGL2RenderingContext !== 'undefined') {{
            WebGL2RenderingContext.prototype.getParameter = new Proxy(
                WebGL2RenderingContext.prototype.getParameter,
                getParameterProxyHandler
            );
        }}
        """

    @staticmethod
    def _spoof_webrtc() -> str:
        return """
        Object.defineProperty(navigator, 'mediaDevices', {
            value: { getUserMedia: () => Promise.reject(new Error('Requested device not found')) },
            enumerable: true,
            configurable: true,
            writable: false
        });
        Object.defineProperty(window, 'RTCPeerConnection', {
            value: function() { console.log('RTCPeerConnection intercepted'); },
            enumerable: true,
            configurable: true,
            writable: false
        });
        """

    @staticmethod
    def _spoof_screen(viewport: Tuple[int, int]) -> str:
        width, height = viewport
        return f"""
        Object.defineProperty(window.screen, 'width', {{ get: () => {width} }});
        Object.defineProperty(window.screen, 'height', {{ get: () => {height} }});
        Object.defineProperty(window.screen, 'availWidth', {{ get: () => {width} }});
        Object.defineProperty(window.screen, 'availHeight', {{ get: () => {height - 40} }});
        """

    @staticmethod
    def _spoof_timezone(timezone: str) -> str:
        return f"""
        const OriginalDateTimeFormat = Intl.DateTimeFormat;
        Intl.DateTimeFormat = function(locales, options) {{
            let newOptions = options || {{}};
            newOptions.timeZone = newOptions.timeZone || '{timezone}';
            return new OriginalDateTimeFormat(locales, newOptions);
        }};
        Intl.DateTimeFormat.prototype = OriginalDateTimeFormat.prototype;
        """

    @staticmethod
    def _spoof_platform(platform: str) -> str:
        return f"""
        Object.defineProperty(navigator, 'platform', {{
            get: () => '{platform}',
        }});
        """

    @staticmethod
    def _spoof_hardware(hardware_concurrency: int, device_memory: int) -> str:
        return f"""
        Object.defineProperty(navigator, 'hardwareConcurrency', {{
            get: () => {hardware_concurrency},
        }});
        Object.defineProperty(navigator, 'deviceMemory', {{
            get: () => {device_memory},
        }});
        """

    @staticmethod
    def _spoof_plugins(plugins: List[str]) -> str:
        # Build a realistic plugins array string for JavaScript injection
        plugins_js = ', '.join(
            f'{{name: "{p}", description: "", filename: "", length: 0}}'
            for p in plugins
        )
        return f"""
        Object.defineProperty(navigator, 'plugins', {{
            get: () => [{plugins_js}],
        }});
        Object.defineProperty(navigator, 'mimeTypes', {{
            get: () => [],
        }});
        """

    @classmethod
    def generate_init_scripts(cls, profile: BrowserProfile) -> List[str]:
        scripts = [
            cls._spoof_navigator_webdriver(),
            cls._spoof_navigator_languages(profile.locale),
            cls._spoof_canvas(profile.canvas_noise_seed),
            cls._spoof_webgl(profile.webgl_vendor, profile.webgl_renderer),
            cls._spoof_screen(profile.viewport),
            cls._spoof_timezone(profile.timezone),
            cls._spoof_platform(profile.platform),
            cls._spoof_hardware(profile.hardware_concurrency, profile.device_memory),
            cls._spoof_plugins(profile.plugins),
        ]
        if profile.webrtc_disabled:
            scripts.append(cls._spoof_webrtc())
        return scripts


class StealthBrowser:
    def __init__(self, profile: BrowserProfile):
        self.profile = profile
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    async def start(self) -> None:
        """Launch Playwright with all stealth configurations."""
        self._playwright = await async_playwright().start()
        
        args = [
            '--disable-blink-features=AutomationControlled',
            '--disable-web-security',
            '--disable-features=IsolateOrigins,site-per-process',
            '--ignore-certificate-errors',
        ]
        if self.profile.webrtc_disabled:
            args.extend([
                '--disable-webrtc-hw-decoding',
                '--disable-webrtc-hw-encoding',
            ])

        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=args,
        )

        width, height = self.profile.viewport
        
        self._context = await self._browser.new_context(
            user_agent=self.profile.user_agent,
            viewport={"width": width, "height": height},
            locale=self.profile.locale,
            timezone_id=self.profile.timezone,
            has_touch=False,
            is_mobile=False,
            device_scale_factor=1,
            color_scheme="dark"
        )

        scripts = FingerprintSpoofer.generate_init_scripts(self.profile)
        for script in scripts:
            await self._context.add_init_script(script)

        self._page = await self._context.new_page()

    async def navigate(self, url: str, wait_for: str = "networkidle") -> NavigationResult:
        """Navigate with human-like timing."""
        if not self._page:
            return NavigationResult(success=False, url=url, status_code=None, error="Page not initialized")
        
        try:
            # Human-like pre-navigation delay
            delay_ms = random.gauss(mu=120, sigma=30)
            await asyncio.sleep(max(0.05, delay_ms / 1000))
            
            response = await self._page.goto(url, wait_until=wait_for)
            status = response.status if response else None
            return NavigationResult(success=True, url=url, status_code=status)
        except Exception as e:
            return NavigationResult(success=False, url=url, status_code=None, error=str(e))

    async def screenshot_b64(self, selector: Optional[str] = None) -> str:
        """Take screenshot, return Base64."""
        if not self._page:
            return ""
        
        if selector:
            element = await self._page.wait_for_selector(selector)
            if element:
                image_bytes = await element.screenshot()
            else:
                image_bytes = b""
        else:
            image_bytes = await self._page.screenshot()
            
        return base64.b64encode(image_bytes).decode('utf-8')

    async def get_content(self) -> str:
        """Get page DOM/text content."""
        if not self._page:
            return ""
        return await self._page.content()

    async def close(self) -> None:
        """Cleanup graceful."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

# The tool registrations (for IronCoreEngine)
import logging
from ironcore.core.engine import ToolDefinition, RiskLevel, Observation

logger = logging.getLogger(__name__)

async def stealth_navigate_handler(url: str) -> Observation:
    # A generic profile for one-off tool handler tasks
    profile = BrowserProfile(
        profile_id="default",
        name="Default Profile",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport=(1920, 1080),
        locale="en-US",
        timezone="America/New_York",
        platform="Win32",
        webgl_vendor="Google Inc. (NVIDIA)",
        webgl_renderer="ANGLE (NVIDIA, NVIDIA GeForce RTX 3080 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        canvas_noise_seed=42,
        fonts=["Arial", "Verdana", "Times New Roman"],
        plugins=["Chrome PDF Plugin"],
        hardware_concurrency=8,
        device_memory=8,
    )
    
    async with StealthBrowser(profile) as browser:
        res = await browser.navigate(url)
        content = await browser.get_content()
        
    return Observation(
        content=content if res.success else res.error,
        status="success" if res.success else "error"
    )

stealth_navigate_tool = ToolDefinition(
    name="stealth_navigate", 
    handler=stealth_navigate_handler, 
    risk_level=RiskLevel.HIGH,
    requires_sandbox=False,
    description="Navigate to URL using stealth browser with anti-bot bypass",
)

# Other stub tool definitions matching requirements
async def stealth_screenshot_handler(url: str, selector: Optional[str] = None) -> Observation:
    profile = BrowserProfile(
        profile_id="default_screenshot",
        name="Default Screenshot Profile",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport=(1920, 1080),
        locale="en-US",
        timezone="America/New_York",
        platform="Win32",
        webgl_vendor="Google Inc. (NVIDIA)",
        webgl_renderer="ANGLE (NVIDIA, NVIDIA GeForce RTX 3080 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        canvas_noise_seed=42,
        fonts=["Arial", "Verdana", "Times New Roman"],
        plugins=["Chrome PDF Plugin"],
        hardware_concurrency=8,
        device_memory=8,
    )
    async with StealthBrowser(profile) as browser:
        await browser.navigate(url)
        b64 = await browser.screenshot_b64(selector)
    return Observation(content=b64, status="success")

stealth_screenshot_tool = ToolDefinition(
    name="stealth_screenshot",
    handler=stealth_screenshot_handler,
    risk_level=RiskLevel.MEDIUM,
    requires_sandbox=False,
    description="Navigate to URL and take screenshot as Base64",
)

async def get_page_content_handler(url: str) -> Observation:
    # This handler just calls stealth_navigate_handler under the hood
    return await stealth_navigate_handler(url)

get_page_content_tool = ToolDefinition(
    name="get_page_content",
    handler=get_page_content_handler,
    risk_level=RiskLevel.LOW,
    requires_sandbox=False,
    description="Get page DOM/text content from URL",
)

# ─── stealth_click ────────────────────────────────────────────────────────────
async def stealth_click_handler(url: str, selector: str) -> Observation:
    """
    Navigate to URL via stealth browser and click the element matching `selector`.
    Uses Bezier MouseEngine for human-like interaction.
    """
    from ironcore.browser.mouse_engine import MouseEngine

    profile = BrowserProfile(
        profile_id="click_profile",
        name="Click Profile",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport=(1920, 1080),
        locale="en-US",
        timezone="America/New_York",
        platform="Win32",
        webgl_vendor="Google Inc. (NVIDIA)",
        webgl_renderer="ANGLE (NVIDIA, NVIDIA GeForce RTX 3080 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        canvas_noise_seed=99,
        fonts=["Arial", "Verdana", "Times New Roman"],
        plugins=["Chrome PDF Plugin"],
        hardware_concurrency=8,
        device_memory=8,
    )
    mouse_engine = MouseEngine()

    async with StealthBrowser(profile) as browser:
        nav_result = await browser.navigate(url)
        if not nav_result.success:
            return Observation(content=nav_result.error, status="error")

        element = await browser._page.wait_for_selector(selector, timeout=10000)
        if not element:
            return Observation(content=f"Element not found: {selector}", status="error")

        box = await element.bounding_box()
        if not box:
            return Observation(content=f"Cannot get bounding box for: {selector}", status="error")

        target_x = box['x'] + box['width'] / 2
        target_y = box['y'] + box['height'] / 2
        await mouse_engine.click(browser._page, target_x, target_y)
        logger.info("[Ghost/stealth_click] Clicked '%s' at (%.0f, %.0f)", selector, target_x, target_y)

    return Observation(content=f"Clicked {selector}", status="success")

stealth_click_tool = ToolDefinition(
    name="stealth_click",
    handler=stealth_click_handler,
    risk_level=RiskLevel.HIGH,
    requires_sandbox=False,
    description="Navigate to URL and click element matching CSS selector using Bezier mouse",
)

# ─── stealth_fill_form ────────────────────────────────────────────────────────
async def stealth_fill_form_handler(url: str, form_data: dict) -> Observation:
    """
    Navigate to URL and fill form fields using human-like typing.
    form_data: {"css_selector": "value_to_type", ...}
    """
    from ironcore.browser.mouse_engine import MouseEngine

    profile = BrowserProfile(
        profile_id="form_profile",
        name="Form Profile",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport=(1920, 1080),
        locale="en-US",
        timezone="America/New_York",
        platform="Win32",
        webgl_vendor="Google Inc. (NVIDIA)",
        webgl_renderer="ANGLE (NVIDIA, NVIDIA GeForce RTX 3080 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        canvas_noise_seed=77,
        fonts=["Arial", "Verdana", "Times New Roman"],
        plugins=["Chrome PDF Plugin"],
        hardware_concurrency=8,
        device_memory=8,
    )
    mouse_engine = MouseEngine()
    filled = []

    async with StealthBrowser(profile) as browser:
        nav_result = await browser.navigate(url)
        if not nav_result.success:
            return Observation(content=nav_result.error, status="error")

        for selector, value in form_data.items():
            try:
                element = await browser._page.wait_for_selector(selector, timeout=8000)
                if not element:
                    logger.warning("[Ghost/fill_form] Selector not found: %s", selector)
                    continue

                box = await element.bounding_box()
                if box:
                    # Click the field first with Bezier mouse
                    await mouse_engine.click(browser._page, box['x'] + box['width']/2, box['y'] + box['height']/2)
                    await asyncio.sleep(random.gauss(0.2, 0.05))

                # Clear existing text then type with human-like delay
                await element.triple_click()
                await browser._page.keyboard.type(str(value), delay=random.gauss(80, 25))
                await asyncio.sleep(random.gauss(0.3, 0.1))
                filled.append(selector)
                logger.info("[Ghost/fill_form] Filled '%s'", selector)
            except Exception as e:
                logger.warning("[Ghost/fill_form] Error filling %s: %s", selector, e)

    return Observation(
        content=f"Filled {len(filled)}/{len(form_data)} fields: {filled}",
        status="success" if filled else "error"
    )

stealth_fill_form_tool = ToolDefinition(
    name="stealth_fill_form",
    handler=stealth_fill_form_handler,
    risk_level=RiskLevel.HIGH,
    requires_sandbox=False,
    description="Navigate to URL and fill form fields with human-like typing speed",
)
