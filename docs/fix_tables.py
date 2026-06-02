#!/usr/bin/env python3
"""
Post-process pandoc-generated LaTeX to fix table column widths.
Converts 'l' columns to 'p{width}'\texttt{} for proportional wrapping.

Usage: python3 fix_tables.py < input.tex > output.tex
"""

import re
import sys


def fix_longtable(match):
    """Fix a longtable environment with proper column widths."""
    prefix = match.group('prefix')  # e.g., @{}
    colspec = match.group('spec')  # e.g., llll or lll
    suffix = match.group('suffix')  # e.g., @{}

    col_count = len(colspec)
    textwidth = r'\textwidth'
    tabcolsep = r'\tabcolsep'

    if col_count == 3:
        # For 3-column tables: 编号(12%) | 缺失项(28%) | 说明(60%)
        # Or similar proportions
        widths = [0.12, 0.28, 0.60]
    elif col_count == 4:
        # For 4-column tables: 编号(8%) | 缺失项(20%) | 位置(28%) | 说明(44%)
        widths = [0.08, 0.20, 0.28, 0.44]
    else:
        # Default: equal widths
        widths = [1.0 / col_count] * col_count

    new_cols = []
    for w in widths:
        new_cols.append(r'>{\raggedright\arraybackslash}p{' + f'{w:.4f}{textwidth}' + '}')

    new_spec = ''.join(new_cols)
    return f'\\begin{{longtable}}{{{prefix}{new_spec}{suffix}}}'


def fix_longtable_headers(match):
    """Fix headers that span multiple columns to use proper width hints."""
    return match.group(0)  # keep as-is for now


def process_latex(content):
    """Process LaTeX content to fix table column widths."""
    # Pattern: \begin{longtable}[]{@{}lll@{}}
    pattern = re.compile(
        r'\\begin\{longtable\}\[\]\{(?P<prefix>@{})'
        r'(?P<spec>l+)(?P<suffix>@{})\}'
    )
    content = pattern.sub(fix_longtable, content)
    return content


if __name__ == '__main__':
    content = sys.stdin.read()
    fixed = process_latex(content)
    sys.stdout.write(fixed)
