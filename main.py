import os
import sys

from transformer import Transformer

path = sys.argv[1]

if not os.path.exists(path):
    raise ValueError(f"{path} not found")


def rewrite_file(full_path):
    print(f"Rewriting {full_path}")
    with open(full_path) as f:
        source = f.read()
    transformer = Transformer()
    source = transformer.transform(source)
    with open(full_path, "w") as f:
        f.write(source)


if os.path.isfile(path):
    rewrite_file(path)
else:
    for root, dirs, files in os.walk(path):
        for file in files:
            if os.path.splitext(file)[1] == ".py":
                full_path = os.path.join(root, file)
                print(f"Rewriting {full_path}")
                with open(full_path) as f:
                    source = f.read()
                transformer = Transformer()
                source = transformer.transform(source)
                with open(full_path, "w") as f:
                    f.write(source)
