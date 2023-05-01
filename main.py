import os
import sys

from transformer import Transformer


def rewrite_file(full_path):
    print(f"Rewriting {full_path}")
    with open(full_path) as f:
        source = f.read()
    transformer = Transformer(source)
    source = transformer.transform()
    with open(full_path, "w") as f:
        f.write(source)


def main(path: str):
    if not os.path.exists(path):
        raise ValueError(f"{path} not found")
    if os.path.isfile(path):
        rewrite_file(path)
    else:
        for root, _, files in os.walk(path):
            for file in files:
                if os.path.splitext(file)[1] == ".py":
                    full_path = os.path.join(root, file)
                    print(f"Rewriting {full_path}")
                    with open(full_path) as f:
                        source = f.read()
                    transformer = Transformer(source)
                    source = transformer.transform()
                    with open(full_path, "w") as f:
                        f.write(source)


if __name__ == "__main__":
    path = sys.argv[1]
    main(path)
