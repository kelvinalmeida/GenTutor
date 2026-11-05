import logging
import os
import requests
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from openai import OpenAI

CONTROL_URL = 'http://agente_sessao:5001'
DOMAIN_URL = 'http://domain:5004'
STRATEGIES_URL = 'http://strategies:5003'

PROACTIVE_COOLDOWN_MINUTES = 5


def _ensure_tables(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tutor_chat_history (
                id SERIAL PRIMARY KEY,
                student_username VARCHAR(100) NOT NULL,
                sender VARCHAR(20) NOT NULL,
                message TEXT NOT NULL,
                session_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            ALTER TABLE tutor_chat_history
            ADD COLUMN IF NOT EXISTS session_id INTEGER
        """)
    conn.commit()


def _get_tactic_domain_id(session_id, student_id, session):
    """Retorna o domain_id da tática ativa do aluno (fallback quando sessão não tem domínio)."""
    try:
        strategy_ids = session.get('strategies', [])
        if not strategy_ids:
            return None

        prog = requests.get(
            f"{CONTROL_URL}/sessions/{session_id}/student/{student_id}/tactic_index",
            timeout=6
        )
        tactic_index = prog.json().get('current_tactic_index', 0) if prog.status_code == 200 else 0

        strat = requests.get(f"{STRATEGIES_URL}/strategies/{strategy_ids[0]}", timeout=6)
        if strat.status_code != 200:
            return None
        tactics = strat.json().get('tatics', [])
        if tactic_index < len(tactics):
            return tactics[tactic_index].get('domain_id')
    except Exception:
        pass
    return None


def _get_domain_info(domain_ids):
    """Returns (name, description) for the first domain in the list."""
    if not domain_ids:
        return '', ''
    try:
        resp = requests.get(
            f"{DOMAIN_URL}/domains/ids_to_names",
            params={'ids': domain_ids},
            timeout=8
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and data:
                first = data[0]
                if isinstance(first, dict):
                    return first.get('name', ''), first.get('description', '')
                return str(first), ''
            if isinstance(data, dict):
                first = next(iter(data.values()), {})
                if isinstance(first, dict):
                    return first.get('name', ''), first.get('description', '')
    except Exception:
        pass
    return '', ''


def _generate_tip(client, domain_name, domain_desc, pref_content_type):
    """Gera um mini-conteúdo educativo sobre o domínio da sessão via LLM."""
    topic = domain_name or 'conteúdo da sessão'
    desc_line = f"\nDescrição do domínio: {domain_desc[:200]}" if domain_desc else ''
    pref_line = f"\nPreferência de conteúdo: {pref_content_type}." if pref_content_type else ''

    prompt = f"""Você é um tutor educacional gerando mini-conteúdo para uma sessão sobre "{topic}".{desc_line}{pref_line}

Gere um MINI-CONTEÚDO EDUCATIVO (máximo 150 palavras) que ajude o estudante a entender melhor o que está sendo ensinado:
- Explique um conceito central do tema "{topic}" com linguagem clara e acessível
- Use um exemplo prático ou analogia do cotidiano para ilustrar o conceito
- Termine com uma pergunta reflexiva para estimular o raciocínio
- NUNCA revele respostas de exercícios ou gabaritos
- Use sempre "você" (nunca o nome do aluno)
- Sem markdown, sem JSON, apenas texto corrido"""

    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "Você escreve mini-conteúdos educativos claros e didáticos. Nunca revela gabaritos."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.5,
            max_tokens=250
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logging.warning("[ProactiveScheduler] Falha ao gerar conteúdo LLM: %s", e)
        return f"Vamos aprofundar o tema '{topic}'? Pense em como esse conteúdo se aplica no seu dia a dia e tente formular uma pergunta sobre o que ainda não ficou claro."


def send_proactive_tips(app):
    with app.app_context():
        from config import Config

        try:
            from db import create_connection
        except ImportError:
            logging.error("[ProactiveScheduler] Não foi possível importar create_connection")
            return

        db_url = os.getenv('DATABASE_URL')

        # 1. Buscar sessões ativas
        try:
            resp = requests.get(f"{CONTROL_URL}/sessions", timeout=15)
            all_sessions = resp.json() if resp.status_code == 200 else []
        except Exception as e:
            logging.error("[ProactiveScheduler] Erro ao buscar sessões: %s", e)
            return

        active_sessions = [s for s in all_sessions if s.get('status') == 'in-progress']
        if not active_sessions:
            return

        if not getattr(Config, 'GROQ_API_KEY', None):
            logging.error("[ProactiveScheduler] GROQ_API_KEY não configurada")
            return

        client = OpenAI(api_key=Config.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")

        conn = create_connection(db_url)
        if not conn:
            logging.error("[ProactiveScheduler] Falha na conexão com o banco")
            return

        try:
            _ensure_tables(conn)

            for session in active_sessions:
                session_id = session.get('id')
                student_ids = session.get('students', [])
                domain_ids = session.get('domains', [])

                session_domain_name, session_domain_desc = _get_domain_info(domain_ids)

                for student_id in student_ids:
                    try:
                        with conn.cursor() as cur:
                            cur.execute("""
                                SELECT username, pref_content_type
                                FROM student WHERE student_id = %s
                            """, (int(student_id),))
                            student_row = cur.fetchone()

                        if not student_row:
                            continue

                        username = student_row['username']
                        pref = student_row.get('pref_content_type', '') or ''

                        # Dedup: pular se última dica foi há menos de COOLDOWN minutos
                        with conn.cursor() as cur:
                            cur.execute("""
                                SELECT created_at FROM tutor_chat_history
                                WHERE student_username = %s
                                  AND session_id = %s
                                  AND sender = 'proactive'
                                ORDER BY created_at DESC LIMIT 1
                            """, (username, session_id))
                            last_row = cur.fetchone()

                        if last_row:
                            last_time = last_row['created_at']
                            if datetime.utcnow() - last_time < timedelta(minutes=PROACTIVE_COOLDOWN_MINUTES):
                                continue

                        # Usa domínio da sessão; se vazio, busca da tática ativa do aluno
                        domain_name = session_domain_name
                        domain_desc = session_domain_desc
                        if not domain_name:
                            tactic_domain_id = _get_tactic_domain_id(session_id, student_id, session)
                            if tactic_domain_id:
                                domain_name, domain_desc = _get_domain_info([tactic_domain_id])

                        tip = _generate_tip(client, domain_name, domain_desc, pref)

                        with conn.cursor() as cur:
                            cur.execute("""
                                INSERT INTO tutor_chat_history
                                    (student_username, sender, message, session_id)
                                VALUES (%s, 'proactive', %s, %s)
                            """, (username, tip, session_id))
                        conn.commit()

                        logging.info(
                            "[ProactiveScheduler] Dica enviada — aluno=%s sessão=%s",
                            username, session_id
                        )

                    except Exception as e:
                        logging.error(
                            "[ProactiveScheduler] Erro — student_id=%s sessão=%s: %s",
                            student_id, session_id, e
                        )
                        try:
                            conn.rollback()
                        except Exception:
                            pass

        finally:
            conn.close()


def start_scheduler(app):
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        func=lambda: send_proactive_tips(app),
        trigger=IntervalTrigger(minutes=1),
        id='proactive_tips',
        replace_existing=True
    )
    scheduler.start()
    logging.info(
        "[ProactiveScheduler] Iniciado — verifica sessões a cada 1 min "
        "(cooldown de %d min por aluno)", PROACTIVE_COOLDOWN_MINUTES
    )
    return scheduler
