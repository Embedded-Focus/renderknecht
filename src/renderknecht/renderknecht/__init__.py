import os
import subprocess

import flask
import httpx
from flask import Flask

from renderers import hugo, pandoc
from util import yaml


def create_app() -> Flask:
    app = Flask(__name__)

    yaml.configure()

    @app.route("/pdf/<pad_id>")
    def render_pad_pdf(pad_id: str) -> flask.Response:
        rsp: httpx.Response | None = None
        tmp_files: pandoc.TemporaryFiles = []
        try:
            rsp = httpx.get(f"http://app:3000/{pad_id}/download")
            rsp.raise_for_status()

            pdf = pandoc.render_markdown(rsp.text, tmp_files)
            response = flask.make_response(pdf, 200)
            response.headers["Content-Type"] = "application/pdf"
            return response
        except subprocess.CalledProcessError as e:
            app.logger.error(f"exitcode = {e.returncode}; {e.output} {e.stderr}")
            return flask.make_response(
                f"""<html>
<head><title>An error occurred ...</title></head>
<p>Exitcode = {e.returncode}</p>
<pre>
{e.output.decode()}
<pre>
{e.stderr.decode()}
</pre>
</html>""",
                500,
            )
        except httpx.HTTPStatusError:
            if not rsp:
                return flask.make_response("Could not obtain response from app.", 500)
            return flask.make_response(rsp.text, rsp.status_code)
        finally:
            for f in tmp_files:
                try:
                    if not f.closed:
                        f.close()
                    os.remove(f.name)
                except OSError as e:
                    app.logger.warning(f"Could not delete {f.name}: {e}")

    @app.route("/hugo/<pad_id>")
    def render_pad_hugo(pad_id: str) -> flask.Response:
        rsp: httpx.Response | None = None
        try:
            rsp = httpx.get(f"http://app:3000/{pad_id}/download")
            rsp.raise_for_status()
        except httpx.HTTPStatusError:
            if not rsp:
                return flask.make_response("Could not obtain response from app.", 500)
            return flask.make_response(rsp.text, rsp.status_code)
        response = flask.make_response(
            hugo.prepare_markdown(rsp.text),
            200,
        )
        # Using text/plain mime-type instead of text/markdown to not show the save to dialog
        response.headers["Content-Type"] = "text/plain; charset=utf-8"
        return response

    return app
