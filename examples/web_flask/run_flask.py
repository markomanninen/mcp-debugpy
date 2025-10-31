"""Runner that imports the Flask app as a package so relative imports work.

This avoids "attempted relative import with no known parent" when running
`examples/web_flask/app.py` directly as a script.
"""

from examples.web_flask import app


if __name__ == "__main__":
    app.main()
