import logging
from flask import Blueprint, jsonify

agente_teacher_report_bp = Blueprint('agente_teacher_report_bp', __name__)


@agente_teacher_report_bp.route('/sessions/<int:session_id>/alerts', methods=['GET'])
def get_session_alerts(session_id):
    """Retorna todos os alertas de maestria de uma sessão, do mais recente ao mais antigo."""
    from app.models import SessionAlert
    alerts = (
        SessionAlert.query
        .filter_by(session_id=session_id)
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
            "concept": a.concept,
            "mastery_pct": a.mastery_pct,
            "score": a.score,
            "message": a.message,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in alerts
    ]), 200


