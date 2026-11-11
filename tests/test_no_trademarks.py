"""The shipped code neither names nor draws other companies' trademarks.

The Game Boy face used to print its maker's name and the console's name on the bezel, and the platform scene named a function after a
game character. The bezel now carries invented words and the rider is a runner. "Game Boy" as the name of a colour style in prose, a
theme list or a file name is allowed (the maintainer's decision); what must not come back is a trademark drawn on a screen, or a
company or character name inside the code.
"""
import ast
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHIPPED = (ROOT / 'token_tv', ROOT / 'firmware/board/src')
TEXT = {'.py', '.js', '.mjs', '.css', '.html', '.json', '.cpp', '.h'}
# Never anywhere in the shipped code, in any case: not in a name, a comment or a string.
NAMED = re.compile(r'nintendo|mario|\bsnes\b', re.IGNORECASE)
# Never drawn: whatever a `.text(...)` call receives is printed on a screen.
DRAWN = re.compile(r'nintendo|game\s*boy|mario', re.IGNORECASE)


class NoTrademarkTests(unittest.TestCase):
    def test_the_shipped_code_never_names_these_brands(self):
        for folder in SHIPPED:
            for path in sorted(folder.rglob('*')):
                if path.is_file() and path.suffix in TEXT:
                    found = NAMED.search(path.read_text(encoding='utf-8', errors='replace'))
                    self.assertIsNone(found, f'{path.relative_to(ROOT)} contains {found and found.group(0)!r}')

    def test_no_screen_draws_a_brand_name(self):
        for path in sorted((ROOT / 'token_tv').rglob('*.py')):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                where = f'{path.relative_to(ROOT)}:{getattr(node, "lineno", 0)}'
                # The bezel used to print the console's name in capitals: that literal is a drawn trademark wherever it is built.
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self.assertNotIn('GAME BOY', node.value, f'{where} has {node.value!r}')
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'text':
                    for part in ast.walk(node):
                        if isinstance(part, ast.Constant) and isinstance(part.value, str):
                            found = DRAWN.search(part.value)
                            self.assertIsNone(found, f'{where} draws {part.value!r}')


if __name__ == '__main__':
    unittest.main()
