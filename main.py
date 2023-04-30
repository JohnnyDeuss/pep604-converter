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
            for i in count(1):
                transformer = Transformer()
                source = transformer.transform(source, file)
                if not transformer.has_changes:
                    break
            re.sub(r"(\s+\\$)+\s+", "", source)
            with open(full_path, "w") as f:
                f.write(source)
