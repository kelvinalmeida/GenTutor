"""
Alertas de aprendizagem para o professor (TCC, seção 4.4.4).

Um alerta é criado a cada tentativa com menos de 70% de acerto nos exercícios de Reuso.
A criação é disparada pelo Orquestrador no momento da correção (ver
routes/agente_teacher_report.py → POST /sessions/<id>/alerts/low_score).
"""
import logging
import requests

USER_URL = 'http://user:5002'


def _fetch_student_contact(student_id):
    """Retorna (name, email) do aluno ou ('Aluno', '') em caso de falha."""
    try:
        r = requests.get(f"{USER_URL}/students/{student_id}/contact", timeout=8)
        if r.status_code == 200:
            data = r.json()
            return data.get('name', 'Aluno'), data.get('email', '')
    except Exception:
        pass
    return 'Aluno', ''


def _generate_alert_message(client, score, received_material=True):
    """Prompt do APÊNDICE C. Nenhum dado que identifique o aluno é enviado ao LLM."""
    if received_material:
        prompt = (
            f"Gere uma mensagem curta (1-2 frases) para alertar o professor que um aluno recebeu material "
            f"personalizado após uma nota baixa.\n"
            f"Nota obtida: {score}%\n"
            f"Comece com 'Este aluno' e sugira como o professor pode ajudá-lo. Sem formatação."
        )
    else:
        prompt = (
            f"Gere uma mensagem curta (1-2 frases) para alertar o professor que um aluno esgotou as tentativas "
            f"de recuperação com nota baixa e seguiu na sessão.\n"
            f"Nota obtida: {score}%\n"
            f"Comece com 'Este aluno' e sugira como o professor pode ajudá-lo. Sem formatação."
        )
    try:
        resp = client.chat.completions.create(
            model="openai/gpt-oss-120b", extra_body={"reasoning_effort": "low"},
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1200
        )
        content = (resp.choices[0].message.content or "").strip()
        if content:
            return content
    except Exception as e:
        logging.warning("[Alertas] Falha ao gerar mensagem LLM: %s", e)
    if received_material:
        return f"Este aluno recebeu material personalizado após nota de {score}%. Verifique se precisa de suporte adicional."
    return f"Este aluno esgotou as tentativas de recuperação com nota de {score}% e seguiu na sessão. Considere acompanhá-lo de perto."


def migrate_session_alerts_schema(db):
    from sqlalchemy import text
    migrations = [
        """CREATE TABLE IF NOT EXISTS session_alerts (
            id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL,
            student_id INTEGER,
            student_name VARCHAR(255),
            student_email VARCHAR(255),
            alert_type VARCHAR(50) NOT NULL DEFAULT 'low_score',
            concept VARCHAR(255),
            mastery_pct FLOAT,
            score INTEGER,
            answer_id INTEGER,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        "ALTER TABLE session_alerts ADD COLUMN IF NOT EXISTS student_name VARCHAR(255)",
        "ALTER TABLE session_alerts ADD COLUMN IF NOT EXISTS student_email VARCHAR(255)",
        "ALTER TABLE session_alerts ADD COLUMN IF NOT EXISTS alert_type VARCHAR(50) DEFAULT 'low_score'",
        "ALTER TABLE session_alerts ADD COLUMN IF NOT EXISTS score INTEGER",
        "ALTER TABLE session_alerts ADD COLUMN IF NOT EXISTS answer_id INTEGER",
        "ALTER TABLE session_alerts ADD COLUMN IF NOT EXISTS attempt INTEGER",
        "ALTER TABLE session_alerts ADD COLUMN IF NOT EXISTS tactic_index INTEGER",
    ]
    for sql in migrations:
        try:
            db.session.execute(text(sql))
            db.session.commit()
        except Exception:
            db.session.rollback()


def create_low_score_alert(session_id, student_id, score_pct, attempt, tactic_index=None, received_material=True):
    """Cria um alerta de nota baixa (um por tentativa). Deve ser chamado dentro do app context."""
    from app.models import SessionAlert
    from app import db
    from config import Config
    from openai import OpenAI

    migrate_session_alerts_schema(db)

    exists = SessionAlert.query.filter_by(
        session_id=session_id, student_id=student_id, alert_type='low_score',
        tactic_index=tactic_index, attempt=attempt
    ).first()
    if exists:
        return exists, False

    client = OpenAI(api_key=Config.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
    name, email = _fetch_student_contact(student_id)
    msg = _generate_alert_message(client, score_pct, received_material=received_material)

    alert = SessionAlert(
        session_id=session_id,
        student_id=student_id,
        student_name=name,
        student_email=email,
        alert_type='low_score',
        score=score_pct,
        attempt=attempt,
        tactic_index=tactic_index,
        message=msg,
    )
    db.session.add(alert)
    db.session.commit()
    logging.info("[Alertas] Nota baixa: sessão=%s aluno=%s tentativa=%s nota=%s%%",
                 session_id, student_id, attempt, score_pct)
    return alert, True
