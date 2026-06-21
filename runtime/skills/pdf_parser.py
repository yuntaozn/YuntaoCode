"""
PDF 文档解析器
用于 YuntaoCode 本地文档能力；优先本地解析，质量不足时按能力边界降级。

策略决策树：
1. pypdf 快速提取 -> 质量检测（乱码率 + CID检测）
2. 质量差时启用 pdfplumber + PyMuPDF 兜底渲染
3. 扫描件/乱码文件走 AI 多模态 OCR（复用终端已配置的模型）
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import string
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .text_postprocessor import TextPostProcessor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 可选依赖 — 缺失时优雅降级
# ---------------------------------------------------------------------------

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

try:
    import numpy as np
    from PIL import Image as PILImage
    HAS_IMAGE = True
except ImportError:
    HAS_IMAGE = False


# ---------------------------------------------------------------------------
# 解析结果
# ---------------------------------------------------------------------------

@dataclass
class ParseResult:
    """PDF 解析结果"""
    text: str = ""
    total_pages: int = 0
    pages_parsed: int = 0
    strategy: str = "pypdf"  # pypdf | pdfplumber | ocr
    garbled_ratio: float = 0.0
    cid_garbled: bool = False
    ocr_used: bool = False
    ocr_pages: int = 0
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 核心解析器
# ---------------------------------------------------------------------------

class PDFParser:
    """异步 PDF 解析器，支持乱码检测和 OCR 回退"""

    _pdf_lock = asyncio.Lock()  # pdfplumber/PDFium 非线程安全
    _executor = ThreadPoolExecutor(max_workers=4)
    _ocr_semaphore = asyncio.Semaphore(4)  # OCR 并发限流
    _post_processor = TextPostProcessor()

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    async def parse(
        self,
        file_path: Path,
        max_pages: int = 0,
        context: Any = None,
    ) -> ParseResult:
        """主入口：自动决策最佳提取策略。

        :param file_path: PDF 文件路径
        :param max_pages: 最大解析页数（0 = 不限）
        :param context: ToolContext，需要包含 settings 属性以支持 OCR
        """
        result = ParseResult()
        file_str = str(file_path)

        # 策略 1: pypdf 快速提取
        text, total_pages = await self._extract_pypdf(file_str, max_pages)
        result.total_pages = total_pages
        result.pages_parsed = min(max_pages, total_pages) if max_pages > 0 else total_pages

        # 策略 2: 文本为空 -> 可能是扫描版
        if not text.strip():
            logger.info("pypdf 提取为空，尝试 OCR 路径")
            ocr_result = await self._ocr_path(file_str, result, context, force_ocr=False)
            return ocr_result

        # 策略 3: 乱码检测
        garbled = self._garbled_ratio(text)
        result.garbled_ratio = garbled
        logger.info(f"乱码检测: {garbled:.2%}")

        # 每页平均字符数
        avg_chars = len(text) / total_pages if total_pages > 0 else 0

        if avg_chars < 50:
            logger.info(f"平均每页 {avg_chars:.0f} 字符，判断为扫描版")
            return await self._ocr_path(file_str, result, context, force_ocr=False)

        if garbled > 0.15:
            logger.info(f"乱码率 {garbled:.2%} 超过阈值，走 OCR")
            return await self._ocr_path(file_str, result, context, force_ocr=True)

        if self._looks_like_cid_garbled(text, file_str):
            result.cid_garbled = True
            logger.info("检测到 CID 字体编码乱码，走 OCR")
            return await self._ocr_path(file_str, result, context, force_ocr=True)

        # 策略 4: 文本质量良好，直接后处理返回
        result.text = self._post_processor.process(text)
        result.strategy = "pypdf"
        return result

    # ------------------------------------------------------------------
    # pypdf 提取
    # ------------------------------------------------------------------

    async def _extract_pypdf(self, file_path: str, max_pages: int) -> tuple[str, int]:
        """使用 pypdf 快速提取文本（不持锁）"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            self._sync_extract_pypdf,
            file_path, max_pages,
        )

    @staticmethod
    def _sync_extract_pypdf(file_path: str, max_pages: int) -> tuple[str, int]:
        """同步 pypdf 提取"""
        import pypdf
        text = ""
        total_pages = 0
        try:
            with open(file_path, 'rb') as f:
                reader = pypdf.PdfReader(f)
                total_pages = len(reader.pages)
                limit = min(total_pages, max_pages) if max_pages > 0 else total_pages
                for i, page in enumerate(reader.pages[:limit]):
                    try:
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text + "\n"
                    except Exception as e:
                        logger.debug(f"pypdf 第{i+1}页提取失败: {e}")
        except Exception as e:
            logger.warning(f"pypdf 解析失败: {e}")
        return text, total_pages

    # ------------------------------------------------------------------
    # 乱码检测
    # ------------------------------------------------------------------

    @staticmethod
    def _garbled_ratio(text: str) -> float:
        """计算文本中的乱码比例（支持多语言字符集）"""
        if not text:
            return 1.0

        def is_valid(c: str) -> bool:
            return (
                c in string.printable or
                '\u4e00' <= c <= '\u9fff' or  # 中文基本汉字
                '\u3400' <= c <= '\u4DBF' or  # CJK扩展A
                '\u2F00' <= c <= '\u2FDF' or  # 康熙部首
                '\uF900' <= c <= '\uFAFF' or  # CJK兼容汉字
                '\u0400' <= c <= '\u04FF' or  # 西里尔文
                '\u00C0' <= c <= '\u024F' or  # 拉丁文扩展
                '\u3040' <= c <= '\u309F' or  # 平假名
                '\u30A0' <= c <= '\u30FF' or  # 片假名
                '\uAC00' <= c <= '\uD7AF'     # 韩文
            )

        valid = sum(1 for c in text if is_valid(c))
        return 1.0 - valid / len(text) if len(text) > 0 else 1.0

    @staticmethod
    def _looks_like_cid_garbled(text: str, file_path: str = "") -> bool:
        """检测 CID/ToUnicode 映射缺失型乱码。

        强判定：中文文件名 + 提取文本中文占比 < 2%
        兜底判定：中文<2% + 标点>25% + 英文单词<40%
        """
        if not text:
            return False
        sample = text[:5000]
        total = len(sample)
        if total < 200:
            return False

        cjk = sum(1 for c in sample if '\u4e00' <= c <= '\u9fff')
        cjk_ratio = cjk / total

        # 强判定：中文文件名 + 中文极少
        if file_path:
            try:
                filename = os.path.basename(file_path)
            except Exception:
                filename = ''
            has_chinese_fn = any('\u4e00' <= c <= '\u9fff' for c in filename)
            if has_chinese_fn and cjk_ratio < 0.02:
                logger.info(f"CID乱码: 中文文件名但中文仅 {cjk_ratio:.2%}")
                return True

        # 兜底判定
        punct_chars = set('!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~''""、。，！？；：—…【】（）《》')
        punct = sum(1 for c in sample if c in punct_chars)
        punct_ratio = punct / total
        long_words = re.findall(r'[A-Za-z]{3,}', sample)
        long_word_chars = sum(len(w) for w in long_words)
        long_word_ratio = long_word_chars / total

        result = cjk_ratio < 0.02 and punct_ratio > 0.25 and long_word_ratio < 0.40
        if result:
            logger.info(f"CID乱码(兜底): 中文={cjk_ratio:.2%} 标点={punct_ratio:.2%} 英文={long_word_ratio:.2%}")
        return result

    # ------------------------------------------------------------------
    # OCR 路径（pdfplumber 渲染 + AI OCR）
    # ------------------------------------------------------------------

    async def _ocr_path(
        self,
        file_path: str,
        result: ParseResult,
        context: Any,
        force_ocr: bool = False,
    ) -> ParseResult:
        """OCR 路径：阶段A 持锁渲染，阶段B 释放锁后并发 OCR"""
        result.strategy = "ocr"
        result.ocr_used = True

        if not HAS_PDFPLUMBER and not HAS_PYMUPDF:
            result.warnings.append("缺少 pdfplumber 和 PyMuPDF，无法执行 OCR 路径")
            # 回退到 pypdf 原始文本
            text, _ = await self._extract_pypdf(file_path, 0)
            result.text = self._post_processor.process(text) if text else ""
            result.strategy = "pypdf"
            result.ocr_used = False
            return result

        if not HAS_IMAGE:
            result.warnings.append("缺少 numpy/Pillow，无法渲染图像进行 OCR")
            text, _ = await self._extract_pypdf(file_path, 0)
            result.text = self._post_processor.process(text) if text else ""
            result.strategy = "pypdf"
            result.ocr_used = False
            return result

        # 阶段 A: 持锁渲染
        loop = asyncio.get_event_loop()
        async with self._pdf_lock:
            page_texts, images = await loop.run_in_executor(
                self._executor,
                self._sync_render_pages,
                file_path,
            )

        result.total_pages = len(page_texts)
        result.pages_parsed = len(page_texts)

        # 阶段 B: 释放锁后并发 OCR
        if context and hasattr(context, 'settings') and context.settings:
            ocr_text, ocr_count = await self._ocr_pages(
                page_texts, images, context, force_ocr=force_ocr
            )
            result.ocr_pages = ocr_count
            result.text = ocr_text
        else:
            # 无模型配置，只用 pdfplumber 文本
            result.warnings.append("无模型配置，跳过 AI OCR，仅使用 pdfplumber 文本")
            result.ocr_used = False
            result.strategy = "pdfplumber"
            combined = "\n".join(t for t in page_texts if t)
            result.text = self._post_processor.process(combined)

        return result

    @staticmethod
    def _sync_render_pages(file_path: str) -> tuple[list[str], list[Any]]:
        """pdfplumber 渲染：提取文本 + 渲染图像（持锁调用）"""
        page_texts: list[str] = []
        images: list[Any] = []  # numpy arrays or None
        failed_indices: list[int] = []

        if HAS_PDFPLUMBER:
            try:
                with pdfplumber.open(file_path) as pdf:
                    for i, page in enumerate(pdf.pages):
                        # 提取文本
                        page_text = ""
                        try:
                            page_text = page.extract_text() or ""
                        except Exception as e:
                            logger.debug(f"pdfplumber 第{i+1}页文本失败: {e}")

                        # 渲染图像
                        img = None
                        if HAS_IMAGE:
                            try:
                                img_obj = page.to_image()
                                if img_obj:
                                    img = np.array(img_obj.original)
                            except Exception as e:
                                logger.debug(f"pdfplumber 第{i+1}页图像失败: {e}")
                                failed_indices.append(i)

                        page_texts.append(page_text)
                        images.append(img)
            except Exception as e:
                logger.warning(f"pdfplumber 打开失败: {e}")

        # PyMuPDF 兜底渲染失败页
        total = len(page_texts)
        if (
            HAS_PYMUPDF and HAS_IMAGE
            and failed_indices
            and total > 0
            and len(failed_indices) / total > 0.3
        ):
            logger.info(f"pdfplumber 渲染失败 {len(failed_indices)}/{total} 页，启用 PyMuPDF 兜底")
            try:
                with fitz.open(file_path) as doc:
                    for idx in failed_indices:
                        if idx >= len(doc):
                            continue
                        try:
                            pix = doc[idx].get_pixmap(dpi=150)
                            pil_im = PILImage.frombytes("RGB", (pix.width, pix.height), pix.samples)
                            images[idx] = np.array(pil_im)
                        except Exception as e:
                            logger.debug(f"PyMuPDF 第{idx+1}页失败: {e}")
            except Exception as e:
                logger.warning(f"PyMuPDF 兜底整体失败: {e}")

        # 如果 pdfplumber 完全失败，尝试纯 PyMuPDF
        if not page_texts and HAS_PYMUPDF:
            try:
                with fitz.open(file_path) as doc:
                    for i, page in enumerate(doc):
                        page_text = page.get_text() or ""
                        page_texts.append(page_text)
                        img = None
                        if HAS_IMAGE:
                            try:
                                pix = page.get_pixmap(dpi=150)
                                pil_im = PILImage.frombytes("RGB", (pix.width, pix.height), pix.samples)
                                img = np.array(pil_im)
                            except Exception:
                                pass
                        images.append(img)
            except Exception as e:
                logger.warning(f"PyMuPDF 独立解析失败: {e}")

        return page_texts, images

    # ------------------------------------------------------------------
    # AI OCR（调用终端模型客户端）
    # ------------------------------------------------------------------

    async def _ocr_pages(
        self,
        page_texts: list[str],
        images: list[Any],
        context: Any,
        force_ocr: bool = False,
    ) -> tuple[str, int]:
        """并发 OCR 需要识别的页面，返回 (拼接文本, OCR页数)"""
        ocr_count = 0

        async def process_page(idx: int) -> tuple[int, str]:
            nonlocal ocr_count
            page_text = page_texts[idx] if idx < len(page_texts) else ""
            img = images[idx] if idx < len(images) else None

            is_scan_page = len(page_text.strip()) < 50
            need_ocr = (is_scan_page or force_ocr) and img is not None

            if need_ocr:
                async with self._ocr_semaphore:
                    try:
                        ocr_text = await self._call_model_ocr(img, idx + 1, context)
                        ocr_count += 1
                        return idx, ocr_text or ""
                    except Exception as e:
                        logger.warning(f"第{idx+1}页 OCR 失败: {e}")
                        return idx, page_text
            else:
                return idx, page_text

        tasks = [process_page(i) for i in range(len(page_texts))]
        results = await asyncio.gather(*tasks)
        results.sort(key=lambda x: x[0])

        # 按页拼接 + 后处理
        text_parts: list[str] = []
        for _, page_text in results:
            if page_text:
                try:
                    cleaned = self._post_processor.process(page_text)
                    text_parts.append(cleaned)
                except Exception:
                    text_parts.append(page_text)

        return "\n".join(text_parts), ocr_count

    async def _call_model_ocr(self, img_array: Any, page_num: int, context: Any) -> str:
        """调用终端已配置的多模态模型进行单页 OCR"""
        import base64

        # 将 numpy 数组转为 PNG bytes
        pil_img = PILImage.fromarray(img_array)
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        img_bytes = buf.getvalue()
        base64_img = base64.b64encode(img_bytes).decode()

        messages = [{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{base64_img}"}
                },
                {
                    "type": "text",
                    "text": "请识别图片中的所有文字和表格内容，保持原始格式，返回完整文本。"
                },
            ]
        }]

        from runtime.model_providers.client import generate_chat_completion
        answer, _ = await generate_chat_completion(
            settings=context.settings,
            model="doubao-seed-1-8-251228",
            messages=messages,
            enable_thinking=False,
        )
        return answer
