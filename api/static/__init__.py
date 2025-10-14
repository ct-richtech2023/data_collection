import os

CURRENT_DIR = os.path.dirname(__file__)


class SwaggerUIFileNames:
    favicon = 'favicon.png'
    css = 'swagger-ui.css'
    js = 'swagger-ui-bundle.js'


class SwaggerUIFiles:
    current_dir = CURRENT_DIR
    favicon = os.path.join(CURRENT_DIR, SwaggerUIFileNames.favicon)
    css = os.path.join(CURRENT_DIR, SwaggerUIFileNames.css)
    js = os.path.join(CURRENT_DIR, SwaggerUIFileNames.js)
