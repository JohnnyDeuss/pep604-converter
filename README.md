# pep604-converter
Convert Optionals and Unions in Python code to use pipe syntax, i.e.
`Optional[X]` to `X | None` and `Union[X, Y]` to `X | Y`.

Run at your own risk and please back up your code before running this script.

# Running

`./main.py <directory with .py files>`

Note that the script may leave empty lines where imports have been
removed or where Unions/Optionals span multiple lines. It is recommended
to run `black` and `isort` after conversion.
