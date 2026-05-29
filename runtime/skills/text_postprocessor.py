"""
文本后处理工具
清理 PDF 解析产生的多余空格、格式化问题等
移植自 aipython/core/rag/text_postprocessor.py
"""
from __future__ import annotations

import re


class TextPostProcessor:
    """文本后处理器"""

    def __init__(self):
        # 中文标点符号
        self.chinese_punctuation = '，。、；：？！""''（）【】《》…—·'

        # 常见英文单词（用于识别是否需要保留空格）
        self.common_english_words = {
            'the', 'be', 'to', 'of', 'and', 'a', 'in', 'that', 'have', 'it',
            'for', 'not', 'on', 'with', 'he', 'as', 'you', 'do', 'at', 'this',
            'but', 'his', 'by', 'from', 'they', 'we', 'say', 'her', 'she',
            'or', 'an', 'will', 'my', 'one', 'all', 'would', 'there', 'their',
            'what', 'so', 'up', 'out', 'if', 'about', 'who', 'get', 'which',
            'go', 'me', 'when', 'make', 'can', 'like', 'time', 'no', 'just',
            'him', 'know', 'take', 'people', 'into', 'year', 'your', 'good',
            'some', 'could', 'them', 'see', 'other', 'than', 'then', 'now',
            'look', 'only', 'come', 'its', 'over', 'think', 'also', 'back',
            'after', 'use', 'two', 'how', 'our', 'work', 'first', 'well',
            'way', 'even', 'new', 'want', 'because', 'any', 'these', 'give',
            'day', 'most', 'GB', 'mm', 'MPa', 'CJJ', 'SY', 'PU', 'PE', 'PP'
        }

    def process(self, text: str) -> str:
        """处理文本，清理多余空格和特殊编码字符"""
        if not text:
            return text

        # 步骤 0: 转换 PDF 特殊编码字符（康熙部首/兼容汉字）为常规汉字
        text = self._convert_special_chars(text)

        # 步骤 1: 清理中文之间的多余空格
        text = self._remove_chinese_spaces(text)

        # 步骤 2: 清理被拆分的英文单词
        text = self._fix_broken_english(text)

        # 步骤 3: 清理数字和单位之间的空格
        text = self._fix_number_unit_spaces(text)

        # 步骤 4: 清理标点符号周围的空格
        text = self._fix_punctuation_spaces(text)

        # 步骤 5: 清理多余的空行和制表符
        text = self._clean_extra_whitespace(text)

        return text

    def _convert_special_chars(self, text: str) -> str:
        """转换 PDF 特殊编码字符为常规汉字（康熙部首 + CJK兼容汉字）"""
        char_mapping = {
            '\u2F00': '一', '\u2F03': '丶', '\u2F06': '亅', '\u2F07': '二',
            '\u2F08': '亠', '\u2F09': '人', '\u2F0A': '儿', '\u2F0B': '入',
            '\u2F0C': '八', '\u2F0D': '冂', '\u2F0E': '冖', '\u2F0F': '冫',
            '\u2F10': '几', '\u2F11': '凵', '\u2F12': '刀', '\u2F13': '力',
            '\u2F14': '勹', '\u2F15': '匕', '\u2F16': '匚', '\u2F17': '匸',
            '\u2F18': '十', '\u2F19': '卜', '\u2F1A': '卩', '\u2F1B': '厂',
            '\u2F1C': '厶', '\u2F1D': '又', '\u2F20': '口', '\u2F21': '囗',
            '\u2F22': '土', '\u2F23': '士', '\u2F24': '夂', '\u2F25': '夊',
            '\u2F26': '夕', '\u2F27': '大', '\u2F28': '女', '\u2F29': '子',
            '\u2F2A': '宀', '\u2F2B': '寸', '\u2F2C': '小', '\u2F2D': '尢',
            '\u2F2E': '尸', '\u2F2F': '屮', '\u2F30': '山', '\u2F31': '巛',
            '\u2F32': '工', '\u2F33': '己', '\u2F34': '巾', '\u2F35': '干',
            '\u2F36': '幺', '\u2F37': '广', '\u2F38': '廴', '\u2F39': '廾',
            '\u2F3A': '弋', '\u2F3B': '弓', '\u2F3C': '彐', '\u2F3D': '彡',
            '\u2F3E': '彳', '\u2F3F': '心', '\u2F40': '戈', '\u2F41': '戶',
            '\u2F42': '手', '\u2F43': '支', '\u2F44': '攴', '\u2F45': '文',
            '\u2F46': '斗', '\u2F47': '斤', '\u2F48': '方', '\u2F49': '无',
            '\u2F4A': '日', '\u2F4B': '曰', '\u2F4C': '月', '\u2F4D': '木',
            '\u2F4E': '欠', '\u2F4F': '止', '\u2F50': '歹', '\u2F51': '殳',
            '\u2F52': '毋', '\u2F53': '比', '\u2F54': '毛', '\u2F55': '氏',
            '\u2F56': '气', '\u2F57': '水', '\u2F58': '火', '\u2F59': '爪',
            '\u2F5A': '父', '\u2F5B': '爻', '\u2F5C': '爿', '\u2F5D': '片',
            '\u2F5E': '牙', '\u2F5F': '牛', '\u2F60': '犬', '\u2F61': '玄',
            '\u2F62': '玉', '\u2F63': '瓜', '\u2F64': '瓦', '\u2F65': '甘',
            '\u2F66': '生', '\u2F67': '用', '\u2F68': '田', '\u2F69': '疋',
            '\u2F6A': '疒', '\u2F6B': '癶', '\u2F6C': '白', '\u2F6D': '皮',
            '\u2F6E': '皿', '\u2F6F': '目', '\u2F70': '矛', '\u2F71': '矢',
            '\u2F72': '石', '\u2F73': '示', '\u2F74': '禸', '\u2F75': '禾',
            '\u2F76': '穴', '\u2F77': '立', '\u2F78': '竹', '\u2F79': '米',
            '\u2F7A': '糸', '\u2F7B': '缶', '\u2F7C': '网', '\u2F7D': '羊',
            '\u2F7E': '羽', '\u2F7F': '老', '\u2F80': '而', '\u2F81': '耒',
            '\u2F82': '耳', '\u2F83': '聿', '\u2F84': '肉', '\u2F85': '臣',
            '\u2F86': '自', '\u2F87': '至', '\u2F88': '臼', '\u2F89': '舌',
            '\u2F8A': '舛', '\u2F8B': '舟', '\u2F8C': '艮', '\u2F8D': '色',
            '\u2F8E': '艸', '\u2F8F': '虍', '\u2F90': '虫', '\u2F91': '血',
            '\u2F92': '行', '\u2F93': '衣', '\u2F94': '襾', '\u2F95': '見',
            '\u2F96': '角', '\u2F97': '言', '\u2F98': '谷', '\u2F99': '豆',
            '\u2F9A': '豕', '\u2F9B': '豸', '\u2F9C': '貝', '\u2F9D': '赤',
            '\u2F9E': '走', '\u2F9F': '足', '\u2FA0': '身', '\u2FA1': '車',
            '\u2FA2': '辛', '\u2FA3': '辰', '\u2FA4': '辵', '\u2FA5': '邑',
            '\u2FA6': '酉', '\u2FA7': '釆', '\u2FA8': '里', '\u2FA9': '金',
            '\u2FAA': '長', '\u2FAB': '門', '\u2FAC': '阜', '\u2FAD': '隶',
            '\u2FAE': '隹', '\u2FAF': '雨', '\u2FB0': '靑', '\u2FB1': '非',
            '\u2FB2': '面', '\u2FB3': '革', '\u2FB4': '韋', '\u2FB5': '韭',
            '\u2FB6': '音', '\u2FB7': '頁', '\u2FB8': '風', '\u2FB9': '飛',
            '\u2FBA': '食', '\u2FBB': '首', '\u2FBC': '香', '\u2FBD': '馬',
            '\u2FBE': '骨', '\u2FBF': '高', '\u2FC0': '髟', '\u2FC1': '鬥',
            '\u2FC2': '鬯', '\u2FC3': '鬲', '\u2FC4': '鬼', '\u2FC5': '魚',
            '\u2FC6': '鳥', '\u2FC7': '鹵', '\u2FC8': '鹿', '\u2FC9': '麥',
            '\u2FCA': '麻', '\u2FCB': '黃', '\u2FCC': '黍', '\u2FCD': '黑',
            '\u2FCE': '黹', '\u2FCF': '黽', '\u2FD0': '鼎', '\u2FD1': '鼓',
            '\u2FD2': '鼠', '\u2FD3': '鼻', '\u2FD4': '齊', '\u2FD5': '齒',
            '\u2FD6': '龍', '\u2FD7': '龜', '\u2FD8': '龠',
        }

        for special_char, normal_char in char_mapping.items():
            text = text.replace(special_char, normal_char)

        return text

    def _remove_chinese_spaces(self, text: str) -> str:
        """移除中文字符之间的多余空格"""
        pattern = r'([\u4e00-\u9fa5])\s+([\u4e00-\u9fa5])'
        while re.search(pattern, text):
            text = re.sub(pattern, r'\1\2', text)
        return text

    def _fix_broken_english(self, text: str) -> str:
        """修复被OCR拆分的英文单词（如 w a t e r -> water）"""
        lines = text.split('\n')
        fixed_lines = []

        for line in lines:
            pattern = r'\b([a-zA-Z])\s+([a-zA-Z])\s+([a-zA-Z])(?:\s+([a-zA-Z]))?(?:\s+([a-zA-Z]))?'

            def replace_func(match):
                chars = [g for g in match.groups() if g]
                if len(chars) >= 3:
                    word = ''.join(chars)
                    if word.lower() in self.common_english_words or len(word) <= 5:
                        return word
                return match.group(0)

            line = re.sub(pattern, replace_func, line)
            fixed_lines.append(line)

        return '\n'.join(fixed_lines)

    def _fix_number_unit_spaces(self, text: str) -> str:
        """修复数字和单位之间的空格"""
        # GB 50268 -> GB50268
        text = re.sub(r'(GB)\s+(\d+)', r'\1\2', text, flags=re.IGNORECASE)
        # 数字 + mm/MPa/m 等单位
        text = re.sub(r'(\d+)\s+(mm|MPa|m|cm|km|kg|℃)', r'\1\2', text, flags=re.IGNORECASE)
        # CJJ 3 - 90 -> CJJ3-90
        text = re.sub(r'(CJJ)\s*(\d+)\s*-\s*(\d+)', r'\1\2-\3', text, flags=re.IGNORECASE)
        return text

    def _fix_punctuation_spaces(self, text: str) -> str:
        """修复标点符号周围的空格"""
        text = re.sub(r'\s+([，。、；：？！"\'（）【】《》])', r'\1', text)
        text = re.sub(r'([（【《"\'\'）】》])\s+', r'\1', text)
        text = re.sub(r'\(\s+', '(', text)
        text = re.sub(r'\s+\)', ')', text)
        return text

    def _clean_extra_whitespace(self, text: str) -> str:
        """清理多余的空行和制表符"""
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = text.replace('\t', ' ')
        lines = text.split('\n')
        lines = [line.rstrip() for line in lines]
        return '\n'.join(lines)


def clean_pdf_text(text: str) -> str:
    """清理 PDF 文本的便捷函数"""
    processor = TextPostProcessor()
    return processor.process(text)
