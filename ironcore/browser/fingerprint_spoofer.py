"""
ironcore/browser/fingerprint_spoofer.py — Phase 5: FullFingerprintSpoofer
Canvas/WebGL/Audio/Battery/GPU/Font/Misc fingerprint spoofing — Production grade.

Vectors (theo thứ tự nguy hiểm):
  1. Canvas  — toDataURL / getImageData LCG noise        [CRITICAL]
  2. WebGL   — vendor/renderer/extensions (GL1+GL2)      [CRITICAL]
  3. Audio   — AudioBuffer.getChannelData ±1e-7 noise    [HIGH]
  4. Battery — getBattery() stable fake values           [MEDIUM]
  5. GPU     — navigator.gpu WebGPU adapter info         [MEDIUM]
  6. Font    — document.fonts.check() whitelist          [MEDIUM]
  7. Misc    — connection/DNT/window.chrome/permissions  [LOW]
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

try:
    from playwright.async_api import BrowserContext, Page
except ImportError:
    BrowserContext = Any  # type: ignore
    Page = Any  # type: ignore


def _j(v: Any) -> str:
    """JSON-serialize a Python value to a JS-safe string."""
    return json.dumps(v)


# ─── BrowserProfile ─────────────────────────────────────────────────────────
# Import from stealth.py to avoid duplication, fall back to local definition
# if stealth is not importable (e.g. playwright missing)
try:
    from ironcore.browser.stealth import BrowserProfile  # type: ignore
except Exception:
    # Fallback: standalone definition (used when playwright is not installed)
    class BrowserProfile(BaseModel):  # type: ignore[no-redef]
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
        fonts: List[str] = Field(default_factory=list)
        plugins: List[str] = Field(default_factory=list)
        hardware_concurrency: int = 8
        device_memory: int = 8
        battery_charging: bool = True
        battery_level: float = 0.93
        battery_charging_time: float = 0.0
        battery_discharging_time: float = float("inf")
        webgl_extensions: List[str] = Field(
            default_factory=lambda: [
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
        )


# ─── Result model ─────────────────────────────────────────────────────────────

class FingerprintVerificationResult(BaseModel):
    success: bool
    url: str
    checks: Dict[str, bool]
    observed: Dict[str, Any]
    errors: List[str] = Field(default_factory=list)


# ─── FullFingerprintSpoofer ───────────────────────────────────────────────────

class FullFingerprintSpoofer:
    """
    Phase 5 — Orchestrates ALL fingerprint spoofing scripts.

    Usage:
        spoofer = FullFingerprintSpoofer(profile)
        await spoofer.apply_to_context(context)          # inject to browser context
        result = await spoofer.verify_spoof(page)        # verify at bot.sannysoft.com
    """

    def __init__(self, profile: BrowserProfile):
        self.profile = profile

    # ── 5.1 Canvas V2 ───────────────────────────────────────────────────────

    @staticmethod
    def _generate_noise_function(seed: int) -> str:
        """Generate a seeded LCG noise PRNG as an inlinable JS function definition."""
        return f"""
        function ironcoreSeededNoise(index, salt) {{
            let state = ({seed} ^ (salt * 374761393) ^ (index * 668265263)) >>> 0;
            state = Math.imul(state ^ (state >>> 13), 1274126177) >>> 0;
            state = Math.imul(state ^ (state >>> 16), 2246822519) >>> 0;
            return ((state >>> 0) / 4294967295) * 2 - 1;
        }}
        """

    @classmethod
    def generate_canvas_script(cls, profile: BrowserProfile) -> str:
        return f"""
        (() => {{
            {cls._generate_noise_function(profile.canvas_noise_seed)}
            const originalGetImageData = CanvasRenderingContext2D.prototype.getImageData;
            const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
            const originalToBlob = HTMLCanvasElement.prototype.toBlob;

            function cloneImageData(source) {{
                return new ImageData(
                    new Uint8ClampedArray(source.data), source.width, source.height
                );
            }}

            function applyImageNoise(imageData, salt) {{
                for (let i = 0; i < imageData.data.length; i += 4) {{
                    const px = i / 4;
                    for (let ch = 0; ch < 3; ch++) {{
                        const delta = ironcoreSeededNoise(px + ch, salt);
                        const jitter = delta >= 0 ? 1 : -1;
                        const idx = i + ch;
                        imageData.data[idx] = Math.min(255, Math.max(0, imageData.data[idx] + jitter));
                    }}
                }}
                return imageData;
            }}

            CanvasRenderingContext2D.prototype.getImageData = function(...args) {{
                const original = originalGetImageData.apply(this, args);
                const salt = (((args[0]||0)*31)^((args[1]||0)*37)^((args[2]||0)*41)^((args[3]||0)*43))>>>0;
                return applyImageNoise(cloneImageData(original), salt);
            }};

            function withNoisyCanvas(canvas, callback) {{
                const context = canvas.getContext('2d', {{willReadFrequently: true}});
                if (!context || !canvas.width || !canvas.height) return callback();
                let orig;
                try {{ orig = originalGetImageData.call(context, 0, 0, canvas.width, canvas.height); }}
                catch (_) {{ return callback(); }}
                try {{
                    const noisy = applyImageNoise(cloneImageData(orig), (canvas.width*53+canvas.height*59)>>>0);
                    context.putImageData(noisy, 0, 0);
                    return callback();
                }} finally {{
                    context.putImageData(orig, 0, 0);
                }}
            }}

            HTMLCanvasElement.prototype.toDataURL = function(...args) {{
                return withNoisyCanvas(this, () => originalToDataURL.apply(this, args));
            }};
            HTMLCanvasElement.prototype.toBlob = function(...args) {{
                return withNoisyCanvas(this, () => originalToBlob.apply(this, args));
            }};
        }})();
        """

    # ── 5.2 WebGL Full ──────────────────────────────────────────────────────

    @classmethod
    def generate_webgl_script(cls, profile: BrowserProfile) -> str:
        vendor = _j(profile.webgl_vendor)
        renderer = _j(profile.webgl_renderer)
        extensions = _j(profile.webgl_extensions)
        return f"""
        (() => {{
            const spoofedVendor = {vendor};
            const spoofedRenderer = {renderer};
            const spoofedExtensions = {extensions};
            const UNMASKED_VENDOR = 37445, UNMASKED_RENDERER = 37446;
            const VENDOR = 7936, RENDERER = 7937, VERSION = 7938;

            function patchContext(proto) {{
                if (!proto || !proto.getParameter) return;
                const origGetParam = proto.getParameter;
                const origGetExt = proto.getExtension;
                const origGetSuppExt = proto.getSupportedExtensions;

                proto.getParameter = new Proxy(origGetParam, {{
                    apply(target, ctx, args) {{
                        const p = args[0];
                        if (p === UNMASKED_VENDOR || p === VENDOR) return spoofedVendor;
                        if (p === UNMASKED_RENDERER || p === RENDERER) return spoofedRenderer;
                        if (p === VERSION) return 'WebGL 1.0 (OpenGL ES 2.0 Chromium)';
                        return Reflect.apply(target, ctx, args);
                    }}
                }});
                proto.getSupportedExtensions = new Proxy(origGetSuppExt, {{
                    apply() {{ return spoofedExtensions.slice(); }}
                }});
                proto.getExtension = new Proxy(origGetExt, {{
                    apply(target, ctx, args) {{
                        if (!spoofedExtensions.includes(args[0])) return null;
                        return Reflect.apply(target, ctx, args);
                    }}
                }});
            }}

            patchContext(globalThis.WebGLRenderingContext && WebGLRenderingContext.prototype);
            patchContext(globalThis.WebGL2RenderingContext && WebGL2RenderingContext.prototype);
        }})();
        """

    # ── 5.3 Audio Fingerprint ───────────────────────────────────────────────

    @classmethod
    def generate_audio_script(cls, profile: BrowserProfile) -> str:
        seed = profile.canvas_noise_seed + 17
        return f"""
        (() => {{
            {cls._generate_noise_function(seed)}
            const touchedArrays = new WeakSet();
            const origGetChannelData = AudioBuffer.prototype.getChannelData;
            AudioBuffer.prototype.getChannelData = function(channel) {{
                const array = origGetChannelData.call(this, channel);
                if (!touchedArrays.has(array)) {{
                    for (let i = 0; i < array.length; i++) {{
                        array[i] += ironcoreSeededNoise(i, channel + 97) * 1e-7;
                    }}
                    touchedArrays.add(array);
                }}
                return array;
            }};
        }})();
        """

    # ── 5.4 Battery API ─────────────────────────────────────────────────────

    @classmethod
    def generate_battery_script(cls, profile: BrowserProfile) -> str:
        payload = {
            "charging": profile.battery_charging,
            "chargingTime": profile.battery_charging_time,
            "dischargingTime": profile.battery_discharging_time,
            "level": round(profile.battery_level, 4),
        }
        return f"""
        (() => {{
            const batteryState = {json.dumps(payload, allow_nan=True)};
            Object.defineProperty(navigator, 'getBattery', {{
                configurable: true,
                get: () => async () => ({{
                    ...batteryState,
                    addEventListener: () => undefined,
                    removeEventListener: () => undefined,
                    dispatchEvent: () => false,
                    onchargingchange: null, onchargingtimechange: null,
                    ondischargingtimechange: null, onlevelchange: null,
                }}),
            }});
        }})();
        """

    # ── 5.5 GPU / WebGPU ────────────────────────────────────────────────────

    @staticmethod
    def generate_gpu_script(profile: BrowserProfile) -> str:
        """Spoof navigator.gpu WebGPU adapter to match WebGL vendor/renderer."""
        vendor = profile.webgl_vendor
        renderer = profile.webgl_renderer
        clean_vendor = vendor.replace("Google Inc. (", "").rstrip(")").lower()
        clean_device = renderer.split(" Direct3D11")[0].replace("ANGLE (", "").strip()
        arch = ("ampere" if "RTX" in renderer else
                "rdna2" if "RX 6" in renderer else
                "apple-m1" if "M1" in renderer else
                "apple-m2" if "M2" in renderer else "gen12lp")
        return f"""
        (() => {{
            if (!navigator.gpu) return;
            const _orig = navigator.gpu.requestAdapter.bind(navigator.gpu);
            navigator.gpu.requestAdapter = async function(options) {{
                const adapter = await _orig(options);
                if (!adapter) return null;
                const _origInfo = adapter.requestAdapterInfo.bind(adapter);
                adapter.requestAdapterInfo = async function() {{
                    return {{
                        vendor: {_j(clean_vendor)},
                        architecture: {_j(arch)},
                        device: {_j(clean_device)},
                        description: {_j(renderer)},
                    }};
                }};
                return adapter;
            }};
        }})();
        """

    # ── 5.6 Font Enumeration Defense ────────────────────────────────────────

    @staticmethod
    def generate_font_defense_script(profile: BrowserProfile) -> str:
        """Whitelist allowed fonts — block JS font enumeration attacks."""
        allowed = profile.fonts if profile.fonts else []
        return f"""
        (() => {{
            const _allowed = new Set({_j(allowed)});
            if (document.fonts && document.fonts.check) {{
                const _orig = document.fonts.check.bind(document.fonts);
                document.fonts.check = function(font, text) {{
                    const m = font.match(/["']([^"']+)["']/);
                    if (m && !_allowed.has(m[1].trim())) return false;
                    return _orig(font, text);
                }};
            }}
        }})();
        """

    # ── 5.7 Navigator properties ────────────────────────────────────────────

    @staticmethod
    def generate_navigator_script(profile: BrowserProfile) -> str:
        primary = profile.locale.split("-")[0]
        return f"""
        (() => {{
            Object.defineProperty(navigator, 'webdriver', {{ configurable: true, get: () => undefined }});
            Object.defineProperty(navigator, 'languages', {{ configurable: true, get: () => [{_j(profile.locale)}, {_j(primary)}] }});
            Object.defineProperty(navigator, 'language',  {{ configurable: true, get: () => {_j(profile.locale)} }});
            Object.defineProperty(navigator, 'platform',  {{ configurable: true, get: () => {_j(profile.platform)} }});
            Object.defineProperty(navigator, 'hardwareConcurrency', {{ configurable: true, get: () => {profile.hardware_concurrency} }});
            Object.defineProperty(navigator, 'deviceMemory', {{ configurable: true, get: () => {profile.device_memory} }});
        }})();
        """

    # ── Plugins ─────────────────────────────────────────────────────────────

    @staticmethod
    def generate_plugins_script(profile: BrowserProfile) -> str:
        plugins = [
            {"name": p, "description": "", "filename": p.lower().replace(" ", "-") + ".dll", "length": 1}
            for p in profile.plugins
        ]
        return f"""
        (() => {{
            Object.defineProperty(navigator, 'plugins', {{ configurable: true, get: () => {_j(plugins)} }});
            Object.defineProperty(navigator, 'mimeTypes', {{ configurable: true, get: () => [] }});
        }})();
        """

    # ── Screen ──────────────────────────────────────────────────────────────

    @staticmethod
    def generate_screen_script(profile: BrowserProfile) -> str:
        w, h = profile.viewport
        return f"""
        (() => {{
            Object.defineProperty(window.screen, 'width',       {{ configurable: true, get: () => {w} }});
            Object.defineProperty(window.screen, 'height',      {{ configurable: true, get: () => {h} }});
            Object.defineProperty(window.screen, 'availWidth',  {{ configurable: true, get: () => {w} }});
            Object.defineProperty(window.screen, 'availHeight', {{ configurable: true, get: () => {max(h - 40, 0)} }});
        }})();
        """

    # ── Timezone ────────────────────────────────────────────────────────────

    @staticmethod
    def generate_timezone_script(profile: BrowserProfile) -> str:
        return f"""
        (() => {{
            const OrigDTF = Intl.DateTimeFormat;
            Intl.DateTimeFormat = function(locales, options) {{
                const opts = options ? {{...options}} : {{}};
                opts.timeZone = opts.timeZone || {_j(profile.timezone)};
                return new OrigDTF(locales, opts);
            }};
            Intl.DateTimeFormat.prototype = OrigDTF.prototype;
        }})();
        """

    # ── WebRTC ──────────────────────────────────────────────────────────────

    @staticmethod
    def generate_webrtc_script() -> str:
        return """
        (() => {
            Object.defineProperty(navigator, 'mediaDevices', {
                configurable: true,
                value: {
                    getUserMedia: () => Promise.reject(new Error('Requested device not found')),
                    enumerateDevices: async () => [],
                },
            });
            Object.defineProperty(window, 'RTCPeerConnection', {
                configurable: true,
                value: function() { throw new Error('RTCPeerConnection is disabled by policy'); },
            });
        })();
        """

    # ── Misc: Connection / DNT / window.chrome / Permissions ────────────────

    @staticmethod
    def generate_misc_script() -> str:
        return """
        (() => {
            /* Connection API */
            try {
                if ('connection' in navigator) {
                    Object.defineProperty(navigator, 'connection', {
                        get: () => ({ downlink: 10, downlinkMax: Infinity, effectiveType: '4g',
                                      rtt: 50, saveData: false, type: 'wifi',
                                      addEventListener: () => {}, removeEventListener: () => {},
                                      dispatchEvent: () => true, onchange: null }),
                        configurable: true,
                    });
                }
            } catch(e) {}

            /* Do Not Track */
            try { Object.defineProperty(navigator, 'doNotTrack', { get: () => '1', configurable: true }); } catch(e) {}

            /* window.chrome presence */
            if (!window.chrome) {
                window.chrome = {
                    app: { isInstalled: false }, csi: () => {}, loadTimes: () => {},
                    runtime: { connect: () => {}, sendMessage: () => {}, OnInstalledReason: {}, PlatformOs: {} },
                    webstore: { onInstallStageChanged: {}, onDownloadProgress: {} },
                };
            }

            /* Permissions API */
            if (navigator.permissions && navigator.permissions.query) {
                const _orig = navigator.permissions.query.bind(navigator.permissions);
                const _priv = ['camera','microphone','notifications','geolocation','push','midi'];
                navigator.permissions.query = function(d) {
                    if (_priv.includes(d && d.name)) {
                        return Promise.resolve({ state: 'prompt', name: d.name, onchange: null,
                            addEventListener: () => {}, removeEventListener: () => {} });
                    }
                    return _orig(d);
                };
            }
        })();
        """

    # ── generate_all_scripts ─────────────────────────────────────────────────

    @classmethod
    def generate_all_scripts(cls, profile: BrowserProfile) -> List[str]:
        """
        Return the complete list of 11-12 fingerprint spoof scripts.
        Phase 5 coverage: Canvas V2, WebGL, Audio, Battery, GPU, Font,
        Navigator, Plugins, Screen, Timezone, Misc, [WebRTC].
        """
        scripts = [
            cls.generate_navigator_script(profile),     # webdriver, language, platform, hw, mem
            cls.generate_canvas_script(profile),        # toDataURL + getImageData LCG noise
            cls.generate_webgl_script(profile),         # vendor/renderer/extensions GL1+GL2
            cls.generate_audio_script(profile),         # AudioBuffer channel data ±1e-7 noise
            cls.generate_battery_script(profile),       # getBattery() stable spoofed values
            cls.generate_gpu_script(profile),           # WebGPU navigator.gpu adapter info
            cls.generate_font_defense_script(profile),  # font enumeration whitelist
            cls.generate_screen_script(profile),        # screen.width/height dimensions
            cls.generate_timezone_script(profile),      # Intl.DateTimeFormat timezone
            cls.generate_plugins_script(profile),       # navigator.plugins list
            cls.generate_misc_script(),                 # connection/DNT/chrome/permissions
        ]
        if profile.webrtc_disabled:
            scripts.append(cls.generate_webrtc_script())
        logger.info("[Ghost/FingerprintSpoofer] Generated %d scripts for profile='%s'",
                    len(scripts), profile.profile_id)
        return scripts

    async def apply_to_context(self, context: BrowserContext) -> None:
        """Inject all spoof scripts into browser context via add_init_script()."""
        scripts = self.generate_all_scripts(self.profile)
        for script in scripts:
            await context.add_init_script(script)
        logger.info("[Ghost/FingerprintSpoofer] Applied %d scripts to context profile='%s'",
                    len(scripts), self.profile.profile_id)

    async def verify_spoof(
        self,
        page: Page,
        test_url: str = "https://bot.sannysoft.com/",
    ) -> FingerprintVerificationResult:
        """Navigate to fingerprint test site and verify all spoofs are active."""
        errors: List[str] = []
        try:
            await page.goto(test_url, wait_until="domcontentloaded")
        except Exception as exc:
            errors.append(f"navigation_failed: {exc}")

        observed = await page.evaluate(
            """
            async (p) => {
                const canvas = document.createElement('canvas');
                canvas.width = 8; canvas.height = 8;
                const ctx = canvas.getContext('2d');
                ctx.fillStyle = 'rgb(120,121,122)';
                ctx.fillRect(0, 0, 8, 8);
                const pixel = Array.from(ctx.getImageData(0,0,1,1).data.slice(0,3));
                const webgl = document.createElement('canvas').getContext('webgl');
                const battery = navigator.getBattery ? await navigator.getBattery() : null;
                const ab = new AudioBuffer({length: 32, sampleRate: 44100});
                const audioSample = ab.getChannelData(0)[0];
                return {
                    webdriverUndefined: navigator.webdriver === undefined,
                    languages: navigator.languages,
                    platform: navigator.platform,
                    hardwareConcurrency: navigator.hardwareConcurrency,
                    deviceMemory: navigator.deviceMemory,
                    canvasPixel: pixel,
                    webglVendor: webgl ? webgl.getParameter(37445) : null,
                    webglRenderer: webgl ? webgl.getParameter(37446) : null,
                    webglExtensions: webgl ? webgl.getSupportedExtensions() : [],
                    battery, audioSample,
                };
            }
            """,
            None,
        )

        checks = {
            "webdriver": bool(observed["webdriverUndefined"]),
            "languages": bool(observed["languages"]) and observed["languages"][0] == self.profile.locale,
            "platform": observed["platform"] == self.profile.platform,
            "hardware": observed["hardwareConcurrency"] == self.profile.hardware_concurrency,
            "device_memory": observed["deviceMemory"] == self.profile.device_memory,
            "canvas_noise": observed["canvasPixel"] != [120, 121, 122],
            "webgl_vendor": observed["webglVendor"] == self.profile.webgl_vendor,
            "webgl_renderer": observed["webglRenderer"] == self.profile.webgl_renderer,
            "webgl_extensions": set(observed.get("webglExtensions", [])).issubset(
                set(self.profile.webgl_extensions)
            ),
            "battery": bool(observed.get("battery")) and \
                       observed["battery"].get("level") == round(self.profile.battery_level, 4),
            "audio": abs(observed["audioSample"]) > 0,
        }
        success = all(checks.values()) and not errors
        if not success and not errors:
            errors.append("one_or_more_checks_failed")

        failed = [k for k, v in checks.items() if not v]
        logger.info("[Ghost/FingerprintSpoofer] verify_spoof done: success=%s failed=%s",
                    success, failed or "none")
        return FingerprintVerificationResult(
            success=success, url=page.url,
            checks=checks, observed=observed, errors=errors,
        )


# ─── DeviceFingerprint library ────────────────────────────────────────────────

@dataclass
class DeviceFingerprint:
    """
    A realistic device fingerprint bundle — maps to BrowserProfile.
    Sources: real devices captured via bot.sannysoft.com + creepjs.
    """
    name: str
    user_agent: str
    platform: str
    webgl_vendor: str
    webgl_renderer: str
    viewport: Tuple[int, int]
    timezone: str
    locale: str
    hardware_concurrency: int
    device_memory: int
    battery_level: float = 0.93
    fonts: List[str] = dc_field(default_factory=list)
    plugins: List[str] = dc_field(
        default_factory=lambda: ["Chrome PDF Plugin", "Chrome PDF Viewer"]
    )

    def to_browser_profile(self, profile_id: str, canvas_noise_seed: int) -> BrowserProfile:
        """Convert to a fully initialized BrowserProfile."""
        return BrowserProfile(
            profile_id=profile_id,
            name=self.name,
            user_agent=self.user_agent,
            viewport=self.viewport,
            locale=self.locale,
            timezone=self.timezone,
            platform=self.platform,
            webgl_vendor=self.webgl_vendor,
            webgl_renderer=self.webgl_renderer,
            canvas_noise_seed=canvas_noise_seed,
            battery_level=self.battery_level,
            fonts=self.fonts if self.fonts else [
                "Arial", "Calibri", "Cambria", "Comic Sans MS", "Consolas",
                "Courier New", "Georgia", "Impact", "Segoe UI",
                "Times New Roman", "Trebuchet MS", "Verdana",
            ],
            plugins=self.plugins,
            hardware_concurrency=self.hardware_concurrency,
            device_memory=self.device_memory,
        )


DEVICE_FINGERPRINT_LIBRARY: List[DeviceFingerprint] = [
    DeviceFingerprint(
        name="Win10 Chrome121 RTX3080 / New York",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        platform="Win32",
        webgl_vendor="Google Inc. (NVIDIA)",
        webgl_renderer="ANGLE (NVIDIA, NVIDIA GeForce RTX 3080 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        viewport=(1920, 1080), timezone="America/New_York",
        locale="en-US", hardware_concurrency=16, device_memory=16, battery_level=0.95,
    ),
    DeviceFingerprint(
        name="Win11 Chrome121 IntelUHD770 / Chicago",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        platform="Win32",
        webgl_vendor="Google Inc. (Intel)",
        webgl_renderer="ANGLE (Intel, Intel(R) UHD Graphics 770 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        viewport=(2560, 1440), timezone="America/Chicago",
        locale="en-US", hardware_concurrency=12, device_memory=8, battery_level=0.88,
    ),
    DeviceFingerprint(
        name="macOS Monterey Chrome121 AppleM1 / Los Angeles",
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        platform="MacIntel",
        webgl_vendor="Google Inc. (Apple)",
        webgl_renderer="ANGLE (Apple, ANGLE Metal Renderer: Apple M1, Unspecified Version)",
        viewport=(1440, 900), timezone="America/Los_Angeles",
        locale="en-US", hardware_concurrency=8, device_memory=8, battery_level=0.91,
    ),
    DeviceFingerprint(
        name="Win10 Chrome120 AMD_RX6700 / London",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        platform="Win32",
        webgl_vendor="Google Inc. (AMD)",
        webgl_renderer="ANGLE (AMD, AMD Radeon RX 6700 (0x73DF) Direct3D11 vs_5_0 ps_5_0, D3D11)",
        viewport=(1920, 1080), timezone="Europe/London",
        locale="en-GB", hardware_concurrency=12, device_memory=16, battery_level=0.87,
    ),
    DeviceFingerprint(
        name="macOS Ventura Chrome121 AppleM2Pro / Tokyo",
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        platform="MacIntel",
        webgl_vendor="Google Inc. (Apple)",
        webgl_renderer="ANGLE (Apple, ANGLE Metal Renderer: Apple M2 Pro, Unspecified Version)",
        viewport=(1512, 982), timezone="Asia/Tokyo",
        locale="ja-JP", hardware_concurrency=12, device_memory=16, battery_level=0.99,
    ),
    DeviceFingerprint(
        name="Win10 Chrome121 GTX1660SUPER / Singapore",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        platform="Win32",
        webgl_vendor="Google Inc. (NVIDIA)",
        webgl_renderer="ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 SUPER Direct3D11 vs_5_0 ps_5_0, D3D11)",
        viewport=(1920, 1080), timezone="Asia/Singapore",
        locale="en-SG", hardware_concurrency=6, device_memory=8, battery_level=0.93,
    ),
]


def get_device_fingerprint(seed: int) -> DeviceFingerprint:
    """Pick a deterministic device fingerprint from library via seed."""
    return DEVICE_FINGERPRINT_LIBRARY[seed % len(DEVICE_FINGERPRINT_LIBRARY)]


def get_random_browser_profile(profile_id: str, seed: int) -> BrowserProfile:
    """
    Convenience: return a fully-formed BrowserProfile from the library.
    Useful for ProfilePool.create_fresh_profile() in Phase 6 (Session Manager).
    """
    return get_device_fingerprint(seed).to_browser_profile(
        profile_id=profile_id, canvas_noise_seed=seed
    )
