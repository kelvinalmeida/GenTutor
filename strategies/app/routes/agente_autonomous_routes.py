import json
import logging
import os
import threading
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app
from db import create_connection

agente_autonomous_bp = Blueprint('agente_autonomous_bp', __name__)


def _get_conn():
    db_url = current_app.config.get("SQLALCHEMY_DATABASE_URI") or os.getenv("DATABASE_URL")
    return create_connection(db_url)


@agente_autonomous_bp.route('/agent/autonomous/run', methods=['POST'])
def trigger_autonomous_agent():
    """
    Dispara manualmente o agente autônomo de estratégias para um aluno em uma sessão.
    Útil para testes e para o orquestrador chamar sob demanda.
    Body: { "session_id": int, "student_id": int }
    """
    data = request.get_json() or {}
    session_id = data.get('session_id')
    student_id = data.get('student_id')

    if not session_id or not student_id:
        return jsonify({"error": "session_id e student_id são obrigatórios"}), 400

    app = current_app._get_current_object()

    def run_in_thread():
        with app.app_context():
            from app.routes.agente_core import run_strategies_agent
            run_strategies_agent(int(session_id), int(student_id))

    thread = threading.Thread(target=run_in_thread, daemon=True)
    thread.start()

    return jsonify({
        "success": True,
        "message": f"Agente iniciado para sessão {session_id}, aluno {student_id}.",
        "status": "running_async"
    }), 202


@agente_autonomous_bp.route('/agent/autonomous/run/sync', methods=['POST'])
def trigger_autonomous_agent_sync():
    """
    Versão síncrona do trigger — aguarda a resposta completa do agente.
    Body: { "session_id": int, "student_id": int }
    """
    data = request.get_json() or {}
    session_id = data.get('session_id')
    student_id = data.get('student_id')

    if not session_id or not student_id:
        return jsonify({"error": "session_id e student_id são obrigatórios"}), 400

    from app.routes.agente_core import run_strategies_agent
    result = run_strategies_agent(int(session_id), int(student_id))
    return jsonify(result), 200


@agente_autonomous_bp.route('/agent/autonomous/pending', methods=['GET'])
def get_pending_intervention():
    """
    Retorna a intervenção pendente mais recente para um aluno em uma sessão.
    Usado pelo orquestrador antes de chamar o AI de tática para verificar se o agente
    já decidiu a próxima tática.
    Query params: session_id, student_id
    """
    session_id = request.args.get('session_id')
    student_id = request.args.get('student_id')

    if not session_id or not student_id:
        return jsonify({"pending": False}), 200

    conn = _get_conn()
    if not conn:
        return jsonify({"pending": False, "error": "banco indisponível"}), 200

    try:
        from app.routes.agente_core import _ensure_intervention_table
        _ensure_intervention_table(conn)

        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, target_tactic_index, reason, created_at
                FROM agent_pending_interventions
                WHERE session_id = %s
                  AND student_id = %s
                  AND applied = FALSE
                ORDER BY created_at DESC
                LIMIT 1
            """, (int(session_id), int(student_id)))
            row = cur.fetchone()

        if not row:
            return jsonify({"pending": False}), 200

        return jsonify({
            "pending": True,
            "intervention_id": row['id'],
            "target_tactic_index": row['target_tactic_index'],
            "reason": row['reason'],
            "created_at": str(row['created_at'])
        }), 200
    except Exception as e:
        logging.error("[AutonomousRoutes] get_pending_intervention: %s", e)
        return jsonify({"pending": False, "error": str(e)}), 200
    finally:
        conn.close()


@agente_autonomous_bp.route('/agent/autonomous/pending/<int:intervention_id>/mark_applied', methods=['POST'])
def mark_intervention_applied(intervention_id):
    """
    Marca uma intervenção como aplicada. Chamado pelo orquestrador após executar a mudança de tática.
    """
    conn = _get_conn()
    if not conn:
        return jsonify({"success": False, "error": "banco indisponível"}), 500
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE agent_pending_interventions
                SET applied = TRUE, applied_at = NOW()
                WHERE id = %s
            """, (intervention_id,))
            conn.commit()
        return jsonify({"success": True}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()


@agente_autonomous_bp.route('/agent/autonomous/learning_log', methods=['GET'])
def get_learning_log():
    """
    Retorna o log de aprendizado do agente.
    Query params: student_id (opcional), limit (padrão 20)
    """
    student_id = request.args.get('student_id')
    limit = int(request.args.get('limit', 20))

    conn = _get_conn()
    if not conn:
        return jsonify({"error": "banco indisponível"}), 500
    try:
        from app.routes.agente_core import _ensure_learning_log_table
        _ensure_learning_log_table(conn)

        with conn.cursor() as cur:
            if student_id:
                cur.execute("""
                    SELECT id, session_id, student_id, tactic_name, student_pref_content_type,
                           mastery_before, mastery_after, score_improvement, was_effective,
                           reasoning, created_at
                    FROM strategy_learning_log
                    WHERE student_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (int(student_id), limit))
            else:
                cur.execute("""
                    SELECT id, session_id, student_id, tactic_name, student_pref_content_type,
                           mastery_before, mastery_after, score_improvement, was_effective,
                           reasoning, created_at
                    FROM strategy_learning_log
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (limit,))
            rows = [dict(r) for r in cur.fetchall()]

        for row in rows:
            if row.get('created_at'):
                row['created_at'] = str(row['created_at'])

        return jsonify({"count": len(rows), "log": rows}), 200
    except Exception as e:
        logging.error("[AutonomousRoutes] get_learning_log: %s", e)
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@agente_autonomous_bp.route('/agent/autonomous/effectiveness', methods=['POST'])
def close_session_effectiveness():
    """
    Chamado ao fim de uma sessão para preencher mastery_after e was_effective
    no log de aprendizado, fechando o ciclo de feedback.
    Body: { "session_id": int, "student_id": int, "mastery_after": float, "score_improvement": float }
    """
    data = request.get_json() or {}
    session_id = data.get('session_id')
    student_id = data.get('student_id')
    mastery_after = data.get('mastery_after')
    score_improvement = data.get('score_improvement', 0)

    if not session_id or not student_id:
        return jsonify({"error": "session_id e student_id são obrigatórios"}), 400

    conn = _get_conn()
    if not conn:
        return jsonify({"error": "banco indisponível"}), 500
    try:
        with conn.cursor() as cur:
            was_effective = (mastery_after is not None and mastery_after > 50) or score_improvement > 10
            cur.execute("""
                UPDATE strategy_learning_log
                SET mastery_after = %s,
                    score_improvement = %s,
                    was_effective = %s
                WHERE session_id = %s
                  AND student_id = %s
                  AND mastery_after IS NULL
            """, (mastery_after, score_improvement, was_effective, int(session_id), int(student_id)))

            if was_effective:
                cur.execute("""
                    SELECT tactic_name FROM strategy_learning_log
                    WHERE session_id = %s AND student_id = %s
                    ORDER BY created_at DESC LIMIT 1
                """, (int(session_id), int(student_id)))
                row = cur.fetchone()
                if row and row.get('tactic_name'):
                    cur.execute("""
                        UPDATE strategies
                        SET score = LEAST(10, ROUND((0.8 * score + 0.2 * 10)::numeric, 0))
                        WHERE name ILIKE %s
                    """, (f"%{row['tactic_name']}%",))

            conn.commit()

        return jsonify({"success": True, "was_effective": was_effective}), 200
    except Exception as e:
        conn.rollback()
        logging.error("[AutonomousRoutes] close_session_effectiveness: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()
