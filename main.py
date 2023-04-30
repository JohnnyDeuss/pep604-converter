import ast
import os
import re
import sys
from itertools import count

from transformer import Transformer

for root, dirs, files in os.walk(sys.argv[1]):
    for file in files:
        if os.path.splitext(file)[1] == ".py":
            full_path = os.path.join(root, file)
            print(f"Rewriting {full_path}")
            with open(full_path) as f:
                source = f.read()
            transformer = Transformer()
            source = transformer.transform(source)
            re.sub(r"(\s+\\$)+\s+", "", source)
            with open(full_path, "w") as f:
                f.write(source)
