import logging
import requests
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

USER_URL = 'http://user:5002'
CONTROL_URL = 'http://agente_sessao:5001'



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


def _generate_alert_message(client, concept, mastery_pct=None, score=None, alert_type='mastery'):
    if alert_type == 'mastery':
        prompt = (
            f"Gere uma mensagem curta (1-2 frases) para alertar o professor sobre a maestria baixa de um aluno.\n"
            f"Conceito: {concept}\nDomínio atual: {mastery_pct:.0f}%\n"
            f"Comece com 'Este aluno' e sugira uma ação pedagógica específica. Sem formatação."
        )
    else:
        prompt = (
            f"Gere uma mensagem curta (1-2 frases) para alertar o professor que um aluno recebeu material "
            f"personalizado após uma nota baixa.\n"
            f"Nota obtida: {score}%\n"
            f"Comece com 'Este aluno' e sugira como o professor pode ajudá-lo. Sem formatação."
        )
    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=120
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logging.warning("[AlertScheduler] Falha ao gerar mensagem LLM: %s", e)
        if alert_type == 'mastery':
            return f"Este aluno está com domínio baixo ({mastery_pct:.0f}%) em '{concept}'. Considere revisar este conceito."
        return f"Este aluno recebeu material personalizado após nota de {score}%. Verifique se precisa de suporte adicional."


def _migrate_session_alerts_schema(db):
    from sqlalchemy import text
    migrations = [
        """CREATE TABLE IF NOT EXISTS session_alerts (
            id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL,
            student_id INTEGER,
            student_name VARCHAR(255),
            student_email VARCHAR(255),
            alert_type VARCHAR(50) NOT NULL DEFAULT 'mastery',
            concept VARCHAR(255),
            mastery_pct FLOAT,
            score INTEGER,
            answer_id INTEGER,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        "ALTER TABLE session_alerts ADD COLUMN IF NOT EXISTS student_name VARCHAR(255)",
        "ALTER TABLE session_alerts ADD COLUMN IF NOT EXISTS student_email VARCHAR(255)",
        "ALTER TABLE session_alerts ADD COLUMN IF NOT EXISTS alert_type VARCHAR(50) DEFAULT 'mastery'",
        "ALTER TABLE session_alerts ADD COLUMN IF NOT EXISTS score INTEGER",
        "ALTER TABLE session_alerts ADD COLUMN IF NOT EXISTS answer_id INTEGER",
    ]
    for sql in migrations:
        try:
            db.session.execute(text(sql))
            db.session.commit()
        except Exception:
            db.session.rollback()


def check_student_mastery_alerts(app):
    with app.app_context():
        from app.models import SessionAlert
        from app import db
        from config import Config
        from openai import OpenAI

        logging.info("[AlertScheduler] Verificando sessões ativas...")

        _migrate_session_alerts_schema(db)

        try:
            sessions_resp = requests.get(f"{CONTROL_URL}/sessions", timeout=15)
            all_sessions = sessions_resp.json() if sessions_resp.status_code == 200 else []
        except Exception as e:
            logging.error("[AlertScheduler] Erro ao buscar sessões: %s", e)
            return

        active_sessions = [s for s in all_sessions if s.get('status') == 'in-progress']
        if not active_sessions:
            return

        if not getattr(Config, 'GROQ_API_KEY', None):
            logging.error("[AlertScheduler] GROQ_API_KEY não configurada")
            return

        client = OpenAI(api_key=Config.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")

        for session in active_sessions:
            session_id = session.get('id')
            student_ids = session.get('students', [])
            verified_answers = session.get('verified_answers', [])

            # ── Gatilho 1: Maestria baixa (≤ 60%) ────────────────────────────
            for student_id in student_ids:
                try:
                    mastery_resp = requests.get(
                        f"{USER_URL}/students/{student_id}/mastery",
                        params={"session_id": session_id},
                        timeout=10
                    )
                    if mastery_resp.status_code != 200:
                        continue

                    for item in mastery_resp.json().get('mastery', []):
                        concept = item.get('concept', '')
                        pct = item.get('mastery_pct', 100)
                        if pct > 60:
                            continue

                        cutoff = datetime.utcnow() - timedelta(minutes=30)
                        exists = SessionAlert.query.filter(
                            SessionAlert.session_id == session_id,
                            SessionAlert.student_id == int(student_id),
                            SessionAlert.concept == concept,
                            SessionAlert.alert_type == 'mastery',
                            SessionAlert.created_at >= cutoff
                        ).first()
                        if exists:
                            continue

                        name, email = _fetch_student_contact(student_id)
                        msg = _generate_alert_message(client, concept, mastery_pct=pct, alert_type='mastery')

                        db.session.add(SessionAlert(
                            session_id=session_id,
                            student_id=int(student_id),
                            student_name=name,
                            student_email=email,
                            alert_type='mastery',
                            concept=concept,
                            mastery_pct=pct,
                            message=msg,
                        ))
                        db.session.commit()
                        logging.info("[AlertScheduler] Alerta maestria: sessão=%s aluno=%s conceito=%s %.0f%%",
                                     session_id, student_id, concept, pct)

                except Exception as e:
                    logging.error("[AlertScheduler] Erro maestria aluno=%s sessão=%s: %s", student_id, session_id, e)
                    db.session.rollback()

            # ── Gatilho 2: Nota baixa < 70% (material personalizado enviado) ──
            for answer in verified_answers:
                try:
                    score_raw = answer.get('score', 0)
                    answers_list = answer.get('answers') or []
                    total_q = len(answers_list) if answers_list else 1
                    score_pct = int((score_raw / total_q) * 100)

                    if score_pct >= 70:
                        continue

                    answer_id = answer.get('id')
                    student_id = answer.get('student_id')

                    # Dedup por answer_id
                    if answer_id:
                        exists = SessionAlert.query.filter_by(
                            answer_id=int(answer_id)
                        ).first()
                        if exists:
                            continue

                    name, email = _fetch_student_contact(student_id)
                    tactic_index = answer.get('tactic_index', '?')
                    msg = _generate_alert_message(client, f"tática {tactic_index}", score=score_pct, alert_type='low_score')

                    db.session.add(SessionAlert(
                        session_id=session_id,
                        student_id=int(student_id) if student_id else None,
                        student_name=name,
                        student_email=email,
                        alert_type='low_score',
                        score=score_pct,
                        answer_id=int(answer_id) if answer_id else None,
                        message=msg,
                    ))
                    db.session.commit()
                    logging.info("[AlertScheduler] Alerta nota baixa: sessão=%s aluno=%s score=%s%%",
                                 session_id, student_id, score_pct)

                except Exception as e:
                    logging.error("[AlertScheduler] Erro nota baixa sessão=%s: %s", session_id, e)
                    db.session.rollback()


def start_scheduler(app):
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        func=lambda: check_student_mastery_alerts(app),
        trigger=IntervalTrigger(minutes=1),
        id='mastery_alerts',
        replace_existing=True
    )
    scheduler.start()
    logging.info("[Scheduler] Iniciado — alertas de nota baixa a cada 1 min")
    return scheduler
