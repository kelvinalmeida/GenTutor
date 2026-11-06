import logging
from flask import Blueprint, jsonify, request

agente_teacher_report_bp = Blueprint('agente_teacher_report_bp', __name__)


@agente_teacher_report_bp.route('/sessions/<int:session_id>/alerts', methods=['GET'])
def get_session_alerts(session_id):
    """Retorna os alertas de nota baixa de uma sessão, do mais recente ao mais antigo."""
    from app.models import SessionAlert
    alerts = (
        SessionAlert.query
        .filter_by(session_id=session_id, alert_type='low_score')
        .order_by(SessionAlert.created_at.desc())
        .all()
    )
    return jsonify([
        {
            "id": a.id,
            "student_id": a.student_id,
            "student_name": a.student_name,
            "student_email": a.student_email,
            "alert_type": a.alert_type,
            "score": a.score,
            "attempt": a.attempt,
            "tactic_index": a.tactic_index,
            "message": a.message,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in alerts
    ]), 200


@agente_teacher_report_bp.route('/sessions/<int:session_id>/alerts/low_score', methods=['POST'])
def create_low_score_alert_route(session_id):
    """
    Chamado pelo Orquestrador a cada tentativa com menos de 70% nos exercícios de Reuso.
    Body: { student_id, score_pct, attempt, tactic_index, received_material }
    """
    from app.scheduler import create_low_score_alert
    data = request.get_json() or {}
    try:
        student_id = int(data['student_id'])
        score_pct = int(data.get('score_pct', 0))
        attempt = int(data.get('attempt') or 1)
        tactic_index = data.get('tactic_index')
        tactic_index = int(tactic_index) if tactic_index is not None else None
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "student_id, score_pct e attempt são obrigatórios"}), 400

    try:
        alert, created = create_low_score_alert(
            session_id, student_id, score_pct, attempt,
            tactic_index=tactic_index,
            received_material=bool(data.get('received_material', True)),
        )
        return jsonify({"id": alert.id, "created": created}), 201 if created else 200
    except Exception as e:
        logging.error("[Alertas] Erro ao criar alerta sessão=%s aluno=%s: %s", session_id, student_id, e)
        return jsonify({"error": str(e)}), 500
