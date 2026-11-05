import requests
import logging
from flask import Blueprint, jsonify, request
from ...services_routs import CONTROL_URL, STRATEGIES_URL, USER_URL, DOMAIN_URL

logging.basicConfig(level=logging.INFO)

agente_memory_bp = Blueprint('agente_memory_bp', __name__)


def _build_exercise_context(session_id):
    """Retorna {exercise_id: exercise_data} para todos os exercícios da sessão."""
    exercise_context = {}
    try:
        session_resp = requests.get(f"{CONTROL_URL}/sessions/{session_id}", timeout=10)
        if session_resp.status_code != 200:
            return exercise_context
        domain_ids = (session_resp.json() or {}).get('domains', [])
        for domain_id in domain_ids:
            try:
                ex_resp = requests.get(f"{DOMAIN_URL}/domains/{int(domain_id)}/exercises", timeout=10)
                if ex_resp.status_code == 200:
                    for ex in (ex_resp.json() or []):
                        if isinstance(ex, dict) and ex.get('id') is not None:
                            exercise_context[str(ex['id'])] = ex
            except Exception:
                pass
    except Exception as e:
        logging.warning("Erro ao construir contexto de exercícios session_id=%s: %s", session_id, e)
    return exercise_context


@agente_memory_bp.route('/orchestrator/agent/save_session_memory', methods=['POST'])
def save_session_memory():
    """
    Chamado ao fim da sessão de um aluno.
    Agrega dados de desempenho e delega ao serviço user a geração e persistência
    do resumo de memória para uso em sessões futuras.
    """
    data = request.get_json() or {}
    student_id = data.get('student_id')
    session_id = data.get('session_id')

    if student_id is None or session_id is None:
        return jsonify({"error": "student_id e session_id são obrigatórios"}), 400

    try:
        # 1. Dados da sessão
        session_resp = requests.get(f"{CONTROL_URL}/sessions/{session_id}", timeout=10)
        if session_resp.status_code != 200:
            return jsonify({"error": "Falha ao buscar sessão"}), 502
        session_data = session_resp.json()

        # 2. Notas do aluno nesta sessão
        verified = [
            v for v in session_data.get('verified_answers', [])
            if str(v.get('student_id', '')) == str(student_id)
        ]
        scores = [v.get('score', 0) for v in verified]

        # 3. Nomes de todas as táticas da estratégia
        strategy_ids = session_data.get('strategies', [])
        strategy_id = strategy_ids[0] if strategy_ids else None
        tactics_names = []
        if strategy_id:
            try:
                strat_resp = requests.get(f"{STRATEGIES_URL}/strategies/{strategy_id}", timeout=10)
                if strat_resp.status_code == 200:
                    all_tactics = strat_resp.json().get('tatics', [])
                    tactics_names = [t.get('name', '') for t in all_tactics]
            except Exception as e:
                logging.warning("Erro ao buscar táticas strategy_id=%s: %s", strategy_id, e)

        # 4. Salva memória via serviço user (que chama o LLM e persiste)
        save_resp = requests.post(
            f"{USER_URL}/agent/save_session_memory",
            json={
                "student_id": student_id,
                "session_id": session_id,
                "scores": scores,
                "tactics_names": tactics_names,
            },
            timeout=30
        )

        if save_resp.status_code != 200:
            logging.error("Falha ao salvar memória: %s", save_resp.text)
            return jsonify({"error": "Falha ao salvar memória"}), 502

        return jsonify(save_resp.json()), 200

    except Exception as e:
        logging.error("Erro em save_session_memory orchestrator: %s", str(e))
        return jsonify({"error": str(e)}), 500


