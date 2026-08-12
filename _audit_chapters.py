# -*- coding: utf-8 -*-
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')
os.chdir('seasons/02_city')

samples = [10, 11, 12, 50, 100, 150, 200, 250, 251, 300, 500, 584, 700, 900, 1000]
for n in samples:
    matches = [f for f in os.listdir('.') if f.startswith(f'ch{n:03d}-')]
    if matches:
        with open(matches[0], 'r', encoding='utf-8') as f:
            content = f.read()
        lines = content.count('\n')
        chars = len(content)
        print(f'ch{n:04d}: {matches[0]} | {lines} lines | {chars} chars')
    else:
        print(f'ch{n:04d}: NOT FOUND')
