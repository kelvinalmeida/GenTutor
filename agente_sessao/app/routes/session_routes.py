import logging
import sys
import json
import random
import string
import os
from flask import Blueprint, request, jsonify, current_app
from datetime import datetime
from contextlib import contextmanager

try:
    from db import create_connection
except ImportError:
    from ...db import create_connection

session_bp = Blueprint('session_bp', __name__)

# Regra da etapa de avaliação (TCC, seção 4.4.2): 70% de acerto para avançar.
# Cada falha gera um material de recuperação (Quadro 2: 1ª, 2ª e 3ª abordagens) e nova tentativa.
# Se o aluno ainda tirar nota baixa depois do 3º material, ele deixa o ciclo e segue na sessão.
PASS_THRESHOLD = 0.7
MAX_RECOVERY_CYCLES = 3

def generate_unique_code(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

@contextmanager
def get_db_connection():
    db_url = current_app.config.get("SQLALCHEMY_DATABASE_URI") or os.getenv("DATABASE_URL")
    conn = create_connection(db_url)
    if conn is None:
        raise Exception("Failed to connect to database")
    try:
        yield conn
    finally:
        conn.close()

def ensure_rating_tables(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS session_ratings (
                id SERIAL PRIMARY KEY,
                session_id INTEGER NOT NULL,
                student_id VARCHAR(50) NOT NULL,
                rating INTEGER NOT NULL,
                CONSTRAINT fk_rating_session FOREIGN KEY (session_id) REFERENCES session(id) ON DELETE CASCADE,
                UNIQUE(session_id, student_id)
            );
        """)
        try:
            cur.execute("ALTER TABLE session ADD COLUMN IF NOT EXISTS rating_average FLOAT DEFAULT 0.0")
            cur.execute("ALTER TABLE session ADD COLUMN IF NOT EXISTS rating_count INTEGER DEFAULT 0")
        except Exception as e:
            conn.rollback()
            logging.warning(f"Columns ensure error (ignored): {e}")
        conn.commit()

def get_session_details(conn, session_id):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM session WHERE id = %s", (session_id,))
        session = cur.fetchone()

        if not session:
            return None

        cur.execute("SELECT strategy_id FROM session_strategies WHERE session_id = %s", (session_id,))
        strategies = [row['strategy_id'] for row in cur.fetchall()]

        cur.execute("SELECT teacher_id FROM session_teachers WHERE session_id = %s", (session_id,))
        teachers = [row['teacher_id'] for row in cur.fetchall()]

        cur.execute("SELECT student_id FROM session_students WHERE session_id = %s", (session_id,))
        students = [row['student_id'] for row in cur.fetchall()]

        cur.execute("SELECT domain_id FROM session_domains WHERE session_id = %s", (session_id,))
        domains = [row['domain_id'] for row in cur.fetchall()]

        cur.execute("SELECT * FROM verified_answers WHERE session_id = %s", (session_id,))
        verified_answers = cur.fetchall()

        cur.execute("SELECT * FROM extra_notes WHERE session_id = %s", (session_id,))
        extra_notes = cur.fetchall()

        session_dict = dict(session)
        session_dict['use_agent'] = session.get('use_agent', False)
        session_dict['end_on_next_completion'] = session.get('end_on_next_completion', False)

        # Rating fields might not be in dict if row factory doesn't include them yet (lazy migration)
        # But 'dict(session)' from RealDictCursor should include them if columns exist.
        # We handle defaults just in case
        session_dict['rating_average'] = session.get('rating_average', 0.0)
        session_dict['rating_count'] = session.get('rating_count', 0)
        session_dict['adaptive_tactic_enabled'] = session.get('adaptive_tactic_enabled', False)
        rc = session.get('reuso_cooldown_enabled')
        session_dict['reuso_cooldown_enabled'] = True if rc is None else bool(rc)

        try:
            session_dict['executed_indices'] = json.loads(session.get('executed_indices', '[]'))
        except:
            session_dict['executed_indices'] = []

        session_dict['strategies'] = strategies
        session_dict['teachers'] = teachers
        session_dict['students'] = students
        session_dict['domains'] = domains
        session_dict['verified_answers'] = [dict(va) for va in verified_answers]
        session_dict['extra_notes'] = [dict(en) for en in extra_notes]

        return session_dict

def ensure_student_progress_table(conn):
    # Create table
    with conn.cursor() as cur:
        try:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS student_session_progress (
                    session_id INTEGER NOT NULL,
                    student_id VARCHAR(50) NOT NULL,
                    current_tactic_index INTEGER DEFAULT 0,
                    PRIMARY KEY (session_id, student_id),
                    CONSTRAINT fk_progress_session
                        FOREIGN KEY (session_id) REFERENCES session (id) ON DELETE CASCADE
                )
            """)
            conn.commit()
        except Exception as e:
            conn.rollback()
            logging.warning(f"Note on create student_session_progress: {e}")

    # Each migration is independent so a pre-existing column never blocks newer ones
    _run_migration(conn, "ALTER TABLE verified_answers ADD COLUMN IF NOT EXISTS tactic_index INTEGER NOT NULL DEFAULT 0")
    _run_migration(conn, "ALTER TABLE verified_answers ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 1")
    _run_migration(conn, "ALTER TABLE verified_answers ADD COLUMN IF NOT EXISTS score_history JSONB NOT NULL DEFAULT '[]'::jsonb")
    _run_migration(conn, "ALTER TABLE student_session_progress ADD COLUMN IF NOT EXISTS tactic_started_at TIMESTAMP")
    _run_migration(conn, "ALTER TABLE student_session_progress ADD COLUMN IF NOT EXISTS student_started BOOLEAN DEFAULT TRUE")
    _run_migration(conn, "ALTER TABLE student_session_progress ADD COLUMN IF NOT EXISTS should_end_session BOOLEAN DEFAULT FALSE")
    _run_migration(conn, "ALTER TABLE student_session_progress ADD COLUMN IF NOT EXISTS executed_tactic_indices TEXT DEFAULT '[]'")
    _run_migration(conn, "ALTER TABLE student_session_progress ADD COLUMN IF NOT EXISTS session_plan TEXT DEFAULT NULL")
    # Unique constraint needed for ON CONFLICT (student_id, session_id, tactic_index) in submit_answer
    _run_migration(conn, "ALTER TABLE verified_answers ADD CONSTRAINT uq_verified_answers_student_session_tactic UNIQUE (student_id, session_id, tactic_index)")


def _run_migration(conn, sql):
    with conn.cursor() as cur:
        try:
            cur.execute(sql)
            conn.commit()
        except Exception as e:
            conn.rollback()
            logging.warning(f"Migration note ({sql[:60]}...): {e}")

def ensure_end_flag_column(conn):
    with conn.cursor() as cur:
        try:
            cur.execute("ALTER TABLE session ADD COLUMN IF NOT EXISTS end_on_next_completion BOOLEAN DEFAULT FALSE")
            conn.commit()
        except Exception as e:
            conn.rollback()
            logging.warning(f"Note on ensure_end_flag_column: {e}")

def ensure_executed_indices_column(conn):
    with conn.cursor() as cur:
        try:
            cur.execute("ALTER TABLE session ADD COLUMN IF NOT EXISTS executed_indices TEXT DEFAULT '[]'")
            conn.commit()
        except Exception as e:
            conn.rollback()
            logging.warning(f"Note on ensure_executed_indices_column: {e}")

def ensure_adaptive_tactic_column(conn):
    with conn.cursor() as cur:
        try:
            cur.execute("ALTER TABLE session ADD COLUMN IF NOT EXISTS adaptive_tactic_enabled BOOLEAN DEFAULT FALSE")
            cur.execute("ALTER TABLE session ADD COLUMN IF NOT EXISTS reuso_cooldown_enabled BOOLEAN DEFAULT TRUE")
            conn.commit()
        except Exception as e:
            conn.rollback()
            logging.warning(f"Note on ensure_adaptive_tactic_column: {e}")

def update_executed_indices(conn, session_id):
    with conn.cursor() as cur:
        cur.execute("SELECT current_tactic_index, executed_indices FROM session WHERE id = %s", (session_id,))
        row = cur.fetchone()

        if row:
            current_idx = row['current_tactic_index']
            try:
                history = json.loads(row['executed_indices'] or '[]')
            except:
                history = []

            if not history or history[-1] != current_idx:
                history.append(current_idx)

            cur.execute("UPDATE session SET executed_indices = %s WHERE id = %s", (json.dumps(history), session_id))
            conn.commit()

def _end_session(conn, session_id):
    with conn.cursor() as cur:
        cur.execute("SELECT id, original_strategy_id FROM session WHERE id = %s", (session_id,))
        session = cur.fetchone()
        if not session:
            return False

        if session.get('original_strategy_id'):
            original_strategy_id = session['original_strategy_id']
            cur.execute("DELETE FROM session_strategies WHERE session_id = %s", (session_id,))
            cur.execute("INSERT INTO session_strategies (session_id, strategy_id) VALUES (%s, %s)",
                       (session_id, str(original_strategy_id)))

            cur.execute("UPDATE session SET status = 'finished', original_strategy_id = NULL WHERE id = %s", (session_id,))
        else:
            cur.execute("UPDATE session SET status = 'finished' WHERE id = %s", (session_id,))

        conn.commit()
    return True

@session_bp.route('/sessions/<int:session_id>/set_end_flag', methods=['POST'])
def set_end_flag(session_id):
    with get_db_connection() as conn:
        ensure_end_flag_column(conn)
        with conn.cursor() as cur:
             cur.execute("UPDATE session SET end_on_next_completion = TRUE WHERE id = %s", (session_id,))
             conn.commit()
    return jsonify({"success": True}), 200

@session_bp.route('/sessions/create', methods=['POST'])
def create_session():
    data = request.get_json()
    strategies = data.get('strategies', [])
    teachers = data.get('teachers', [])
    students = data.get('students', [])
    domains = data.get('domains', [])

    if not strategies:
        return jsonify({"error": "Strategies not provided"}), 400

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            while True:
                code = generate_unique_code()
                cur.execute("SELECT 1 FROM session WHERE code = %s", (code,))
                if not cur.fetchone():
                    break

            cur.execute("""
                INSERT INTO session (status, code, current_tactic_index)
                VALUES (%s, %s, %s)
                RETURNING id
            """, ('aguardando', code, 0))
            session_id = cur.fetchone()['id']

            if strategies:
                cur.executemany("INSERT INTO session_strategies (session_id, strategy_id) VALUES (%s, %s)",
                                [(session_id, str(s)) for s in strategies])
            if teachers:
                cur.executemany("INSERT INTO session_teachers (session_id, teacher_id) VALUES (%s, %s)",
                                [(session_id, str(t)) for t in teachers])
            if students:
                cur.executemany("INSERT INTO session_students (session_id, student_id) VALUES (%s, %s)",
                                [(session_id, str(s)) for s in students])
            if domains:
                cur.executemany("INSERT INTO session_domains (session_id, domain_id) VALUES (%s, %s)",
                                [(session_id, str(d)) for d in domains])

            conn.commit()

    return jsonify({"success": "Session created!"}), 200

@session_bp.route('/sessions', methods=['GET'])
def list_sessions():
    with get_db_connection() as conn:
        ensure_rating_tables(conn) # Ensure tables exist when listing (lazy init)
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM session")
            rows = cur.fetchall()

            all_sessions = []
            for row in rows:
                details = get_session_details(conn, row['id'])
                if details:
                    all_sessions.append(details)

    return jsonify(all_sessions)

@session_bp.route('/sessions/<int:session_id>', methods=['GET'])
def get_session_by_id(session_id):
    with get_db_connection() as conn:
        ensure_rating_tables(conn)
        ensure_adaptive_tactic_column(conn)
        session_dict = get_session_details(conn, session_id)

    if session_dict:
        return jsonify(session_dict), 200
        
    return jsonify({"error": "Session not found"}), 404
    

@session_bp.route('/sessions/delete/<int:session_id>', methods=['DELETE']) 
def delete_session(session_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM session WHERE id = %s", (session_id,))
            if not cur.fetchone():
                return jsonify({"error": "Session not found"}), 404

            cur.execute("DELETE FROM session WHERE id = %s", (session_id,))
            conn.commit()

    return jsonify({"success": "Session deleted!"}), 200

@session_bp.route('/sessions/status/<int:session_id>', methods=['GET'])
def get_session_status(session_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, status FROM session WHERE id = %s", (session_id,))
            session = cur.fetchone()

    if session:
        return jsonify({"session_id": session['id'], "status": session['status']})
    return jsonify({"error": "Session not found"}), 404


@session_bp.route('/sessions/start/<int:session_id>', methods=['POST'])
def start_session(session_id):
    data = request.get_json() or {}
    use_agent = data.get('use_agent', False)

    with get_db_connection() as conn:
        ensure_end_flag_column(conn)
        ensure_executed_indices_column(conn)
        ensure_adaptive_tactic_column(conn)
        ensure_student_progress_table(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM session WHERE id = %s", (session_id,))
            if not cur.fetchone():
                return jsonify({"error": "Session not found"}), 404

            start_time = datetime.utcnow()
            cur.execute("""
                UPDATE session
                SET status = 'in-progress', start_time = %s, current_tactic_index = 0, current_tactic_started_at = %s, use_agent = %s, end_on_next_completion = FALSE, executed_indices = '[]'
                WHERE id = %s
                RETURNING status, start_time
            """, (start_time, start_time, use_agent, session_id))
            updated = cur.fetchone()

            # Inicializa progresso individual de cada aluno (aguardando o aluno clicar em "Iniciar")
            cur.execute("SELECT student_id FROM session_students WHERE session_id = %s", (session_id,))
            for row in cur.fetchall():
                cur.execute("""
                    INSERT INTO student_session_progress (session_id, student_id, current_tactic_index, tactic_started_at, student_started, executed_tactic_indices)
                    VALUES (%s, %s, 0, NULL, FALSE, '[]')
                    ON CONFLICT (session_id, student_id) DO UPDATE
                    SET current_tactic_index = 0, tactic_started_at = NULL, student_started = FALSE, executed_tactic_indices = '[]'
                """, (session_id, row['student_id']))

            conn.commit()

    return jsonify({
        "session_id": session_id,
        "status": updated['status'],
        "start_time": updated['start_time'].isoformat(),
        "use_agent": use_agent
    })


@session_bp.route('/sessions/end/<int:session_id>', methods=['POST'])
def end_session(session_id):
    with get_db_connection() as conn:
        success = _end_session(conn, session_id)
        if not success:
             return jsonify({"error": "Session not found"}), 404

    return jsonify({"session_id": session_id, "message": "Session ended!"})


@session_bp.route('/sessions/<int:session_id>/temp_switch_strategy', methods=['POST'])
def temp_switch_strategy(session_id):
    data = request.get_json()
    new_strategy_id = data.get('strategy_id')

    if not new_strategy_id:
        return jsonify({"error": "Strategy ID is required"}), 400

    with get_db_connection() as conn:
        ensure_end_flag_column(conn)
        ensure_executed_indices_column(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT id, original_strategy_id FROM session WHERE id = %s", (session_id,))
            session = cur.fetchone()
            if not session:
                return jsonify({"error": "Session not found"}), 404

            if not session['original_strategy_id']:
                cur.execute("SELECT strategy_id FROM session_strategies WHERE session_id = %s", (session_id,))
                rows = cur.fetchall()
                if rows:
                    current_strategy_id = rows[0]['strategy_id']
                    cur.execute("UPDATE session SET original_strategy_id = %s WHERE id = %s", (current_strategy_id, session_id))

            cur.execute("DELETE FROM session_strategies WHERE session_id = %s", (session_id,))
            cur.execute("INSERT INTO session_strategies (session_id, strategy_id) VALUES (%s, %s)", (session_id, str(new_strategy_id)))

            start_time = datetime.utcnow()
            cur.execute("""
                UPDATE session
                SET current_tactic_index = 0,
                    current_tactic_started_at = %s,
                    end_on_next_completion = FALSE,
                    executed_indices = '[]'
                WHERE id = %s
            """, (start_time, session_id))

            conn.commit()

    return jsonify({"success": "Strategy temporarily switched!"}), 200


@session_bp.route('/sessions/tactic/next/<int:session_id>', methods=['POST'])
def next_tactic(session_id):
    with get_db_connection() as conn:
        ensure_executed_indices_column(conn)

        end_flag = False
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT end_on_next_completion FROM session WHERE id = %s", (session_id,))
                res = cur.fetchone()
                if res and res.get('end_on_next_completion'):
                    end_flag = True
            except Exception:
                conn.rollback()

        if end_flag:
            _end_session(conn, session_id)
            return jsonify({"success": True, "session_status": "finished", "message": "Session ended by rule."})

        update_executed_indices(conn, session_id)

        with conn.cursor() as cur:
            cur.execute("SELECT id, current_tactic_index FROM session WHERE id = %s", (session_id,))
            session = cur.fetchone()
            if not session:
                return jsonify({"error": "Session not found"}), 404

            new_index = session['current_tactic_index'] + 1
            now = datetime.utcnow()

            cur.execute("""
                UPDATE session
                SET current_tactic_index = %s, current_tactic_started_at = %s
                WHERE id = %s
            """, (new_index, now, session_id))
            conn.commit()

    return jsonify({"success": True, "current_tactic_index": new_index})


@session_bp.route('/sessions/tactic/set/<int:session_id>', methods=['POST'])
def set_tactic_index(session_id):
    data = request.get_json()
    new_index = data.get('tactic_index')

    if new_index is None:
        return jsonify({"error": "tactic_index is required"}), 400

    with get_db_connection() as conn:
        ensure_executed_indices_column(conn)
        update_executed_indices(conn, session_id)

        with conn.cursor() as cur:
            cur.execute("SELECT id FROM session WHERE id = %s", (session_id,))
            if not cur.fetchone():
                return jsonify({"error": "Session not found"}), 404

            now = datetime.utcnow()
            cur.execute("""
                UPDATE session
                SET current_tactic_index = %s, current_tactic_started_at = %s
                WHERE id = %s
            """, (new_index, now, session_id))
            conn.commit()

    return jsonify({"success": True, "current_tactic_index": new_index})


@session_bp.route('/sessions/tactic/prev/<int:session_id>', methods=['POST'])
def prev_tactic(session_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, current_tactic_index FROM session WHERE id = %s", (session_id,))
            session = cur.fetchone()
            if not session:
                return jsonify({"error": "Session not found"}), 404

            new_index = max(0, session['current_tactic_index'] - 1)
            now = datetime.utcnow()

            cur.execute("""
                UPDATE session
                SET current_tactic_index = %s, current_tactic_started_at = %s
                WHERE id = %s
            """, (new_index, now, session_id))
            conn.commit()

    return jsonify({"success": True, "current_tactic_index": new_index})


@session_bp.route('/sessions/submit_answer', methods=['POST'])
def submit_answer():
    data = request.get_json()
    student_id = str(data['student_id'])
    session_id = data['session_id']
    tactic_index = data.get('tactic_index', 0)
    score = data.get('score', 0)

    with get_db_connection() as conn:
        ensure_student_progress_table(conn)
        with conn.cursor() as cur:
            # Upsert: permite retentativa na mesma tática e conta as tentativas
            cur.execute("""
                INSERT INTO verified_answers (student_name, student_id, answers, score, session_id, tactic_index, attempts, score_history)
                VALUES (%s, %s, %s, %s, %s, %s, 1, jsonb_build_array(%s::int))
                ON CONFLICT (student_id, session_id, tactic_index)
                DO UPDATE SET
                    answers = EXCLUDED.answers,
                    score = EXCLUDED.score,
                    student_name = EXCLUDED.student_name,
                    attempts = verified_answers.attempts + 1,
                    score_history = verified_answers.score_history || EXCLUDED.score_history
                RETURNING attempts
            """, (
                data['student_name'],
                student_id,
                json.dumps(data['answers']),
                score,
                session_id,
                tactic_index,
                score
            ))
            attempts = cur.fetchone()['attempts']

            total_questions = len(data.get('answers') or []) or 1
            passed = (score / total_questions) >= PASS_THRESHOLD
            # Ultrapassada a última tentativa, o aluno deixa o ciclo de recuperação e prossegue
            forced_advance = (not passed) and attempts > MAX_RECOVERY_CYCLES
            now = datetime.utcnow()

            if passed or forced_advance:
                # Avança para a próxima tática e inicia o timer pessoal da nova tática
                cur.execute("""
                    INSERT INTO student_session_progress (session_id, student_id, current_tactic_index, tactic_started_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (session_id, student_id) DO UPDATE
                    SET current_tactic_index = GREATEST(
                            student_session_progress.current_tactic_index,
                            EXCLUDED.current_tactic_index
                        ),
                        tactic_started_at = CASE
                            WHEN EXCLUDED.current_tactic_index > student_session_progress.current_tactic_index
                            THEN EXCLUDED.tactic_started_at
                            ELSE student_session_progress.tactic_started_at
                        END
                """, (session_id, student_id, tactic_index + 1, now))
            else:
                # Retentativa: reinicia o timer pessoal da mesma tática
                cur.execute("""
                    INSERT INTO student_session_progress (session_id, student_id, current_tactic_index, tactic_started_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (session_id, student_id)
                    DO UPDATE SET tactic_started_at = EXCLUDED.tactic_started_at
                """, (session_id, student_id, tactic_index, now))

            cur.execute("""
                SELECT current_tactic_index, tactic_started_at FROM student_session_progress
                WHERE session_id = %s AND student_id = %s
            """, (session_id, student_id))
            row = cur.fetchone()
            student_tactic_index = row['current_tactic_index'] if row else (tactic_index + 1 if (passed or forced_advance) else tactic_index)
            tactic_started_at_val = row['tactic_started_at'].isoformat() if row and row['tactic_started_at'] else now.isoformat()

            conn.commit()

    logging.info("🔍 submit_answer: student=%s session=%s tactic=%s score=%s passed=%s attempts=%s forced=%s",
                 student_id, session_id, tactic_index, score, passed, attempts, forced_advance)

    return jsonify({
        **data,
        "passed": passed,
        "attempts": attempts,
        "max_recovery_cycles": MAX_RECOVERY_CYCLES,
        "forced_advance": forced_advance,
        "score": score,
        "student_tactic_index": student_tactic_index,
        "tactic_started_at": tactic_started_at_val
    }), 200


@session_bp.route('/sessions/<int:session_id>/student/<string:student_id>/start', methods=['POST'])
def student_start_own(session_id, student_id):
    now = datetime.utcnow()
    with get_db_connection() as conn:
        ensure_student_progress_table(conn)
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO student_session_progress (session_id, student_id, current_tactic_index, tactic_started_at, student_started, should_end_session, executed_tactic_indices, session_plan)
                VALUES (%s, %s, 0, %s, TRUE, FALSE, '[]', NULL)
                ON CONFLICT (session_id, student_id) DO UPDATE
                SET current_tactic_index = 0, tactic_started_at = EXCLUDED.tactic_started_at,
                    student_started = TRUE, should_end_session = FALSE, executed_tactic_indices = '[]', session_plan = NULL
            """, (session_id, str(student_id), now))
            conn.commit()
    return jsonify({"success": True, "tactic_started_at": now.isoformat()}), 200


@session_bp.route('/sessions/<int:session_id>/student/<string:student_id>/tactic_index', methods=['GET'])
def get_student_tactic_index(session_id, student_id):
    with get_db_connection() as conn:
        ensure_student_progress_table(conn)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT current_tactic_index, tactic_started_at, student_started, executed_tactic_indices, session_plan
                FROM student_session_progress
                WHERE session_id = %s AND student_id = %s
            """, (session_id, str(student_id)))
            row = cur.fetchone()
            if row:
                try:
                    executed = json.loads(row['executed_tactic_indices'] or '[]')
                except Exception:
                    executed = []
                return jsonify({
                    "current_tactic_index": row['current_tactic_index'],
                    "tactic_started_at": row['tactic_started_at'].isoformat() if row['tactic_started_at'] else None,
                    "student_started": bool(row['student_started']),
                    "executed_tactic_indices": executed,
                    "session_plan": row['session_plan'],
                }), 200
            # Sem registro: aluno ainda não entrou na sessão
            return jsonify({"current_tactic_index": 0, "tactic_started_at": None, "student_started": False, "executed_tactic_indices": [], "session_plan": None}), 200


@session_bp.route('/sessions/<int:session_id>/student/<string:student_id>/set_tactic', methods=['POST'])
def set_student_tactic(session_id, student_id):
    data = request.get_json() or {}
    new_index = data.get('tactic_index')
    if new_index is None:
        return jsonify({"error": "tactic_index is required"}), 400
    executed_indices = data.get('executed_tactic_indices')
    session_plan = data.get('session_plan')  # optional: raw JSON string
    now = datetime.utcnow()
    with get_db_connection() as conn:
        ensure_student_progress_table(conn)
        with conn.cursor() as cur:
            if executed_indices is not None and session_plan is not None:
                cur.execute("""
                    UPDATE student_session_progress
                    SET current_tactic_index = %s, tactic_started_at = %s, should_end_session = FALSE,
                        executed_tactic_indices = %s, session_plan = %s
                    WHERE session_id = %s AND student_id = %s
                """, (new_index, now, json.dumps(executed_indices), session_plan, session_id, str(student_id)))
            elif executed_indices is not None:
                cur.execute("""
                    UPDATE student_session_progress
                    SET current_tactic_index = %s, tactic_started_at = %s, should_end_session = FALSE,
                        executed_tactic_indices = %s
                    WHERE session_id = %s AND student_id = %s
                """, (new_index, now, json.dumps(executed_indices), session_id, str(student_id)))
            else:
                cur.execute("""
                    UPDATE student_session_progress
                    SET current_tactic_index = %s, tactic_started_at = %s, should_end_session = FALSE
                    WHERE session_id = %s AND student_id = %s
                """, (new_index, now, session_id, str(student_id)))
            conn.commit()
    return jsonify({"success": True, "current_tactic_index": new_index}), 200


@session_bp.route('/sessions/<int:session_id>/student/<string:student_id>/update_session_plan', methods=['POST'])
def update_student_session_plan(session_id, student_id):
    """Atualiza apenas o session_plan sem alterar a tática atual (usado no replanejamento)."""
    data = request.get_json() or {}
    session_plan = data.get('session_plan')
    if session_plan is None:
        return jsonify({"error": "session_plan is required"}), 400
    with get_db_connection() as conn:
        ensure_student_progress_table(conn)
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE student_session_progress
                SET session_plan = %s
                WHERE session_id = %s AND student_id = %s
            """, (session_plan, session_id, str(student_id)))
            conn.commit()
    return jsonify({"success": True}), 200


@session_bp.route('/sessions/<int:session_id>/student/<string:student_id>/set_end_flag', methods=['POST'])
def set_student_end_flag(session_id, student_id):
    with get_db_connection() as conn:
        ensure_student_progress_table(conn)
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE student_session_progress
                SET should_end_session = TRUE
                WHERE session_id = %s AND student_id = %s
            """, (session_id, str(student_id)))
            conn.commit()
    return jsonify({"success": True}), 200


@session_bp.route('/sessions/<int:session_id>/student/<string:student_id>/advance_tactic', methods=['POST'])
def advance_student_tactic(session_id, student_id):
    now = datetime.utcnow()
    with get_db_connection() as conn:
        ensure_student_progress_table(conn)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT current_tactic_index, should_end_session FROM student_session_progress
                WHERE session_id = %s AND student_id = %s
            """, (session_id, str(student_id)))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Progress not found"}), 404
            # Se a flag de encerramento estiver ativa, avança além de todas as táticas
            if row.get('should_end_session'):
                new_index = 9999
            else:
                new_index = row['current_tactic_index'] + 1
            cur.execute("""
                UPDATE student_session_progress
                SET current_tactic_index = %s, tactic_started_at = %s, should_end_session = FALSE
                WHERE session_id = %s AND student_id = %s
            """, (new_index, now, session_id, str(student_id)))
            conn.commit()
    return jsonify({"success": True, "current_tactic_index": new_index}), 200


@session_bp.route('/sessions/<int:session_id>/set_adaptive_tactic', methods=['POST'])
def set_adaptive_tactic(session_id):
    data = request.get_json() or {}
    enabled = bool(data.get('enabled', False))
    with get_db_connection() as conn:
        ensure_adaptive_tactic_column(conn)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE session SET adaptive_tactic_enabled = %s WHERE id = %s",
                (enabled, session_id)
            )
            conn.commit()
    return jsonify({"success": True, "adaptive_tactic_enabled": enabled}), 200


@session_bp.route('/sessions/<int:session_id>/set_reuso_cooldown', methods=['POST'])
def set_reuso_cooldown(session_id):
    """Ativa/desativa o tempo de espera após nota < 70% no Reuso. Só pode mudar fora de sessão em andamento."""
    data = request.get_json() or {}
    enabled = bool(data.get('enabled', True))
    with get_db_connection() as conn:
        ensure_adaptive_tactic_column(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM session WHERE id = %s", (session_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Session not found"}), 404
            if row['status'] == 'in-progress':
                return jsonify({"error": "Não é possível alterar durante uma sessão em andamento."}), 409
            cur.execute(
                "UPDATE session SET reuso_cooldown_enabled = %s WHERE id = %s",
                (enabled, session_id)
            )
            conn.commit()
    return jsonify({"success": True, "reuso_cooldown_enabled": enabled}), 200


@session_bp.route('/sessions/<int:session_id>/students/progress', methods=['GET'])
def get_students_progress(session_id):
    with get_db_connection() as conn:
        ensure_student_progress_table(conn)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT student_id, current_tactic_index
                FROM student_session_progress
                WHERE session_id = %s
                ORDER BY student_id
            """, (session_id,))
            rows = cur.fetchall()
            return jsonify([dict(r) for r in rows]), 200


@session_bp.route("/sessions/add_extra_notes", methods=["POST"])
def add_extra_notes():
    logging.basicConfig(level=logging.INFO)
    logging.info("oiiiiiii")
    sys.stdout.flush()

    data = request.json

    extra_notes = float(data.get("extra_notes", 0.0))
    session_id = int(data.get("session_id"))
    student_id = int(data.get("student_id", 0))
    estudante_username = data.get("estudante_username", "")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Check if exists
            cur.execute("""
                SELECT id FROM extra_notes
                WHERE estudante_username = %s AND session_id = %s
            """, (estudante_username, session_id))
            existing_note = cur.fetchone()

            if existing_note:
                cur.execute("""
                    UPDATE extra_notes
                    SET extra_notes = %s
                    WHERE id = %s
                """, (extra_notes, existing_note['id']))
                conn.commit()
                return jsonify({"message": "Extra notes updated successfully"}), 200

            cur.execute("""
                INSERT INTO extra_notes (estudante_username, student_id, extra_notes, session_id)
                VALUES (%s, %s, %s, %s)
            """, (estudante_username, student_id, extra_notes, session_id))
            conn.commit()

            # Logging new note info for consistency with previous code
            logging.info("🔍 new_note inserted for student_id: %s", student_id)
            sys.stdout.flush()

    return jsonify({"message": "Extra notes added successfully"}), 201


@session_bp.route('/sessions/enter', methods=['POST'])
def enter_session():
    data = request.get_json()

    session_code = data.get('session_code')
    requester_id = str(data.get('requester_id')) # Ensure string for DB consistency
    user_type = data.get('type') # 'type' is a built-in function name

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM session WHERE code = %s", (session_code,))
            session = cur.fetchone()

            if not session:
                return jsonify({"error": "Session not found"}), 404

            session_id = session['id']

            # Check if already enrolled to avoid duplicates or error
            if user_type == 'student':
                cur.execute("SELECT 1 FROM session_students WHERE session_id = %s AND student_id = %s", (session_id, requester_id))
                if not cur.fetchone():
                    cur.execute("INSERT INTO session_students (session_id, student_id) VALUES (%s, %s)", (session_id, requester_id))
                    conn.commit()

                # Inicializa progresso individual a partir da tática atual da sessão
                ensure_student_progress_table(conn)
                cur.execute("""
                    SELECT current_tactic_index, current_tactic_started_at, status
                    FROM session WHERE id = %s
                """, (session_id,))
                sess = cur.fetchone()
                if sess and sess['status'] == 'in-progress':
                    cur.execute("""
                        INSERT INTO student_session_progress (session_id, student_id, current_tactic_index, tactic_started_at, student_started)
                        VALUES (%s, %s, 0, NULL, FALSE)
                        ON CONFLICT (session_id, student_id) DO NOTHING
                    """, (session_id, requester_id))
                    conn.commit()
            else:
                cur.execute("SELECT 1 FROM session_teachers WHERE session_id = %s AND teacher_id = %s", (session_id, requester_id))
                if not cur.fetchone():
                    cur.execute("INSERT INTO session_teachers (session_id, teacher_id) VALUES (%s, %s)", (session_id, requester_id))
                    conn.commit()

    return jsonify({"success": "Entered session successfully"}), 200

@session_bp.route('/sessions/<int:session_id>/change_strategy', methods=['POST'])
def change_session_strategy(session_id):
    data = request.get_json()
    new_strategy_id = data.get('strategy_id')

    if not new_strategy_id:
        return jsonify({"error": "Strategy ID is required"}), 400

    with get_db_connection() as conn:
        ensure_end_flag_column(conn)
        ensure_executed_indices_column(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM session WHERE id = %s", (session_id,))
            if not cur.fetchone():
                return jsonify({"error": "Session not found"}), 404

            cur.execute("DELETE FROM session_strategies WHERE session_id = %s", (session_id,))
            cur.execute("INSERT INTO session_strategies (session_id, strategy_id) VALUES (%s, %s)", (session_id, str(new_strategy_id)))

            cur.execute("DELETE FROM verified_answers WHERE session_id = %s", (session_id,))

            start_time = datetime.utcnow()
            cur.execute("""
                UPDATE session
                SET status = 'in-progress',
                    start_time = %s,
                    current_tactic_index = 0,
                    current_tactic_started_at = %s,
                    end_on_next_completion = FALSE,
                    executed_indices = '[]'
                WHERE id = %s
            """, (start_time, start_time, session_id))

            conn.commit()

    return jsonify({"success": "Strategy changed and session restarted!"}), 200


@session_bp.route('/sessions/<int:session_id>/change_domain', methods=['POST'])
def change_session_domain(session_id):
    data = request.get_json()
    new_domain_id = data.get('domain_id')

    if not new_domain_id:
        return jsonify({"error": "Domain ID is required"}), 400

    with get_db_connection() as conn:
        ensure_end_flag_column(conn)
        ensure_executed_indices_column(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM session WHERE id = %s", (session_id,))
            if not cur.fetchone():
                return jsonify({"error": "Session not found"}), 404

            cur.execute("DELETE FROM session_domains WHERE session_id = %s", (session_id,))
            cur.execute("INSERT INTO session_domains (session_id, domain_id) VALUES (%s, %s)", (session_id, str(new_domain_id)))

            cur.execute("DELETE FROM verified_answers WHERE session_id = %s", (session_id,))

            start_time = datetime.utcnow()
            cur.execute("""
                UPDATE session
                SET status = 'in-progress',
                    start_time = %s,
                    current_tactic_index = 0,
                    current_tactic_started_at = %s,
                    end_on_next_completion = FALSE,
                    executed_indices = '[]'
                WHERE id = %s
            """, (start_time, start_time, session_id))

            conn.commit()

    return jsonify({"success": "Domain changed and session restarted!"}), 200

# ============================
# RATING ROUTES
# ============================

@session_bp.route('/sessions/<int:session_id>/rate', methods=['POST'])
def rate_session(session_id):
    data = request.get_json()
    student_id = str(data.get('student_id'))
    rating = int(data.get('rating'))

    if not (1 <= rating <= 5):
        return jsonify({"error": "Rating must be between 1 and 5"}), 400

    with get_db_connection() as conn:
        ensure_rating_tables(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM session WHERE id = %s", (session_id,))
            if not cur.fetchone():
                return jsonify({"error": "Session not found"}), 404

            # Upsert Rating
            cur.execute("""
                INSERT INTO session_ratings (session_id, student_id, rating)
                VALUES (%s, %s, %s)
                ON CONFLICT (session_id, student_id)
                DO UPDATE SET rating = EXCLUDED.rating
            """, (session_id, student_id, rating))

            # Recalculate Average
            cur.execute("""
                SELECT AVG(rating) as avg, COUNT(*) as cnt
                FROM session_ratings
                WHERE session_id = %s
            """, (session_id,))
            row = cur.fetchone()
            new_avg = row['avg'] or 0.0
            new_count = row['cnt'] or 0

            # Update Session Table
            cur.execute("""
                UPDATE session
                SET rating_average = %s, rating_count = %s
                WHERE id = %s
            """, (new_avg, new_count, session_id))

            conn.commit()

    return jsonify({"success": True, "average": new_avg, "count": new_count}), 200

@session_bp.route('/sessions/<int:session_id>/rating', methods=['GET'])
def get_session_rating(session_id):
    student_id = request.args.get('student_id')

    with get_db_connection() as conn:
        ensure_rating_tables(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT rating_average, rating_count FROM session WHERE id = %s", (session_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Session not found"}), 404

            result = {
                "average": row['rating_average'] if row['rating_average'] is not None else 0.0,
                "count": row['rating_count'] if row['rating_count'] is not None else 0,
                "user_rating": None
            }

            if student_id:
                cur.execute("SELECT rating FROM session_ratings WHERE session_id = %s AND student_id = %s", (session_id, str(student_id)))
                user_row = cur.fetchone()
                if user_row:
                    result['user_rating'] = user_row['rating']

    return jsonify(result), 200
