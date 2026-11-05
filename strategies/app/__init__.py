from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import os
from config import Config
from dotenv import load_dotenv

db = SQLAlchemy()
migrate = Migrate()


def create_app():
    app = Flask(__name__, instance_relative_config=True)

    load_dotenv(os.path.join(os.getcwd(), 'config.env'))

    app.config.from_object(Config)
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///../instance/users.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config['SECRET_KEY'] = 'sua_chave_super_secreta'

    from app.routes.strategies_routes import strategies_bp
    from app.routes.agente_strategies_routes import agente_strategies_bp
    from app.routes.agente_perso_individual import agente_perso_individual_bp
    from app.routes.agente_adaptive_tactic_routes import agente_adaptive_tactic_bp
    from app.routes.agente_plan_routes import agente_plan_bp
    from app.routes.agente_teacher_report import agente_teacher_report_bp

    app.register_blueprint(strategies_bp)
    app.register_blueprint(agente_strategies_bp)
    app.register_blueprint(agente_perso_individual_bp)
    app.register_blueprint(agente_adaptive_tactic_bp)
    app.register_blueprint(agente_plan_bp)
    app.register_blueprint(agente_teacher_report_bp)

    db.init_app(app)
    migrate.init_app(app, db)

    # Registra modelos com o SQLAlchemy (necessário para queries ORM funcionarem)
    from app import models  # noqa: F401

    # Cria tabelas novas que ainda não existem no banco.
    # Wrapped em try/except pois o PostgreSQL pode não estar pronto no startup.
    with app.app_context():
        try:
            db.create_all()
        except Exception as e:
            import logging
            logging.warning("db.create_all() falhou — DB pode não estar pronto ainda: %s", e)
        try:
            from sqlalchemy import text
            db.session.execute(text("ALTER TABLE tactics ADD COLUMN IF NOT EXISTS domain_id INTEGER"))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # Inicia scheduler apenas uma vez (evita duplicação no reload do Werkzeug)
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        from app.scheduler import start_scheduler
        start_scheduler(app)

    return app
