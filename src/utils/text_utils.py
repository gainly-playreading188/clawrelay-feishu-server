"""
文本处理工具模块
"""

import re
import logging

logger = logging.getLogger(__name__)


def clean_think_tags(text: str) -> str:
    """清理<think>标签内的markdown格式"""
    def clean_content(match):
        opening_tag = match.group(1)
        content = match.group(2)
        lines = content.split('\n')
        cleaned_lines = []
        for line in lines:
            if '|' in line:
                stripped = line.strip()
                if re.match(r'^[\|\-\s]+$', stripped):
                    continue
                else:
                    cells = [cell.strip() for cell in stripped.split('|') if cell.strip()]
                    if cells:
                        cell_text = re.sub(r'\*\*([^*]+)\*\*', r'\1', cells[0])
                        cleaned_lines.append(cell_text)
                    continue
            line = re.sub(r'\*\*([^*]+)\*\*', r'\1', line)
            line = re.sub(r'<[^>]+>', '', line)
            if line or not line.strip():
                cleaned_lines.append(line)
        cleaned_content = '\n'.join(cleaned_lines)
        cleaned_content = re.sub(r'\n{3,}', '\n\n', cleaned_content)
        return f"{opening_tag}{cleaned_content}</think>"

    pattern = r'(<think[^>]*>)(.*?)(</think>)'
    return re.sub(pattern, clean_content, text, flags=re.DOTALL)


def remove_think_tags(text: str) -> str:
    """完全移除<think>标签及其内容"""
    pattern = r'<think[^>]*>.*?</think>'
    result = re.sub(pattern, '', text, flags=re.DOTALL)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()
