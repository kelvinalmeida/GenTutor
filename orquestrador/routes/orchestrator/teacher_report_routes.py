import requests
from flask import Blueprint, jsonify, request, render_template
from routes.auth import token_required
from routes.services_routs import STRATEGIES_URL

teacher_report_bp = Blueprint('teacher_report_bp', __name__)


@teacher_report_bp.route('/teacher/report', methods=['GET'])
@token_required
def view_report(current_user):
    teacher_id = current_user.get('id')
    report = None
    no_report = True

    try:
        resp = requests.get(f"{STRATEGIES_URL}/agent/teacher_report/{teacher_id}", timeout=10)
        if resp.status_code == 200:
            report = resp.json()
            no_report = False
    except Exception:
        pass

    return render_template('teacher/report.html', report=report, no_report=no_report)


@teacher_report_bp.route('/teacher/report/feedback', methods=['POST'])
@token_required
def submit_feedback(current_user):
    data = request.get_json() or {}
    report_id = data.get('report_id')
    feedback = data.get('feedback', '').strip()
    rating = data.get('rating')

    if not report_id or not feedback:
        return jsonify({"error": "report_id e feedback são obrigatórios"}), 400

    try:
        resp = requests.post(
            f"{STRATEGIES_URL}/agent/teacher_report/{report_id}/feedback",
            json={"feedback": feedback, "rating": rating},
            timeout=10
        )
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@teacher_report_bp.route('/teacher/report/trigger', methods=['POST'])
@token_required
def trigger_report(current_user):
    """Dispara geração imediata (para testes)."""
    try:
        resp = requests.post(f"{STRATEGIES_URL}/agent/trigger_teacher_reports", timeout=5)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500
