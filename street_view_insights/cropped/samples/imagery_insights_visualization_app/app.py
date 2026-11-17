# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from flask import Flask, abort, render_template, send_from_directory
import os

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['TEMPLATES_AUTO_RELOAD'] = False

ALLOWED_DATA_FILES = frozenset({'ga_sample.json'})

_CONTEXT = {
    'maps_api_key': os.getenv('MAPS_API_KEY', '')
}


@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response


@app.route('/')
def index():
    return render_template('index.html', **_CONTEXT)


@app.route('/3d_view')
def three_d_view():
    return render_template('3d_view.html', **_CONTEXT)


@app.route('/data/<filename>')
def get_data(filename):
    if filename not in ALLOWED_DATA_FILES:
        abort(404)
    return send_from_directory('data', filename)


if __name__ == '__main__':
    app.run(
        debug=False,
        host=os.environ.get('HOST', '127.0.0.1'),
        port=int(os.environ.get('PORT', '8080')),
    )
