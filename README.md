# PEP 604 typing converter
Convert Optionals and Unions in Python code to use pipe syntax, i.e.
`Optional[X]` to `X | None` and `Union[X, Y]` to `X | Y`, as introduced
in in Python 3.10 with [PEP 604](https://peps.python.org/pep-0604/).

Run at your own risk and please back up your code before running this script.

# Running

`python main.py <directory with .py files>`

Note that the script may leave empty lines where imports have been
removed or where Unions/Optionals span multiple lines. It is recommended
to run `black` and `isort` after conversion.
