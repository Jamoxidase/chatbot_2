from flask import Flask
from flask_cors import CORS
from routes import register_routes

from config import Config

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    CORS(app, resources={r"/api/*": {"origins": ["http://localhost:3000", "http://127.0.0.1:5500", "http://localhost:5500","http://localhost:*", "file://*"]}})
    
    register_routes(app)
    
    return app

if __name__ == '__main__':
    app = create_app()
    app.run(host='127.0.0.1', port=8080, debug=False)

    