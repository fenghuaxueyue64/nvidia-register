"""
AI 验证码求解器 — 基于 Agent Tool-Loop 架构的 hCaptcha 自动破解 v2。

架构 (参考 agent-doc.md & computer-use-guide.md):
  Observe(截屏) → Think(AI分析+工具选择) → Act(执行工具) → Verify(检查) → Loop

与 AstrBot Tool-Loop 对应:
  ToolLoopAgentRunner.step()  →  AgentCaptchaSolver._agent_loop()
  FunctionTool + ToolSet      →  CAPTCHA_TOOLS (工具定义 JSON Schema)
  FunctionToolExecutor        →  _execute_tool()
  LLMResponse                 →  AgentDecision (解析 AI 输出的工具调用)

v2 改进:
  - 全页+验证码区域双截图策略，AI 有完整上下文
  - 多级验证支持：网格→滑块→文字等多轮挑战自动处理
  - 像素坐标系：AI 返回截图内像素坐标，自动转换
  - _check_passed() 检测绿色勾号，不依赖页面跳转
  - 自动点击表单提交按钮
  - report_done 最多重试3次防止死循环
  - 支持通用点击、按键、等待等完整工具集

支持的验证码类型:
  - 图片选择 / 分类筛选 (3x3, 4x4, 5x4 网格)
  - 滑块拖动 (拼图/缺口)
  - 文字输入
  - 点击序列 / 旋转 / BBOX 框选 (通用 click_at 覆盖)
  所有类型均由 AI Agent 自主判断并调用对应工具
"""

import asyncio
import base64
import io
import json
import math
import random
import re
import time
from typing import Optional

import requests
from PIL import Image, ImageDraw, ImageFont

from core.llm_client import LLMClient

# ============================================================================
# 常量
# ============================================================================

HCAPTCHA_CHECKBOX_VP = (0.353, 0.773)
MAX_AGENT_STEPS = 30       # 最大步数（多级验证需要更多步数）
_MAX_ATTEMPTS = 3          # 最大重试次数
_MAX_REPORT_DONE_RETRIES = 3  # 连续report_done最大次数

# ============================================================================
# HumanMouse — 拟人化鼠标操作
# ============================================================================

class HumanMouse:
    """拟人化鼠标操作封装。
    
    所有鼠标操作均模拟真实人类:
      - 贝塞尔曲线移动（非直线瞬移）
      - 按下→抬起间随机延迟 (80-200ms)
      - 点击位置微小随机偏移 (±3px)
      - 操作间随机微停顿 (50-150ms)
      - 拖动速度不均匀（先慢后快中间慢）
    """

    def __init__(self, page):
        self.page = page
        self._last_pos = None  # 上次鼠标位置，用于连续操作时衔接

    # ---- 核心：贝塞尔曲线移动 ----

    async def move_to(self, x: int, y: int, duration_ms: int = None):
        """贝塞尔曲线移动鼠标到目标位置。
        
        实际路径 = 直线 + 随机控制点偏移，模拟人类手腕运动轨迹。
        duration_ms: 移动耗时(ms)，None则根据距离自动计算(150-500ms)。
        """
        page = self.page
        # 获取当前位置
        if self._last_pos:
            start_x, start_y = self._last_pos
        else:
            try:
                pos = await page.evaluate(
                    "() => ({x: window.mouseX || 0, y: window.mouseY || 0})"
                )
                start_x, start_y = pos.get("x", 0), pos.get("y", 0)
            except Exception:
                start_x, start_y = x - 100, y - 100

        # 距离计算
        dist = math.sqrt((x - start_x) ** 2 + (y - start_y) ** 2)

        # 自动确定时长
        if duration_ms is None:
            if dist < 20:
                duration_ms = random.randint(80, 150)
            elif dist < 100:
                duration_ms = random.randint(120, 250)
            elif dist < 300:
                duration_ms = random.randint(180, 350)
            else:
                duration_ms = random.randint(250, 500)

        # 如果距离很短(<5px)，直接移动
        if dist < 5:
            await page.mouse.move(x, y)
            self._last_pos = (x, y)
            return

        # 贝塞尔控制点：在连线两侧随机偏移制造弧线
        mid_x = (start_x + x) / 2
        mid_y = (start_y + y) / 2
        # 控制点偏移量：距离的 15-30%，垂直方向
        offset = dist * random.uniform(0.12, 0.28)
        angle = math.atan2(y - start_y, x - start_x) + random.uniform(-1.2, 1.2)
        cp_x = mid_x + offset * math.cos(angle + math.pi / 2)
        cp_y = mid_y + offset * math.sin(angle + math.pi / 2)

        # 步数：基于时长，每10-15ms一步
        steps = max(10, duration_ms // random.randint(10, 15))
        step_delay = duration_ms / 1000 / steps

        for i in range(1, steps + 1):
            t = i / steps
            # 二次贝塞尔: B(t) = (1-t)²P0 + 2(1-t)t P1 + t²P2
            bx = (1 - t) ** 2 * start_x + 2 * (1 - t) * t * cp_x + t ** 2 * x
            by = (1 - t) ** 2 * start_y + 2 * (1 - t) * t * cp_y + t ** 2 * y
            # 微小抖动
            bx += random.uniform(-0.5, 0.5)
            by += random.uniform(-0.5, 0.5)
            await page.mouse.move(int(bx), int(by))
            # 人类移动不是匀速的：开始慢→中间快→末尾慢
            if i < steps * 0.2:
                await asyncio.sleep(step_delay * random.uniform(1.1, 1.5))
            elif i > steps * 0.8:
                await asyncio.sleep(step_delay * random.uniform(1.0, 1.4))
            else:
                await asyncio.sleep(step_delay * random.uniform(0.7, 1.0))

        self._last_pos = (x, y)

    # ---- 拟人化点击 ----

    async def click(self, x: int, y: int):
        """移动到目标位置后拟人化点击。
        
        行为:
          1. 贝塞尔曲线移动到目标(带±3px随机偏移)
          2. 短暂犹豫 (80-200ms)
          3. 鼠标按下
          4. 按下保持 (50-150ms, 模拟手指按压时间)
          5. 鼠标抬起
          6. 操作后停顿 (100-250ms)
        """
        # 目标位置加微小随机偏移，模拟人类无法精确点到像素
        ox = x + random.randint(-3, 3)
        oy = y + random.randint(-3, 3)

        # 1. 移动到目标
        await self.move_to(ox, oy)

        # 2. 到达后短暂停顿（人类需要确认位置）
        await self._human_pause(60, 180)

        # 3. 按下
        await self.page.mouse.down()

        # 4. 按下保持（手指按压时间）
        await self._human_pause(50, 150)

        # 5. 抬起
        await self.page.mouse.up()

        # 6. 点击后停顿
        await self._human_pause(80, 200)

    # ---- 拟人化拖动 ----

    async def drag(self, start_x: int, start_y: int, end_x: int, end_y: int):
        """拟人化拖动滑块。
        
        流程:
          1. 移动到起点
          2. 暂停确认
          3. 按下
          4. 沿贝塞尔曲线拖动到终点（速度不均匀，带抖动，模拟紧张/犹豫）
          5. 抬起
        """
        # 1. 移动到起点
        await self.move_to(start_x, start_y)
        await self._human_pause(100, 250)

        # 2. 按下
        await self.page.mouse.down()
        await self._human_pause(30, 80)

        # 3. 拖动 — 非匀速贝塞尔曲线
        dist = math.sqrt((end_x - start_x) ** 2 + (end_y - start_y) ** 2)
        # 拖动比普通移动慢一些
        duration_ms = random.randint(400, 900) if dist > 200 else random.randint(250, 500)

        # 控制点：轻微偏移
        mid_x = (start_x + end_x) / 2
        mid_y = (start_y + end_y) / 2
        offset = dist * random.uniform(0.03, 0.08)
        angle = random.uniform(0, math.pi * 2)
        cp_x = mid_x + offset * math.cos(angle)
        cp_y = mid_y + offset * math.sin(angle)

        steps = max(12, duration_ms // 15)
        step_delay = duration_ms / 1000 / steps

        for i in range(1, steps + 1):
            t = i / steps
            # 模拟人类拖动速度变化：开始犹豫→加速→减速→末尾精准对准
            if t < 0.15:
                # 开始阶段：还在观察，缓慢移动
                eased_t = t * t * 3  # Ease-in
            elif t > 0.85:
                # 末尾阶段：精准对准，减速
                eased_t = 1 - (1 - t) ** 3  # Ease-out
            else:
                eased_t = t

            # 贝塞尔插值
            bx = (1 - eased_t) ** 2 * start_x + 2 * (1 - eased_t) * eased_t * cp_x + eased_t ** 2 * end_x
            by = (1 - eased_t) ** 2 * start_y + 2 * (1 - eased_t) * eased_t * cp_y + eased_t ** 2 * end_y

            # 抖动：人类拖动滑块时手会微微抖动
            jitter_x = random.uniform(-2, 2)
            jitter_y = random.uniform(-2, 2)
            # 偶尔"手滑"一下
            if random.random() < 0.08:
                jitter_x += random.uniform(-3, 3)
                jitter_y += random.uniform(-3, 3)

            await self.page.mouse.move(int(bx + jitter_x), int(by + jitter_y))

            # 变速延迟
            if t < 0.1:
                await asyncio.sleep(step_delay * random.uniform(1.3, 1.8))
            elif t > 0.85:
                await asyncio.sleep(step_delay * random.uniform(0.8, 1.2))
            else:
                await asyncio.sleep(step_delay * random.uniform(0.5, 0.8))

        # 到达终点后短暂保持
        await self.page.mouse.move(end_x, end_y)
        await self._human_pause(50, 120)

        # 4. 抬起
        await self.page.mouse.up()
        await self._human_pause(80, 200)

        self._last_pos = (end_x, end_y)

    # ---- 工具函数 ----

    async def _human_pause(self, min_ms: int, max_ms: int):
        """随机微停顿，模拟人类操作间隔."""
        await asyncio.sleep(random.randint(min_ms, max_ms) / 1000)

# ============================================================================
# 工具定义 — 符合 FunctionTool 规范的 JSON Schema
# ============================================================================

CAPTCHA_TOOLS = [
    {
        "name": "click_grid_cells",
        "description": (
            "Click specific cells in the captcha image grid. "
            "Cells are numbered [row, col] starting from top-left [0,0]. "
            "For a 3x3 grid, valid rows/cols are 0-2. For 4x4, 0-3. For 5x4, 0-4 rows, 0-3 cols."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "cells": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": [{"type": "integer"}, {"type": "integer"}],
                        "minItems": 2,
                        "maxItems": 2,
                    },
                    "description": "List of [row, col] cells to click. Example: [[0,1],[1,2],[2,0]]",
                },
                "reason": {
                    "type": "string",
                    "description": "What objects you see in these cells that match the target instruction",
                },
            },
            "required": ["cells"],
        },
    },
    {
        "name": "click_at",
        "description": (
            "Click at specific LEFT full-page absolute PIXEL coordinates in the browser viewport. "
            "Coordinate (0, 0) is the TOP-LEFT corner of the full-page viewport. "
            "Use the RIGHT zoom crop for detail only; do not copy coordinates from the RIGHT zoom image. "
            "Use this for: buttons, individual elements, refresh arrows, audio icons, "
            "and any click target that is NOT part of a regular image grid."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X pixel coordinate (from left edge of screenshot)"},
                "y": {"type": "integer", "description": "Y pixel coordinate (from top edge of screenshot)"},
                "reason": {"type": "string", "description": "What element you are clicking at these coordinates"},
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "drag_from_to",
        "description": (
            "Drag the mouse from start to end LEFT full-page absolute PIXEL coordinates in the full-page viewport. "
            "Use the RIGHT zoom crop for detail only; do not copy coordinates from the RIGHT zoom image. "
            "Use this for slider puzzles and drag-to-verify challenges. "
            "The drag simulates human-like movement with slight jitter."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "start_x": {"type": "integer", "description": "Start X pixel coordinate"},
                "start_y": {"type": "integer", "description": "Start Y pixel coordinate"},
                "end_x": {"type": "integer", "description": "End X pixel coordinate"},
                "end_y": {"type": "integer", "description": "End Y pixel coordinate"},
                "reason": {"type": "string", "description": "What you see: slider position, target gap position, distance to drag"},
            },
            "required": ["start_x", "start_y", "end_x", "end_y"],
        },
    },
    {
        "name": "type_text",
        "description": "Type text into a captcha text input field (e.g., distorted text challenge, audio fallback).",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The exact text to type (case-sensitive)"},
                "reason": {"type": "string", "description": "What characters/words you see in the challenge"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "press_key",
        "description": (
            "Press a keyboard key. Use 'Enter' to submit after selecting cells, "
            "'Tab' to navigate between fields, 'Escape' to dismiss dialogs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "enum": ["Enter", "Tab", "Escape", "Space", "Backspace", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"],
                    "description": "Key to press",
                },
                "reason": {"type": "string", "description": "Why you are pressing this key"},
            },
            "required": ["key"],
        },
    },
    {
        "name": "wait",
        "description": (
            "Wait for N seconds and request a new screenshot. "
            "Use when: images are loading, spinner is visible, page is transitioning, "
            "or you need to observe the result of a previous action before deciding next step."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "seconds": {"type": "number", "description": "Seconds to wait (1-5 recommended)", "default": 2},
                "reason": {"type": "string", "description": "What you are waiting for"},
            },
        },
    },
    {
        "name": "report_done",
        "description": (
            "Report the ENTIRE captcha flow is COMPLETE. "
            "SINGLE-ROUND: 1 grid/slider → green check → report_done. "
            "DOUBLE-ROUND: grid1 → submit → grid2 appears → solve grid2 → green check → report_done. "
            "NEVER call report_done if there is still an active challenge visible in the RIGHT zoomed image. "
            "Green checkmark on checkbox = truly done. New images = NOT done, keep solving."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "evidence": {
                    "type": "string",
                    "description": (
                        "What specific evidence you see that indicates success. "
                        "Be specific: 'green checkmark visible on checkbox', "
                        "'challenge popup disappeared, see main form', "
                        "'6-digit verification code input fields visible'"
                    ),
                },
            },
            "required": ["evidence"],
        },
    },
]


def _tools_text() -> str:
    """生成工具定义的文本表示（嵌入 System Prompt）。"""
    lines = ["## Available Tools", ""]
    for t in CAPTCHA_TOOLS:
        params = json.dumps(t["parameters"], ensure_ascii=False, indent=2)
        lines.append(f"### {t['name']}")
        lines.append(f"Description: {t['description']}")
        lines.append("Parameters:")
        lines.append("```json")
        lines.append(params)
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


# ============================================================================
# Agent System Prompt — v2 全面优化
# ============================================================================

AGENT_SYSTEM_PROMPT = f"""You are a high-precision hCaptcha visual solver.

The screenshot you receive is a SIDE-BY-SIDE observation:
  LEFT = full page with coordinate grid and a red box around the challenge.
  RIGHT = zoomed challenge crop for detail only. Read the target instruction here first, but DO NOT use RIGHT zoom coordinates for tools.
  ACTION COORDINATES = LEFT full-page absolute browser viewport coordinates only.

## Mandatory High-Precision Protocol

1. READ THE TARGET INSTRUCTION exactly. Identify the object/category/color/action requested.
2. CLASSIFY the challenge: image grid, slider/drag, text input, click target, loading, or already solved.
3. LOCATE the grid geometry before acting: rows, columns, and candidate cells.
4. DECIDE with confidence. Include `"confidence": 0.0-1.0` in every JSON response.
5. ACT with exactly one tool.
6. VERIFY AFTER EVERY ACTION by waiting for the next screenshot. New images mean a multi-round challenge, not success.

## Hard Safety Rules

- DO NOT GUESS. If target instruction, grid cells, or slider endpoint are unclear, call `wait` for a new screenshot.
- Use `click_grid_cells` only when confidence >= 0.72 and you can name the matching evidence.
- Use `drag_from_to` only when confidence >= 0.75 and both handle and gap are visible.
- Use `click_at` only for visible buttons/icons outside a normal grid.
- For click_at and drag_from_to, output coordinates from the LEFT full-page absolute coordinate grid only.
- The RIGHT zoom crop is detail only. Its coordinates are not executable.
- Multi-round hCaptcha is common: grid1 -> submit -> grid2/grid3 -> green check.
- NEVER call report_done while a challenge popup, grid, slider, loading spinner, or new image task is visible.
- report_done requires strong evidence: green checkbox checkmark, popup disappeared, or NVIDIA email-code inputs visible.
- If your answer is uncertain, output wait. A wrong click is worse than waiting.

## Output Format

Output ONLY JSON:
{{"tool":"name","params":{{...}},"confidence":0.0,"thinking":"target instruction, evidence, and why this action is safe"}}

## Tool Selection

For IMAGE GRID:
- Read the target instruction first.
- Select only cells that clearly contain the target.
- Do not click borderline/partial objects unless the instruction explicitly accepts them.
- After grid clicks, the system submits and verifies; wait for the next screenshot.

For SLIDER:
- Estimate the handle center and the gap/target center using LEFT full-page absolute coordinates.
- Drag horizontally unless the challenge visibly requires another direction.

For LOADING/UNCLEAR:
- Use wait with a short reason.

{_tools_text()}"""


# ============================================================================
# Agent Captcha Solver — v3 (LLMClient backend)
# ============================================================================

class AgentCaptchaSolver:
    """
    Agent Tool-Loop 验证码求解器 v3。

    后端: LLMClient (直接调用 Qwen API, 不依赖 QWEN-PHOTO-API)
    默认模型: qwen3.6-flash
    模型回退: 主模型失败 → 自动尝试备用模型列表
    """

    FALLBACK_MODELS = [
        "qwen3.7-plus",
        "qwen3.6-flash-2026-04-16",
        "qwen3.7-plus-2026-05-26",
    ]

    def __init__(self, vision_client=None,
                 api_key: Optional[str] = None, base_url: Optional[str] = None,
                 model: str = "qwen3.6-flash", verbose: bool = True):
        self._vision = None
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._model_index = 0       # 当前使用的模型在回退链中的位置 (-1 = 主模型)
        self._tried_models = []     # 已尝试过的模型
        self.verbose = verbose
        self._stats = {"steps": 0, "tool_calls": 0, "screenshots": 0}
        self._conversation: list[dict] = []
        self._area: dict = {}
        self._full_page_b64: Optional[str] = None
        self._consecutive_report_done = 0

        if vision_client:
            self._vision = vision_client
            return

        # 优先级: .env配置 > API.txt自动发现
        if api_key and base_url:
            self._vision = LLMClient(api_key=api_key, base_url=base_url, model=model)
            self._log(f"📡 Agent backend: {model} @ {base_url}")
            return

        discovered = LLMClient.discover_api_txt()
        if discovered:
            api_key, base_url = discovered
            self._api_key = api_key
            self._base_url = base_url
            self._vision = LLMClient(api_key=api_key, base_url=base_url, model=model)
            self._log(f"📡 Agent backend: {model} (from API.txt)")
            return

        raise ValueError(
            "No AI backend available. "
            "Set AI_VISION_API_KEY/AI_VISION_API_BASE in .env or place API.txt."
        )

    def _switch_model(self) -> bool:
        """切换到下一个回退模型。返回 True 表示切换成功。"""
        if self._model_index < len(self.FALLBACK_MODELS):
            new_model = self.FALLBACK_MODELS[self._model_index]
            self._model_index += 1
            self._log(f"  🔄 Falling back to model: {new_model}")
            if self._api_key and self._base_url:
                self._vision = LLMClient(
                    api_key=self._api_key,
                    base_url=self._base_url,
                    model=new_model,
                )
                return True
        return False

    # ================================================================
    # 公共入口
    # ================================================================

    async def solve(self, page, max_attempts: int = _MAX_ATTEMPTS) -> bool:
        """求解验证码的公共入口."""
        self._mouse = HumanMouse(page)  # 初始化拟人化鼠标
        self._log(f"\n{'='*50}")
        self._log("🤖 Agent Captcha Solver v2 — Tool-Loop Mode")
        self._log(f"   Backend: {self._model} @ {self._vision.base_url}")
        self._log(f"   Fallback: {self.FALLBACK_MODELS}")
        self._log(f"   Tools: {[t['name'] for t in CAPTCHA_TOOLS]}")
        self._log(f"{'='*50}\n")

        for attempt in range(max_attempts):
            self._conversation = [
                {"role": "system", "content": AGENT_SYSTEM_PROMPT},
            ]
            self._stats = {"steps": 0, "tool_calls": 0, "screenshots": 0}
            self._consecutive_report_done = 0
            self._model_index = 0
            self._tried_models = []
            # 每次尝试重置回主模型
            if attempt > 0 and self._api_key and self._base_url:
                self._vision = LLMClient(api_key=self._api_key, base_url=self._base_url, model=self._model)
            self._log(f"--- Attempt {attempt + 1}/{max_attempts} ---")

            if attempt == 0:
                if not await self._click_checkbox(page):
                    self._log("❌ Cannot click captcha checkbox")
                    continue
                await asyncio.sleep(2)
            else:
                if not await self._refresh_captcha(page):
                    continue
                await asyncio.sleep(2)

            result = await self._agent_loop(page)
            if result:
                self._log(f"\n✅ SOLVED! (attempt {attempt + 1})")
                self._print_stats()
                return True
            self._log("  ❌ Failed, retrying...")

        self._log(f"\n❌ FAILED ({max_attempts} attempts)")
        self._print_stats()
        return False

    # ================================================================
    # Agent Loop — 核心循环 (v2: 增强版)
    # ================================================================

    async def _agent_loop(self, page, max_steps: int = MAX_AGENT_STEPS) -> bool:
        """
        核心 Agent 循环。

        每步流程:
          1. 截取验证码区域截图
          2. 拼接对话上下文发送给 LLM
          3. 解析 AI 返回的工具调用
          4. 执行工具
          5. 追加结果到对话
          6. 检查是否完成
        """
        for step in range(max_steps):
            self._stats["steps"] += 1
            self._log(f"\n[Agent Step {step + 1}/{max_steps}]")

            # ---- 1. OBSERVE: 全屏截图 + 坐标网格 + 红色标记验证码区域 ----
            # 短暂等待让页面稳定，减少闪屏
            await asyncio.sleep(0.1)
            vp = await page.evaluate("()=>({w:window.innerWidth,h:window.innerHeight})")
            vw, vh = vp["w"], vp["h"]

            # 截取全屏
            full_buf = await page.screenshot(type="png")
            # 查找验证码区域位置
            captcha_bounds = await page.evaluate(r"""() => {
    const iframes = document.querySelectorAll('iframe');
    for (const f of iframes) {
        const src = f.src || '';
        if ((src.includes('hcaptcha') || src.includes('challenge')) && f.offsetParent) {
            const r = f.getBoundingClientRect();
            if (r.width > 150 && r.height > 150)
                return {x: r.x, y: r.y, w: r.width, h: r.height, found: true};
        }
    }
    const popups = document.querySelectorAll('div[class*="challenge"],div[class*="task"],div[class*="captcha"],div[class*="modal"],div[class*="popup"],div[class*="dialog"]');
    for (const el of popups) {
        if (!el.offsetParent) continue;
        const r = el.getBoundingClientRect();
        if (r.width > 200 && r.height > 200)
            return {x: r.x, y: r.y, w: r.width, h: r.height, found: true};
    }
    const w = document.querySelector('[data-hcaptcha-widget-id]');
    if (w) { const r = w.getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height, found: true}; }
    return {found: false};
}""")

            # 叠加坐标网格 + 红色标记验证码区域
            dual_b64 = self._compose_dual(full_buf, vw, vh, captcha_bounds)

            # 保存验证码区域信息供工具执行用
            if captcha_bounds.get("found"):
                self._area = {
                    "ox": captcha_bounds["x"], "oy": captcha_bounds["y"],
                    "cw": captcha_bounds["w"], "ch": captcha_bounds["h"],
                    "vw": vw, "vh": vh,
                }
            else:
                self._area = {"ox": 0, "oy": 0, "cw": vw, "ch": vh, "vw": vw, "vh": vh}

            self._stats["screenshots"] += 1

            # ---- 2. THINK: 构建消息送 LLM ----
            if step == 0:
                user_msg = (
                    "Observe carefully. First read the target instruction in the RIGHT crop, "
                    "then identify challenge type, grid size or slider geometry, candidate targets, "
                    "confidence, and exactly one safe tool action. Do not guess."
                )
            else:
                user_msg = (
                    "New screenshot after action. Verify after every action: solved, new multi-round "
                    "task, loading, or still active. Choose exactly one next safe action."
                )

            self._conversation.append({"role": "user", "content": user_msg})

            try:
                response = self._vision.chat(
                    messages=self._conversation,
                    image_b64=dual_b64,
                    max_tokens=2048,
                )
            except Exception as e:
                self._log(f"  ❌ LLM error ({self._vision.model}): {e}")
                self._tried_models.append(self._vision.model)
                if self._switch_model():
                    self._log(f"  🔄 Switched to {self._vision.model}, retrying same step...")
                    self._conversation.pop()  # 移除失败时追加的 user msg
                    continue
                await asyncio.sleep(2)
                continue

            # ---- 3. DECIDE: 解析工具调用 ----
            decision = self._parse_tool_call(response)
            tool_name = decision.get("tool", "")
            params = decision.get("params", {})
            thinking = decision.get("thinking", "")

            if thinking:
                self._log(f"  💭 {thinking[:250]}")
            self._log(f"  🔧 Tool: {tool_name} {json.dumps(params, ensure_ascii=False)[:200]}")

            # ---- 4. ACT: 执行工具 ----
            tool_result = await self._execute_tool(tool_name, params, page)
            self._stats["tool_calls"] += 1

            # ---- 5. FEEDBACK: 追加结果 + 裁剪上下文 ----
            self._conversation.append({"role": "assistant", "content": response})
            self._conversation.append({
                "role": "user",
                "content": f"Tool '{tool_name}' result: {tool_result}",
            })

            # 裁剪对话历史：保留 system + 最近6条消息，避免上下文爆炸
            if len(self._conversation) > 13:  # system + 6*2 messages
                self._conversation = (
                    self._conversation[:1] + self._conversation[-12:]
                )

            # ---- 6. VERIFY: 检查是否完成 ----
            if tool_name == "report_done":
                self._consecutive_report_done += 1
                passed = await self._check_passed(page)

                if passed:
                    self._log("  ✅ Captcha successfully passed!")
                    # 尝试点击表单提交按钮推进页面
                    await self._click_form_submit(page)
                    return True

                if self._consecutive_report_done >= _MAX_REPORT_DONE_RETRIES:
                    # 连续3次report_done，但检测失败 → 可能是hCaptcha勾号已出但页面没刷新
                    # 尝试点击表单提交按钮强制推进
                    self._log("  ⚠️ AI insists captcha is done (3x report_done), trying form submit...")
                    await self._click_form_submit(page)
                    await asyncio.sleep(2)
                    if await self._check_passed(page):
                        return True

                self._log(f"  ⚠️ AI reported done but check failed (x{self._consecutive_report_done}), continuing...")
                # 告诉AI实际还没通过
                self._conversation.append({
                    "role": "user",
                    "content": (
                        "IMPORTANT: The captcha is NOT solved yet. "
                        "The page still shows hCaptcha elements. "
                        "Please look at the new screenshot and try a different approach."
                    ),
                })
                continue
            else:
                # 非report_done工具，重置计数器
                self._consecutive_report_done = 0

            # wait 类工具：等待后直接进入下一轮观察
            if tool_name == "wait":
                continue

            # 执行操作后拟人化等待，让页面反应
            await asyncio.sleep(random.uniform(0.3, 0.7))

            # 检查页面是否已经自动跳过了验证码
            if await self._check_passed(page):
                self._log("  ✅ Page auto-advanced past captcha!")
                return True

        return False

    # ================================================================
    # 工具执行器
    # ================================================================

    async def _execute_tool(self, name: str, params: dict, page) -> str:
        area = getattr(self, '_area', {
            "ox": 0, "oy": 0, "cw": 400, "ch": 400,
            "vw": 1280, "vh": 800,
        })

        if name == "click_grid_cells":
            return await self._exec_click_grid_cells(params, page, area)

        elif name == "click_at":
            return await self._exec_click_at(params, page, area)

        elif name == "drag_from_to":
            return await self._exec_drag(params, page, area)

        elif name == "type_text":
            return await self._exec_type_text(params, page, area)

        elif name == "press_key":
            return await self._exec_press_key(params, page)

        elif name == "wait":
            seconds = params.get("seconds", 2)
            await asyncio.sleep(seconds)
            return f"Waited {seconds}s, ready for new screenshot"

        elif name == "report_done":
            return f"Reported done: {params.get('evidence', 'no evidence')}"

        return f"Unknown tool: {name}"

    async def _exec_click_grid_cells(self, params: dict, page, area: dict) -> str:
        cells = params.get("cells", [])
        if not cells:
            return "Error: no cells specified"

        # 智能检测网格布局
        layout = self._detect_grid_layout(page, len(cells))

        ox, oy = area.get("ox", 0), area.get("oy", 0)
        cw, ch = area.get("cw", 400), area.get("ch", 400)
        rows, cols = layout
        mouse = getattr(self, '_mouse', None)

        clicked = []
        for idx, cell in enumerate(cells):
            r, c = cell[0], cell[1]
            if r >= rows or c >= cols:
                self._log(f"  ⚠️ Cell [{r},{c}] out of range for {rows}x{cols} grid, clamping")
                r, c = min(r, rows - 1), min(c, cols - 1)

            # 网格图片区域通常不等于整个 challenge iframe；先估算内层图片网格。
            cell_center_x, cell_center_y = self._grid_cell_center(
                area, rows=rows, cols=cols, row=r, col=c
            )
            self._log(f"  👆 grid cell [{r},{c}] → pixel ({cell_center_x},{cell_center_y})")

            if mouse:
                await mouse.click(cell_center_x, cell_center_y)
            else:
                await page.mouse.click(cell_center_x, cell_center_y)

            # 多单元格间的人类思考延迟
            if idx < len(cells) - 1:
                delay = random.randint(200, 500) / 1000
                self._log(f"  ⏱  inter-cell delay {delay:.1f}s")
                await asyncio.sleep(delay)

            clicked.append([r, c])

        # 自动提交: 先按 Enter，再用坐标点击挑战底部 Verify/Next 区域。
        self._log("  ⏎ auto-submit after grid (Enter + challenge verify area)")
        await asyncio.sleep(random.uniform(0.15, 0.35))
        await page.keyboard.press("Enter")
        await asyncio.sleep(random.uniform(0.2, 0.4))
        verify_x = int(ox + cw * 0.74)
        verify_y = int(oy + ch * 0.93)
        if mouse:
            await mouse.click(verify_x, verify_y)
        else:
            await page.mouse.click(verify_x, verify_y)
        await asyncio.sleep(random.uniform(0.2, 0.4))
        # 尝试在captcha区域中点击verify/next/submit/continue按钮
        await page.evaluate(r"""() => {
    const btnTexts = ['verify','submit','next','continue','skip','确认','提交','下一步','继续','跳过','验证'];
    const all = document.querySelectorAll('button, div[role="button"], [class*="button"], [class*="submit"], [class*="verify"]');
    for (const el of all) {
        if (!el.offsetParent || el.disabled) continue;
        const t = (el.innerText || el.textContent || '').trim().toLowerCase();
        if (btnTexts.some(k => t.includes(k))) { el.click(); return t; }
    }
    return null;
}""")
        await asyncio.sleep(random.uniform(0.3, 0.6))

        return f"Clicked {len(clicked)} grid cells: {clicked}"

    @staticmethod
    def _grid_cell_center(area: dict, rows: int, cols: int, row: int, col: int) -> tuple[int, int]:
        """Estimate the visual image-grid cell center inside an hCaptcha challenge."""
        ox, oy = area.get("ox", 0), area.get("oy", 0)
        cw, ch = area.get("cw", 400), area.get("ch", 400)

        side = min(cw * 0.92, ch * 0.64)
        grid_w = side
        grid_h = side * rows / max(cols, 1)
        if grid_h > ch * 0.66:
            grid_h = ch * 0.66
            grid_w = grid_h * cols / max(rows, 1)

        grid_x = ox + max((cw - grid_w) / 2, cw * 0.04)
        grid_y = oy + min(max(ch * 0.24, 90), ch * 0.31)
        if grid_y + grid_h > oy + ch * 0.88:
            grid_y = oy + ch * 0.88 - grid_h

        x = int(grid_x + (col + 0.5) * grid_w / max(cols, 1))
        y = int(grid_y + (row + 0.5) * grid_h / max(rows, 1))
        return x, y

    async def _exec_click_at(self, params: dict, page, area: dict) -> str:
        # 全屏坐标系：AI的坐标直接就是绝对屏幕坐标
        x, y = params.get("x", 0), params.get("y", 0)
        ax, ay = int(x), int(y)
        ok, message = self._validate_viewport_point(ax, ay, area, "click")
        if not ok:
            self._log(f"  ⚠️ {message}")
            return message
        mouse = getattr(self, '_mouse', None)
        self._log(f"  👆 click at absolute ({ax},{ay})")
        if mouse:
            await mouse.click(ax, ay)
        else:
            await page.mouse.click(ax, ay)
        return f"Clicked at ({x}, {y})"

    async def _exec_drag(self, params: dict, page, area: dict) -> str:
        # 全屏坐标系：AI的坐标直接就是绝对屏幕坐标
        sx = int(params.get("start_x", 0))
        sy = int(params.get("start_y", 0))
        ex = int(params.get("end_x", 0))
        ey = int(params.get("end_y", 0))

        # 智能默认：如果坐标为空/全零，根据验证码区域自动计算
        if sx == 0 and sy == 0 and ex == 0 and ey == 0:
            ox, oy = area.get("ox", 0), area.get("oy", 0)
            cw, ch = area.get("cw", 400), area.get("ch", 400)
            sx = int(ox + cw * 0.15)
            sy = int(oy + ch * 0.78)
            ex = int(ox + cw * 0.85)
            ey = sy
            self._log(f"  ⚠️ Using auto-computed drag: ({sx},{sy})→({ex},{ey})")

        for label, x, y in (("drag start", sx, sy), ("drag end", ex, ey)):
            ok, message = self._validate_viewport_point(x, y, area, label)
            if not ok:
                self._log(f"  ⚠️ {message}")
                return message

        self._log(f"  🎚 drag ({sx},{sy})→({ex},{ey})")
        mouse = getattr(self, '_mouse', None)
        if mouse:
            await mouse.drag(sx, sy, ex, ey)
        else:
            # Fallback: 简单线性拖动
            await page.mouse.move(sx, sy)
            await page.mouse.down()
            steps = 20
            for i in range(1, steps + 1):
                t = i / steps
                cur_x = int(sx + (ex - sx) * t)
                cur_y = int(sy + (ey - sy) * t)
                await page.mouse.move(cur_x, cur_y)
                await asyncio.sleep(0.015)
            await page.mouse.move(ex, ey)
            await asyncio.sleep(0.1)
            await page.mouse.up()
            await asyncio.sleep(0.3)

        return f"Dragged from ({params.get('start_x')},{params.get('start_y')}) to ({params.get('end_x')},{params.get('end_y')})"

    @staticmethod
    def _validate_viewport_point(x: int, y: int, area: dict, label: str) -> tuple[bool, str]:
        """Reject coordinates that cannot exist in the browser viewport."""
        vw = int(area.get("vw", 0) or 0)
        vh = int(area.get("vh", 0) or 0)
        if vw <= 0 or vh <= 0:
            return True, ""
        if 0 <= x < vw and 0 <= y < vh:
            return True, ""
        return (
            False,
            f"{label} coordinate ({x},{y}) outside viewport {vw}x{vh}; "
            "use LEFT full-page absolute coordinates",
        )

    async def _exec_type_text(self, params: dict, page, area: dict) -> str:
        text = params.get("text", "")
        if not text:
            return "Error: no text specified"

        # 先尝试聚焦 captcha 内的文本输入框
        ox, oy = area.get("ox", 0), area.get("oy", 0)
        cw, ch = area.get("cw", 400), area.get("ch", 400)
        mouse = getattr(self, '_mouse', None)

        # 拟人化点击 captcha 区域中心偏下位置（文本输入框通常在下方）
        target_x = int(ox + cw * 0.5)
        target_y = int(oy + ch * 0.75)
        self._log(f"  👆 click to focus text area ({target_x},{target_y})")
        if mouse:
            await mouse.click(target_x, target_y)
            await mouse._human_pause(200, 400)  # 等待焦点切换
        else:
            await page.mouse.click(target_x, target_y)
            await asyncio.sleep(0.3)

        # 尝试 JS 填写
        filled = await page.evaluate(f"""(t) => {{
            const inp = document.querySelector('input[type="text"], input:not([type]), textarea, [class*="input"], [class*="answer"]');
            if (inp) {{
                inp.focus();
                inp.value = t;
                inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                return true;
            }}
            return false;
        }}""", text)

        if filled:
            self._log(f"  ⌨ typed (JS): {text}")
        else:
            # 用键盘逐字输入，随机按键间隔模拟人类打字节奏
            # 人类打字间隔: 100-300ms，连续字母快一些，特殊字符慢一些
            await page.keyboard.type(text, delay=random.randint(80, 200))
            self._log(f"  ⌨ typed (keyboard): {text}")

        # 自动按 Enter 提交文字输入（省去AI额外一轮调用）
        self._log("  ⏎ auto-pressing Enter after text input")
        await asyncio.sleep(random.uniform(0.15, 0.35))
        await page.keyboard.press("Enter")
        await asyncio.sleep(random.uniform(0.3, 0.6))

        return f"Typed: {text}"

    async def _exec_press_key(self, params: dict, page) -> str:
        key = params.get("key", "Enter")
        mouse = getattr(self, '_mouse', None)
        # 按键前人类反应时间
        if mouse:
            await mouse._human_pause(100, 300)
        await page.keyboard.press(key)
        await asyncio.sleep(random.randint(150, 350) / 1000)  # 按键后停顿
        self._log(f"  ⌨ pressed: {key}")
        return f"Pressed key: {key}"

    # ================================================================
    # 截图
    # ================================================================

    async def _capture_full_page(self, page) -> Optional[str]:
        """截取全页截图，供 AI 获取整体上下文."""
        try:
            buf = await page.screenshot(type="png", full_page=False)
            return base64.b64encode(buf).decode()
        except Exception as e:
            self._log(f"  full page capture error: {e}")
            return None

    async def _capture_captcha_area(self, page) -> Optional[dict]:
        """精确截取 hCaptcha 挑战弹窗区域."""
        try:
            result = await page.evaluate(r"""() => {
    // 策略1: 查找 hCaptcha iframe
    const iframes = document.querySelectorAll('iframe');
    for (const f of iframes) {
        const src = f.src || '';
        if (src.includes('hcaptcha') || src.includes('challenge')) {
            if (f.offsetParent !== null) {
                const r = f.getBoundingClientRect();
                if (r.width > 200 && r.height > 200) {
                    return {
                        found: true,
                        x: Math.round(r.x), y: Math.round(r.y),
                        width: Math.round(r.width), height: Math.round(r.height),
                        vw: window.innerWidth, vh: window.innerHeight,
                        source: 'iframe'
                    };
                }
            }
        }
    }

    // 策略2: 查找挑战弹窗(div)
    const challengeSelectors = [
        'div[class*="challenge"]', 'div[id*="challenge"]',
        'div[class*="task"]', 'div[class*="captcha"]',
        'div[class*="modal"]', 'div[class*="popup"]',
        'div[class*="overlay"]', 'div[class*="dialog"]',
        'div[class*="h-captcha"]',
        'div[aria-label*="captcha" i]', 'div[aria-label*="challenge" i]',
    ];

    let best = null;
    for (const sel of challengeSelectors) {
        try {
            const els = document.querySelectorAll(sel);
            for (const el of els) {
                if (!el.offsetParent) continue;
                const er = el.getBoundingClientRect();
                if (er.width > 200 && er.height > 200) {
                    if (!best || er.width * er.height > best.width * best.height) {
                        best = {x: er.x, y: er.y, width: er.width, height: er.height};
                    }
                }
            }
        } catch(e) { continue; }
    }

    if (best) {
        return {
            found: true,
            x: Math.round(best.x), y: Math.round(best.y),
            width: Math.round(best.width), height: Math.round(best.height),
            vw: window.innerWidth, vh: window.innerHeight,
            source: 'popup'
        };
    }

    // 策略3: hCaptcha widget container
    const container = document.querySelector('[data-hcaptcha-widget-id]');
    if (container) {
        const r = container.getBoundingClientRect();
        if (r.width > 150 && r.height > 150) {
            return {
                found: true,
                x: Math.round(r.x), y: Math.round(r.y),
                width: Math.round(Math.max(r.width, 300)),
                height: Math.round(Math.max(r.height, 350)),
                vw: window.innerWidth, vh: window.innerHeight,
                source: 'widget'
            };
        }
    }

    return {found: false};
}""")
            if not result.get("found"):
                return None

            x, y, w, h = result["x"], result["y"], result["width"], result["height"]
            vw, vh = result["vw"], result["vh"]

            # 边界检查
            x = max(0, x)
            y = max(0, y)
            w = min(w, vw - x)
            h = min(h, vh - y)

            buf = await page.screenshot(
                clip={"x": x, "y": y, "width": w, "height": h},
                type="png",
            )

            # 叠加坐标网格，辅助AI识别像素位置
            buf = self._add_coordinate_grid(buf, w, h)

            b64 = base64.b64encode(buf).decode()

            source = result.get("source", "unknown")
            self._log(f"  📸 Captcha area: ({x},{y}) {w}x{h} [{source}]")

            return {
                "image": b64,
                "area": {
                    "ox": x, "oy": y,  # 左上角绝对坐标
                    "cw": w, "ch": h,  # 宽高
                    "vw": vw, "vh": vh,  # 视口大小
                },
            }
        except Exception as e:
            self._log(f"  capture error: {e}")
            return None

    # ================================================================
    # 坐标网格叠加
    # ================================================================

    @staticmethod
    def _compose_dual(png_bytes: bytes, vw: int, vh: int, captcha_bounds: dict) -> str:
        """左右双图: 左侧=全页(网格+红框), 右侧=验证码区域裁切特写。
        
        返回 base64 字符串。AI同时看到全局坐标和挑战细节。
        """
        img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        try:
            font = ImageFont.truetype("arial.ttf", 12)
        except Exception:
            font = ImageFont.load_default()

        # ---- LEFT: 全页标注 ----
        # 网格
        for x in range(200, vw, 200):
            draw.line([(x, 0), (x, vh)], fill=(100, 120, 255, 30), width=1)
        for y in range(200, vh, 200):
            draw.line([(0, y), (vw, y)], fill=(100, 120, 255, 30), width=1)
        # 坐标标注
        for x in range(0, vw + 1, 200):
            s = str(x)
            b = draw.textbbox((0, 0), s, font=font)
            tw = b[2] - b[0]
            draw.rectangle([(x - tw//2 - 3, 1), (x + tw//2 + 3, 13)], fill=(0, 0, 0, 90))
            draw.text((x - tw//2, 2), s, fill=(150, 180, 255, 200), font=font)
        for y in range(200, vh + 1, 200):
            s = str(y)
            b = draw.textbbox((0, 0), s, font=font)
            th = b[3] - b[1]
            draw.rectangle([(2, y - th//2 - 1), (b[2] - b[0] + 5, y + th//2 + 1)], fill=(0, 0, 0, 90))
            draw.text((3, y - th//2), s, fill=(150, 180, 255, 200), font=font)
        # 四角
        for cx, cy, ct in [(0, 0, "0,0"), (vw - 60, 0, f"{vw},0"),
                           (0, vh - 16, f"0,{vh}"), (vw - 70, vh - 16, f"{vw},{vh}")]:
            draw.rectangle([(cx, cy), (cx + len(ct) * 7 + 6, cy + 15)], fill=(0, 0, 0, 100))
            draw.text((cx + 2, cy + 1), ct, fill=(180, 180, 180, 220), font=font)

        # 红色框
        if captcha_bounds.get("found"):
            bx, by = round(captcha_bounds["x"]), round(captcha_bounds["y"])
            bw, bh = round(captcha_bounds["w"]), round(captcha_bounds["h"])
            for o in range(3):
                draw.rectangle([(bx - o, by - o), (bx + bw + o, by + bh + o)],
                              outline=(255, 50, 50, 180), width=1)
            tag = f"[{bx},{by}] {bw}x{bh}"
            b = draw.textbbox((0, 0), tag, font=font)
            ly = max(0, by - 17)
            draw.rectangle([(bx, ly), (bx + b[2] - b[0] + 6, ly + 15)], fill=(255, 50, 50, 190))
            draw.text((bx + 2, ly + 1), tag, fill=(255, 255, 255, 240), font=font)

        annotated = Image.alpha_composite(img, overlay).convert("RGB")

        # ---- RIGHT: 裁切验证码区域 ----
        if captcha_bounds.get("found"):
            crop = img.crop((bx, by, bx + bw, by + bh)).convert("RGB")
            # 放大挑战区域，帮助视觉模型看清目标文字和小图细节。
            cw, ch = crop.size
            scale = min(900 / max(cw, 1), 2.0)
            if scale != 1.0:
                crop = crop.resize((int(cw * scale), int(ch * scale)), Image.LANCZOS)
        else:
            crop = annotated.copy()

        # ---- 组合: 左右并排 ----
        lw, lh = annotated.size
        rw, rh = crop.size
        gap = 4
        total_w = lw + gap + rw
        total_h = max(lh, rh)

        composed = Image.new("RGB", (total_w, total_h), (30, 30, 30))
        composed.paste(annotated, (0, 0))
        composed.paste(crop, (lw + gap, 0))

        # 右侧标题
        cdraw = ImageDraw.Draw(composed)
        cdraw.text(
            (lw + gap + 4, 2),
            "RIGHT ZOOM - DETAIL ONLY, USE LEFT COORDS",
            fill=(255, 200, 100),
            font=font,
        )
        # 分隔线
        cdraw.line([(lw + gap - 2, 0), (lw + gap - 2, total_h)], fill=(80, 80, 80), width=2)

        buf = io.BytesIO()
        composed.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    # 检测验证码是否通过 (v2: 增强版)
    # ================================================================

    async def _check_passed(self, page) -> bool:
        """检查 hCaptcha 是否已真正通过。v2: 检测绿色勾号等多重信号."""
        try:
            result = await page.evaluate(r"""() => {
    // === 强信号 ===
    // 1. 6位数字验证码输入框（NVIDIA注册特有，最可靠信号）
    const numInputs = document.querySelectorAll('input[type="number"]');
    if (numInputs.length >= 6) return 'code_inputs';

    // 2. 验证邮箱页面文本
    const bodyText = (document.body?.innerText || '').toLowerCase();
    if (bodyText.includes('verify your email') ||
        bodyText.includes('验证您的电子邮件') ||
        bodyText.includes('enter the 6-digit') ||
        bodyText.includes('输入6位') ||
        bodyText.includes('verification code') ||
        bodyText.includes('验证码'))
        return 'verification_page';

    // 3. hCaptcha response token 已填充（说明验证码已通过）
    const hcaptchaInputs = document.querySelectorAll(
        '[name="h-captcha-response"], [name="h-captcha-response"]'
    );
    for (const inp of hcaptchaInputs) {
        if (inp.value && inp.value.length > 100) return 'has_token';
    }
    // 也检查 textarea
    const ta = document.querySelector('textarea[data-hcaptcha-response]');
    if (ta && ta.value && ta.value.length > 100) return 'has_token';

    // === 中信号：hCaptcha checkbox 状态 ===
    // 4. hCaptcha iframe 内 checkbox 显示已通过
    const hcaptchaIframes = document.querySelectorAll('iframe');
    for (const f of hcaptchaIframes) {
        const src = f.src || '';
        if (src.includes('hcaptcha') && !src.includes('challenge')) {
            // checkbox iframe — 检查是否显示 "✓"
            try {
                const doc = f.contentDocument || f.contentWindow?.document;
                if (doc) {
                    const checkbox = doc.querySelector('.checkbox[aria-checked="true"], [data-checked="true"]');
                    if (checkbox) return 'checkbox_checked';
                    // 检查绿色勾号
                    const checkmark = doc.querySelector('[class*="check"], [class*="success"], [class*="green"]');
                    if (checkmark) return 'checkbox_checked';
                }
            } catch(e) {}
        }
    }

    // 5. 页面主表单的提交按钮已可用（captcha区域的勾号可见）
    // 查找 create account / submit 按钮
    const submitBtns = document.querySelectorAll('button[type="submit"], button');
    for (const btn of submitBtns) {
        const t = (btn.innerText || btn.textContent || '').toLowerCase().trim();
        if ((t.includes('create') || t.includes('创建') || t.includes('sign up') || t.includes('register') || t.includes('注册')) &&
            btn.offsetParent !== null && !btn.disabled) {
            return 'submit_available';
        }
    }

    // === 弱信号：hCaptcha 弹窗消失 ===
    // 6. hCaptcha widget 隐藏
    const ce = document.querySelector('[data-hcaptcha-widget-id]');
    if (ce) {
        const s = window.getComputedStyle(ce);
        if (s.display === 'none' || s.visibility === 'hidden') return 'captcha_hidden';
    }

    // 7. 挑战 iframe 不再可见
    let challengeVisible = false;
    for (const f of hcaptchaIframes) {
        const src = f.src || '';
        if (src.includes('hcaptcha') && src.includes('challenge')) {
            if (f.offsetParent !== null) {
                const fr = f.getBoundingClientRect();
                if (fr.width > 100 && fr.height > 100) challengeVisible = true;
            }
        }
    }
    if (!challengeVisible) {
        // hCaptcha widget 存在但没有挑战iframe → 可能已通过
        if (document.querySelector('[data-hcaptcha-widget-id]')) {
            return 'no_challenge_iframe';
        }
    }

    return 'not_passed';
}""")
            passed = result not in ("not_passed",)
            if passed:
                self._log(f"  ✅ check passed: {result}")
            return passed
        except Exception as e:
            self._log(f"  check error: {e}")
            return False

    # ================================================================
    # 自动提交表单
    # ================================================================

    async def _click_form_submit(self, page) -> bool:
        """hCaptcha 通过后，自动点击页面上的提交/创建账户按钮."""
        try:
            self._log("  🔘 Attempting to click form submit button...")
            clicked = await page.evaluate(r"""() => {
                const btns = document.querySelectorAll('button[type="submit"], button, input[type="submit"]');
                const keywords = [
                    'create account', '创建账户', '创建账号',
                    'sign up', '注册', 'continue', '继续',
                    'next', '下一步', 'submit', '提交',
                ];
                for (const btn of btns) {
                    if (!btn.offsetParent || btn.disabled) continue;
                    const t = (btn.innerText || btn.textContent || btn.value || '').toLowerCase().trim();
                    if (keywords.some(k => t.includes(k))) {
                        btn.click();
                        return 'clicked: ' + t;
                    }
                }
                return null;
            }""")
            if clicked:
                self._log(f"  ✅ Form submit: {clicked}")
                await asyncio.sleep(3)  # 等待页面跳转
                return True
            else:
                self._log("  ⚠️ No submit button found to click")
                return False
        except Exception as e:
            self._log(f"  form submit error: {e}")
            return False

    # ================================================================
    # Playwright 基础操作
    # ================================================================

    async def _click_checkbox(self, page) -> bool:
        """点击 hCaptcha 小方框（拟人化双次点击，模拟人类双击习惯）."""
        try:
            vp = await page.evaluate("()=>({w:window.innerWidth,h:window.innerHeight})")
            x, y = int(HCAPTCHA_CHECKBOX_VP[0] * vp["w"]), int(HCAPTCHA_CHECKBOX_VP[1] * vp["h"])
            self._log(f"  ☑ clicking checkbox ({x},{y})")
            mouse = getattr(self, '_mouse', None)
            if mouse:
                await mouse.click(x, y)
                # 人类双击间隔 (200-400ms)
                await mouse._human_pause(200, 400)
                await mouse.click(x + random.randint(-2, 2), y + random.randint(-2, 2))
            else:
                await page.mouse.click(x, y)
                await asyncio.sleep(0.5)
                await page.mouse.click(x, y)
            return True
        except Exception as e:
            self._log(f"  checkbox error: {e}")
            return False

    async def _refresh_captcha(self, page) -> bool:
        """刷新验证码."""
        try:
            clicked = await page.evaluate(r"""() => {
                const b = document.querySelector('.h-captcha, [data-hcaptcha-widget-id], iframe[src*="hcaptcha"]');
                if (b) {
                    const r = b.getBoundingClientRect();
                    b.dispatchEvent(new MouseEvent('click', {
                        bubbles: true, cancelable: true,
                        clientX: r.x + 20, clientY: r.y + 20,
                    }));
                    return true;
                }
                return false;
            }""")
            if not clicked:
                vp = await page.evaluate("()=>({w:window.innerWidth,h:window.innerHeight})")
                tx = int(HCAPTCHA_CHECKBOX_VP[0] * vp["w"])
                ty = int(HCAPTCHA_CHECKBOX_VP[1] * vp["h"])
                mouse = getattr(self, '_mouse', None)
                if mouse:
                    await mouse.click(tx, ty)
                else:
                    await page.mouse.click(tx, ty)
            return True
        except Exception as e:
            self._log(f"  refresh error: {e}")
            return False

    # ================================================================
    # 网格布局智能检测
    # ================================================================

    @staticmethod
    def _detect_grid_layout(page, cell_count: int) -> tuple:
        """根据单元格数量智能检测网格布局."""
        if cell_count <= 4:
            return (2, 2)
        elif cell_count <= 9:
            return (3, 3)
        elif cell_count <= 12:
            return (3, 4)
        elif cell_count <= 16:
            return (4, 4)
        elif cell_count <= 20:
            return (5, 4)
        elif cell_count <= 25:
            return (5, 5)
        else:
            return (6, 6)

    # ================================================================
    # 决策解析
    # ================================================================

    def _parse_tool_call(self, text: str) -> dict:
        """从 AI 回复中解析工具调用 JSON."""
        # 提取 JSON 块
        json_str = None
        depth = 0
        start = -1
        for i, ch in enumerate(text):
            if ch == '{':
                if depth == 0:
                    start = i
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0 and start >= 0:
                    json_str = text[start:i + 1]
                    break

        if json_str:
            try:
                parsed = json.loads(json_str)
                decision = {
                    "tool": parsed.get("tool", ""),
                    "params": parsed.get("params", {}),
                    "confidence": parsed.get("confidence"),
                    "thinking": parsed.get("thinking", ""),
                }
                confidence = decision.get("confidence")
                try:
                    confidence_value = float(confidence)
                except (TypeError, ValueError):
                    confidence_value = None
                if (
                    decision["tool"] in {"click_grid_cells", "drag_from_to", "click_at"}
                    and confidence_value is not None
                    and confidence_value < 0.7
                ):
                    return {
                        "tool": "wait",
                        "params": {
                            "seconds": 1.5,
                            "reason": f"low confidence for {decision['tool']}: {confidence_value}",
                        },
                        "confidence": confidence_value,
                        "thinking": decision["thinking"] or "low-confidence action blocked",
                    }
                return decision
            except json.JSONDecodeError:
                self._log(f"  ⚠️ JSON parse failed from: {text[:200]}")

        # === 降级：文本模式匹配 ===
        tl = text.lower()

        # 检测 grid cells
        cells = re.findall(r'\[(\d)\s*[,，\s]\s*(\d)\]', text)
        if cells:
            return {
                "tool": "click_grid_cells",
                "params": {"cells": [[int(r), int(c)] for r, c in cells]},
                "thinking": "fallback: detected grid cell references in text",
            }

        # 检测 drag
        if any(k in tl for k in ["drag", "slider", "slide", "拖动", "滑块"]):
            return {
                "tool": "drag_from_to",
                "params": {
                    "start_x": 60, "start_y": 400,
                    "end_x": 350, "end_y": 400,
                },
                "thinking": "fallback: detected drag/slider reference",
            }

        # 检测 type
        type_match = re.search(r'type\s*[:=]?\s*["\']?(\w+)["\']?', tl)
        if type_match or any(k in tl for k in ["text", "input", "输入", "type"]):
            return {
                "tool": "type_text",
                "params": {"text": "test"},
                "thinking": "fallback: detected text input reference",
            }

        # 检测 solved/done
        if any(k in tl for k in ["solved", "done", "pass", "通过", "完成",
                                  "checkmark", "green", "绿色", "success",
                                  "verified", "验证成功"]):
            return {
                "tool": "report_done",
                "params": {"evidence": "detected solved/pass keywords in text"},
                "thinking": "fallback: detected success indicators",
            }

        # 检测 enter/submit
        if any(k in tl for k in ["enter", "submit", "verify", "验证", "提交", "确认"]):
            return {
                "tool": "press_key",
                "params": {"key": "Enter"},
                "thinking": "fallback: detected submit/enter reference",
            }

        # 检测 wait
        if any(k in tl for k in ["wait", "load", "等待", "loading", "spinner"]):
            return {
                "tool": "wait",
                "params": {"seconds": 2},
                "thinking": "fallback: detected wait/loading reference",
            }

        # 默认：报告完成
        return {
            "tool": "wait",
            "params": {"seconds": 1.5, "reason": "no clear high-confidence action found"},
            "confidence": 0.0,
            "thinking": "fallback: no tool matched, waiting instead of guessing",
        }

    # ================================================================
    # 工具函数
    # ================================================================

    def _log(self, msg: str):
        if self.verbose:
            lines = msg.split('\n')
            for line in lines:
                print(f"  [Agent] {line}" if line.strip() else "")

    def _print_stats(self):
        s = self._stats
        self._log(f"📊 Agent Stats: steps={s['steps']} tool_calls={s['tool_calls']} screenshots={s['screenshots']}")

    def get_stats(self) -> dict:
        return dict(self._stats)


# ============================================================================
# 兼容别名 + 便捷函数
# ============================================================================

HCaptchaSolver = AgentCaptchaSolver


def test_connection(api_key: str = "", base_url: str = "", model: str = "") -> dict:
    """测试 LLM 连接。自动发现 API.txt 中的凭证。"""
    if str(base_url or "").strip().lower() == "auto":
        base_url = ""
    if not api_key or not base_url:
        discovered = LLMClient.discover_api_txt()
        if discovered:
            api_key, base_url = discovered

    if not api_key or not base_url:
        return {"ok": False, "message": "No API credentials configured", "latency_ms": 0}

    try:
        client = LLMClient(api_key=api_key, base_url=base_url, model=model or "qwen3.6-flash")
        result = client.test_connectivity()
        result["backend"] = "direct"
        return result
    except Exception as e:
        return {"ok": False, "message": str(e), "latency_ms": 0}


async def solve_captcha_auto(page, api_key: str = "", base_url: str = "", model: str = "") -> bool:
    solver = AgentCaptchaSolver(api_key=api_key, base_url=base_url, model=model or "qwen3.6-flash")
    return await solver.solve(page)
