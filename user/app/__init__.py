import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from dotenv import load_dotenv  # 1. Importe o load_dotenv

db = SQLAlchemy()
migrate = Migrate()

def create_app():
    app = Flask(__name__)


    # load_dotenv(os.path.join(os.getcwd(), 'config.env'))

    
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///../instance/users.db") 
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config['SECRET_KEY'] = 'sua_chave_super_secreta'

    db.init_app(app)
    migrate.init_app(app, db)

    from .routes.students_routes import student_bp
    from .routes.teachers_routes import teachers_bp
    from .routes.login import auth_bp
    from .routes.agente_user_routes import agente_user_bp
    from .routes.agente_proactive_routes import agente_proactive_bp

    app.register_blueprint(student_bp)
    app.register_blueprint(teachers_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(agente_user_bp)
    app.register_blueprint(agente_proactive_bp)

    # Inicia scheduler apenas uma vez (evita duplicação no reload do Werkzeug)
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        from app.scheduler import start_scheduler
        start_scheduler(app)

    return app
